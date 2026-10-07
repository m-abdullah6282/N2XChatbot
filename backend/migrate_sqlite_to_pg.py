"""One-shot: copy every row from SQLite chatbot.db into Postgres.

WARNING: this TRUNCATEs the Postgres tables first so SQLite ids land
identically — agent_id values in Qdrant will then match.
"""
import os
import sqlite3
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Load backend/.env automatically so we use the same DATABASE_URL the app uses.
load_dotenv(Path(__file__).parent / ".env")

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "chatbot.db")
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit(
        "DATABASE_URL not found. Set it in backend/.env or pass it as an env var."
    )

print(f"SQLite: {SQLITE_PATH}")
print(f"Postgres: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else '(local)'}")

TABLES = [
    "admin_users",
    "plans",
    "agents",
    "admin_sessions",
    "api_keys",
    "documents",
    "messages",
    "handoffs",
    "subscriptions",
    "payments",
    "usage_records",
]


def main():
    if not os.path.isfile(SQLITE_PATH):
        raise SystemExit(f"SQLite file not found: {SQLITE_PATH}")

    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as dst:
        # ---- 1. Wipe existing Postgres data ----
        print("Wiping Postgres tables (RESTART IDENTITY CASCADE)...")
        for table in reversed(TABLES):
            try:
                dst.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
            except Exception as exc:
                print(f"  truncate {table}: {exc}")
        dst.commit()

        # ---- 2. Copy rows ----
        for table in TABLES:
            try:
                rows = src.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.OperationalError:
                print(f"{table}: table missing in SQLite, skipped")
                continue
            if not rows:
                print(f"{table}: 0 rows")
                continue

            cols = list(rows[0].keys())
            col_list = ", ".join(cols)
            placeholders = ", ".join(["%s"] * len(cols))

            # `id` is GENERATED ALWAYS AS IDENTITY in Postgres, which blocks
            # explicit id inserts unless we use OVERRIDING SYSTEM VALUE. Tables
            # like admin_sessions have no `id` column at all, so only add the
            # clause when it applies.
            has_id = "id" in cols
            overriding = " OVERRIDING SYSTEM VALUE" if has_id else ""
            sql = f"INSERT INTO {table} ({col_list}){overriding} VALUES ({placeholders})"

            ok = 0
            fail = 0
            for r in rows:
                row_id = r["id"] if has_id else "(no id)"
                try:
                    # Savepoint per row: a single failure rolls back only that
                    # row, not the whole table's transaction.
                    dst.execute("SAVEPOINT row_sp")
                    dst.execute(sql, tuple(r))
                    dst.execute("RELEASE SAVEPOINT row_sp")
                    ok += 1
                except Exception as exc:
                    try:
                        dst.execute("ROLLBACK TO SAVEPOINT row_sp")
                        dst.execute("RELEASE SAVEPOINT row_sp")
                    except Exception:
                        pass
                    fail += 1
                    print(f"  {table} id={row_id}: {exc}")

            # ---- 3. Advance the identity sequence past the max id ----
            if has_id:
                try:
                    dst.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE(MAX(id), 1)) FROM {table}"
                    )
                except Exception as exc:
                    print(f"  seq reset {table}: {exc}")

            dst.commit()
            print(f"{table}: {ok}/{len(rows)} migrated, {fail} failed")

    print("Done.")


if __name__ == "__main__":
    main()