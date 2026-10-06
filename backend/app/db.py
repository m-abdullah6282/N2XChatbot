import hashlib
import hmac
import logging
import os
import re
import secrets
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, DATABASE_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Postgres date/time helpers.
#
# We keep TEXT columns (not TIMESTAMPTZ) so the exact SQLite string format
# "YYYY-MM-DD HH:MM:SS" is preserved. All existing analytics (`_period_cutoff`,
# string comparison `created_at >= ?`, `date(created_at)` groups, frontend
# display) keep working unchanged.
# ---------------------------------------------------------------------------
NOW_SQL = "to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"
PLUS_30_DAYS_SQL = "to_char(NOW() AT TIME ZONE 'UTC' + INTERVAL '30 days', 'YYYY-MM-DD HH24:MI:SS')"
PLUS_1_YEAR_SQL = "to_char(NOW() AT TIME ZONE 'UTC' + INTERVAL '1 year', 'YYYY-MM-DD HH24:MI:SS')"
PLUS_1000_YEARS_SQL = "to_char(NOW() AT TIME ZONE 'UTC' + INTERVAL '1000 years', 'YYYY-MM-DD HH24:MI:SS')"

# Sentinels that callers (admin.py) can pass as period start/end to ask for
# SQL expressions without string-injecting raw SQL.
SQL_NOW = "__SQL_NOW__"
SQL_PLUS_30 = "__SQL_PLUS_30__"
SQL_PLUS_1Y = "__SQL_PLUS_1Y__"
SQL_PLUS_1000Y = "__SQL_PLUS_1000Y__"

_SQL_EXPR = {
    SQL_NOW: NOW_SQL,
    SQL_PLUS_30: PLUS_30_DAYS_SQL,
    SQL_PLUS_1Y: PLUS_1_YEAR_SQL,
    SQL_PLUS_1000Y: PLUS_1000_YEARS_SQL,
}

# ---------------------------------------------------------------------------
# Connection pool. Sync pool is correct here because FastAPI runs our sync
# (`def`) endpoints in its threadpool, so each request gets its own thread
# and its own pooled connection. `dict_row` gives us SQLite-Row-like access
# (row["col"] and dict(row)).
# ---------------------------------------------------------------------------
_pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=10,
    open=True,
    kwargs={"row_factory": dict_row},
)


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Yield a pooled connection inside a transaction. Commits on clean exit,
    rolls back on exception, returns the connection to the pool in all cases."""
    with _pool.connection() as conn:
        yield conn


def _column_exists(conn: psycopg.Connection, table: str, column: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s",
        (table, column),
    ).fetchone()
    return row is not None


def _ensure_column(
    conn: psycopg.Connection, table: str, column: str, definition: str
) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with get_conn() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                was_fallback INTEGER NOT NULL DEFAULT 0,
                agent_id INTEGER,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                api_key TEXT NOT NULL UNIQUE,
                api_key_hash TEXT,
                label TEXT NOT NULL,
                admin_id INTEGER,
                agent_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_used_at TEXT,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL,
                greeting TEXT NOT NULL,
                owner_admin_id INTEGER REFERENCES admin_users(id),
                slug TEXT,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS handoffs (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                session_id TEXT NOT NULL,
                agent_id INTEGER,
                question TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL}),
                status TEXT NOT NULL DEFAULT 'pending',
                resolved_at TEXT
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                agent_id INTEGER REFERENCES agents(id),
                owner_admin_id INTEGER REFERENCES admin_users(id),
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                file_path TEXT,
                file_size INTEGER NOT NULL DEFAULT 0,
                chunks_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL}),
                updated_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                price REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'PKR',
                billing_interval TEXT NOT NULL DEFAULT 'monthly',
                max_agents INTEGER,
                max_support_agents INTEGER,
                unlimited_ai_agents INTEGER NOT NULL DEFAULT 0,
                unlimited_support_agents INTEGER NOT NULL DEFAULT 0,
                max_documents INTEGER,
                unlimited_documents INTEGER NOT NULL DEFAULT 0,
                max_messages_per_period INTEGER,
                unlimited_messages INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL}),
                updated_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                admin_id INTEGER NOT NULL REFERENCES admin_users(id),
                plan_id INTEGER NOT NULL REFERENCES plans(id),
                status TEXT NOT NULL DEFAULT 'pending',
                current_period_start TEXT,
                current_period_end TEXT,
                cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL}),
                updated_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                admin_id INTEGER NOT NULL REFERENCES admin_users(id),
                subscription_id INTEGER REFERENCES subscriptions(id),
                provider TEXT NOT NULL DEFAULT 'manual',
                transaction_id TEXT,
                amount REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'PKR',
                status TEXT NOT NULL DEFAULT 'pending',
                provider_reference TEXT,
                provider_response TEXT,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL}),
                updated_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS usage_records (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                admin_id INTEGER NOT NULL REFERENCES admin_users(id),
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT ({NOW_SQL}),
                updated_at TEXT NOT NULL DEFAULT ({NOW_SQL})
            )
            """
        )

        _ensure_column(conn, "messages", "was_fallback", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "messages", "agent_id", "INTEGER")
        _ensure_column(conn, "admin_sessions", "admin_user_id", "INTEGER")
        _ensure_column(conn, "admin_users", "role", "TEXT NOT NULL DEFAULT 'admin'")
        _ensure_column(conn, "agents", "owner_admin_id", "INTEGER REFERENCES admin_users(id)")
        _ensure_column(conn, "agents", "slug", "TEXT")
        _ensure_column(conn, "agents", "description", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "agents", "primary_color", "TEXT NOT NULL DEFAULT '#2563EB'")
        _ensure_column(conn, "api_keys", "admin_id", "INTEGER")
        _ensure_column(conn, "api_keys", "agent_id", "INTEGER")
        _ensure_column(conn, "api_keys", "is_active", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "api_keys", "last_used_at", "TEXT")
        _ensure_column(conn, "api_keys", "api_key_hash", "TEXT")
        _ensure_column(conn, "plans", "max_support_agents", "INTEGER")
        _ensure_column(conn, "plans", "unlimited_ai_agents", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "plans", "unlimited_support_agents", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "plans", "unlimited_documents", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "plans", "unlimited_messages", "INTEGER NOT NULL DEFAULT 0")

        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_slug ON agents(slug)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_scope_filename "
            "ON documents(agent_id, filename)"
        )

    # Backfills / seeds run in their own transactions so a failure in one
    # does not roll back the schema creation above.
    seed_default_agent()
    seed_default_admin()
    backfill_agent_owners()
    backfill_agent_slugs()
    backfill_agent_descriptions()
    seed_plans()
    rename_plan()
    backfill_subscriptions()
    backfill_documents()
    backfill_api_key_hashes()
    scrub_plaintext_api_keys()
    backfill_message_agent_ids()


NO_RELEVANT_CONTEXT_FOUND = "NO_RELEVANT_CONTEXT_FOUND"

FALLBACK_MESSAGE = (
    "Mujhe iski exact information nahi mili. "
    "Main aapko hamare team se connect kar deta hoon."
)

FALLBACK_MESSAGE_KB = (
    "Sorry, is sawal ka jawab mere knowledge base mein nahi hai. "
    "Kya aap dobara puch sakte hain ya koi aur sawal hai?"
)


# ---------------------------------------------------------------------------
# Agent-aware context search helpers
# ---------------------------------------------------------------------------

def _get_agent_uploaded_files_dir(agent_id: int | None = None) -> str:
    """Return the folder path for uploaded files, scoped by agent.

    - agent_id=None  -> shared root:  <project>/uploaded_files/
    - agent_id given -> agent folder: <project>/uploaded_files/agent_<id>/
    """
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploaded_files")
    if agent_id is None:
        return base
    return os.path.join(base, f"agent_{agent_id}")


SYSTEM_PROMPT_TEMPLATE = f"""You are {{agent_name}}. {{agent_description}}

UNIVERSAL RULES — follow these for every conversation:

1. Language & greeting: Reply in the SAME language the user writes in (Roman Urdu/Hindi -> Roman Urdu/Hindi, English -> English). NEVER use "Namaste", "Namastey" or "Namaskar". Keep greetings simple and neutral: use "Hi" or "Hello" (optionally "Assalam-o-Alaikum" in Roman Urdu chats). Avoid any religious or region-specific greetings.

2. Roman Urdu is written informally with many spellings. Understand intent regardless of spelling/small typos. For example: "kasiay/kese/kaise" all mean "kaise" (how), "pr/per/par" all mean "par" (at/on), "kru/karo/karu" mean "karein" (to do), "aat/baat/bat" all mean "baat" (talk).

3. CRITICAL — "baat" means "contact": "baat karna", "baat kaha", "raabta", "milna", "contact", "office", "address" all mean getting in touch via the contact details. When the user asks how/where to talk to or contact you, ALWAYS directly give the contact details from the context (website, email, phone, address). Do not deflect with a generic "ask me about services" reply.

4. STEP 1 - CLASSIFY the user's message into one of two types:
  - TYPE A (CASUAL / SMALL TALK): greetings ("hi", "hello", "salam", "hey", "good morning"), how-are-you questions ("kya haal hai", "kaise ho", "what's up"), thanks, farewells, or any non-informational remark.
  - TYPE B (FACTUAL QUESTION): a genuine request for information about the agent's topic (services, projects, pricing, portfolio, contact details, etc.).
STEP 2 - RESPOND according to the type:
  - TYPE A (CASUAL): reply naturally, warmly and conversationally in the user's language, keeping your persona/tone. You do NOT need the Context below and you MUST NEVER use the fallback message for them.
  - TYPE B (FACTUAL): answer ONLY from the Context below, but interpret it FLEXIBLY. Roman-Urdu/Hinglish requests for a list use many phrasings: "projects k naam btao", "pojects k naam batayein", "jo jo projects kiye", "projecton ke names", "kaam ki list", "services ka list", "kya services hain" ALL mean the same thing. When the Context contains a projects / products / services / pricing section, ALWAYS extract and list those items (their exact names as written in the Context) even if the user's keywords are loose, misspelled, or half the word (e.g. "pojects", "projcts", "project"). Never demand a perfect spelling match from the user. You MUST NOT use outside knowledge, general knowledge, or anything learned during training for any factual claim. Never guess or make anything up. If the Context is exactly "{NO_RELEVANT_CONTEXT_FOUND}", it means no relevant information was found in the knowledge base; in that case reply with EXACTLY this message and nothing else:
{FALLBACK_MESSAGE}
Do NOT attempt to answer the question and do NOT use general knowledge when the Context has no relevant information.

5. Be friendly, warm and conversational. Use emojis naturally to make the chat feel lively. 😊

6. Keep answers short and to the point (2-4 sentences max). When listing items, use bullet points or numbered lists for clarity.

7. LIST EXTRACTION RULE: When the user asks "list", "kitne", "saare", "sab", "how many", "kya kya", or any variation meaning "tell me all", extract EVERY item from the relevant section in the Context. Do not summarize or pick only a few. List them all with their names/titles.

Examples of correct behavior:
Q: "in se baat kaha pr kru?"
A: [Give the contact details exactly as found in the Context above — phone, email, address, website. Do NOT invent any details.]

Q: "tum se contact kaise karu?"
A: [Give the contact details exactly as found in the Context above — phone, email, address, website. Do NOT invent any details.]

Q: "aapki services kya hain?"
A: [Answer strictly from the Context. List only what is mentioned there.]

Q: "projects k naam btao"
A: [List ALL project names found in the Context, one by one.]"""  # noqa: E501


def get_context_for_agent(
    query: str,
    agent_id: int | None = None,
    top_k: int = 5,
    score_threshold: float = 0.3,
) -> str:
    """Return the best RAG context for a query, scoped to the correct agent.

    Search order:
      1. Agent-specific documents  (uploaded_files/agent_<id>/)
      2. Shared documents          (uploaded_files/)   — fallback / supplement

    This ensures Agent A never sees Agent B's knowledge base.

    The function is a thin DB-layer wrapper. The actual vector search is
    delegated to ``search_documents_for_agent`` (defined in the RAG/vector
    module). We import it lazily here so this file stays free of heavy deps.

    Falls back to NO_RELEVANT_CONTEXT_FOUND when nothing relevant is found.
    """
    try:
        from app.rag import search_documents_for_agent  # type: ignore
        results = search_documents_for_agent(
            query=query,
            agent_id=agent_id,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        if not results:
            return NO_RELEVANT_CONTEXT_FOUND
        return "\n\n".join(results)
    except ImportError:
        return NO_RELEVANT_CONTEXT_FOUND
    except Exception:
        return NO_RELEVANT_CONTEXT_FOUND


DEFAULT_AGENT_DESCRIPTION = (
    "N2X System ka official assistant - services, projects, pricing, "
    "portfolio aur contact details ke sawalon ke jawab deta hai."
)


def build_system_prompt(name: str, description: str = "") -> str:
    """Fill the universal template's two placeholders with the agent's short
    fields. This is the default prompt; only a per-agent custom override
    (Advanced System Prompt) replaces it."""
    desc = (description or "").strip()
    if desc:
        return (
            SYSTEM_PROMPT_TEMPLATE.replace("{agent_name}", name)
            .replace("{agent_description}", desc)
        )
    return SYSTEM_PROMPT_TEMPLATE.replace("{agent_name}", name).replace(
        " {agent_description}", ""
    )


DEFAULT_SYSTEM_PROMPT = build_system_prompt("N2X Assistant", DEFAULT_AGENT_DESCRIPTION)
DEFAULT_GREETING = "Hello! Main aapki kaise madad kar sakta hoon?"


def get_system_prompt_for_agent(agent: dict | None) -> str:
    if not agent:
        return DEFAULT_SYSTEM_PROMPT
    stored = (agent.get("system_prompt") or "").strip()
    if stored:
        return stored
    return build_system_prompt(
        agent.get("name") or "Assistant",
        agent.get("description") or "",
    )


def get_greeting_for_agent(agent: dict | None) -> str:
    if not agent:
        return DEFAULT_GREETING
    return (agent.get("greeting") or DEFAULT_GREETING).strip() or DEFAULT_GREETING


def seed_default_agent():
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM agents").fetchone()
        if row["c"] == 0:
            conn.execute(
                "INSERT INTO agents (name, description, system_prompt, greeting, slug) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    "N2X Assistant",
                    DEFAULT_AGENT_DESCRIPTION,
                    DEFAULT_SYSTEM_PROMPT,
                    DEFAULT_GREETING,
                    "n2x-assistant",
                ),
            )


def _default_agent_owner(conn: psycopg.Connection) -> int | None:
    """The admin agents are assigned to during migration. Prefer the original
    .env super admin, then any super admin, then the oldest admin."""
    row = conn.execute(
        "SELECT id FROM admin_users WHERE username = %s ORDER BY id LIMIT 1",
        (ADMIN_USERNAME,),
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM admin_users WHERE role = 'super_admin' ORDER BY id LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute("SELECT id FROM admin_users ORDER BY id LIMIT 1").fetchone()
    return row["id"] if row else None


def backfill_agent_owners():
    """Assign every agent without an owner to the original .env super admin."""
    with get_conn() as conn:
        owner_id = _default_agent_owner(conn)
        if owner_id is None:
            return
        conn.execute(
            "UPDATE agents SET owner_admin_id = %s WHERE owner_admin_id IS NULL",
            (owner_id,),
        )


# ---------------------------------------------------------------------------
# Admin users
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256 with a per-user random salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    )
    return digest.hex(), salt


def seed_default_admin():
    """Ensure at least one super admin exists."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()
        if row["c"] == 0:
            password_hash, salt = _hash_password(ADMIN_PASSWORD)
            conn.execute(
                "INSERT INTO admin_users (username, password_hash, salt, role) "
                "VALUES (%s, %s, %s, %s)",
                (ADMIN_USERNAME, password_hash, salt, "super_admin"),
            )
            return

        env_admin = conn.execute(
            "SELECT id FROM admin_users WHERE username = %s ORDER BY id LIMIT 1",
            (ADMIN_USERNAME,),
        ).fetchone()
        if env_admin:
            conn.execute(
                "UPDATE admin_users SET role = 'super_admin' WHERE id = %s",
                (env_admin["id"],),
            )
            return

        super_count = conn.execute(
            "SELECT COUNT(*) AS c FROM admin_users WHERE role = 'super_admin'"
        ).fetchone()["c"]
        if super_count == 0:
            first = conn.execute(
                "SELECT id FROM admin_users ORDER BY id LIMIT 1"
            ).fetchone()
            if first:
                conn.execute(
                    "UPDATE admin_users SET role = 'super_admin' WHERE id = %s",
                    (first["id"],),
                )


def create_admin_user(username: str, password: str, role: str = "admin") -> dict:
    password_hash, salt = _hash_password(password)
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO admin_users (username, password_hash, salt, role) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (username, password_hash, salt, role),
        ).fetchone()
        admin_id = row["id"]
    seed_plans()
    if get_current_subscription(admin_id) is None:
        free = get_plan_by_name("Free")
        if free is not None:
            create_subscription(admin_id, free["id"], "active")
    return get_admin_user(admin_id)


def get_admin_role(admin_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT role FROM admin_users WHERE id = %s",
            (admin_id,),
        ).fetchone()
    return row["role"] if row else None


def get_admin_user(admin_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, role, created_at FROM admin_users WHERE id = %s",
            (admin_id,),
        ).fetchone()
    return dict(row) if row else None


def get_admin_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, role, created_at FROM admin_users WHERE username = %s",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def verify_admin_user(username: str, password: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, salt FROM admin_users WHERE username = %s",
            (username,),
        ).fetchone()
    if not row:
        return None
    password_hash, _ = _hash_password(password, row["salt"])
    if not hmac.compare_digest(password_hash, row["password_hash"]):
        return None
    return {"id": row["id"], "username": row["username"]}


def list_admin_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM admin_users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_admin_user(admin_id: int) -> bool:
    """Delete an admin user. Refuses if it would remove the last admin or the
    last super_admin."""
    with get_conn() as conn:
        target = conn.execute(
            "SELECT role FROM admin_users WHERE id = %s", (admin_id,)
        ).fetchone()
        if not target:
            return False
        if conn.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()["c"] <= 1:
            return False
        if target["role"] == "super_admin":
            super_count = conn.execute(
                "SELECT COUNT(*) AS c FROM admin_users WHERE role = 'super_admin'"
            ).fetchone()["c"]
            if super_count <= 1:
                return False
        cur = conn.execute("DELETE FROM admin_users WHERE id = %s", (admin_id,))
        if cur.rowcount > 0:
            conn.execute(
                "DELETE FROM admin_sessions WHERE admin_user_id = %s", (admin_id,)
            )
        return cur.rowcount > 0


def change_admin_password(admin_id: int, new_password: str) -> bool:
    password_hash, salt = _hash_password(new_password)
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE admin_users SET password_hash = %s, salt = %s WHERE id = %s",
            (password_hash, salt, admin_id),
        )
    return cur.rowcount > 0


def save_message(
    session_id: str,
    role: str,
    content: str,
    was_fallback: int = 0,
    agent_id: int | None = None,
) -> int:
    """Insert a message and return its autoincrement id."""
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO messages (session_id, role, content, was_fallback, agent_id) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (session_id, role, content, was_fallback, agent_id),
        ).fetchone()
        return row["id"]


def get_session_messages(session_id: str, agent_id: int | None = None) -> list[dict]:
    query = """
        SELECT id, role, content, agent_id, created_at
        FROM messages
        WHERE session_id = %s
    """
    params: list = [session_id]
    if agent_id is not None:
        query += " AND agent_id = %s"
        params.append(agent_id)
    query += " ORDER BY id"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Human agent handoff
# ---------------------------------------------------------------------------

def create_or_update_handoff(
    session_id: str, question: str, agent_id: int | None = None
) -> None:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM handoffs WHERE session_id = %s AND status = 'pending'",
            (session_id,),
        ).fetchone()
        if existing:
            conn.execute(
                f"""
                UPDATE handoffs
                SET question = %s, agent_id = %s, created_at = {NOW_SQL}
                WHERE id = %s
                """,
                (question, agent_id, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO handoffs (session_id, agent_id, question) "
                "VALUES (%s, %s, %s)",
                (session_id, agent_id, question),
            )


def get_pending_handoffs(
    admin_id: int | None = None, role: str | None = None
) -> list[dict]:
    """Pending fallbacks, scoped by admin role."""
    query = """
            SELECT h.id, h.session_id, h.question, h.created_at,
                   a.name AS agent_name
            FROM handoffs h
            LEFT JOIN agents a ON a.id = h.agent_id
            WHERE h.status = 'pending'
        """
    params: list = []
    if admin_id is not None and role != "super_admin":
        query += (
            " AND (h.agent_id IS NULL OR h.agent_id IN "
            "(SELECT id FROM agents WHERE owner_admin_id = %s))"
        )
        params.append(admin_id)
    query += " ORDER BY h.id DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_handoff(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, session_id, agent_id, question, status, created_at
            FROM handoffs
            WHERE session_id = %s
            ORDER BY id DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def resolve_handoff(session_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            f"""
            UPDATE handoffs
            SET status = 'resolved', resolved_at = {NOW_SQL}
            WHERE session_id = %s AND status = 'pending'
            """,
            (session_id,),
        )
    return cur.rowcount > 0


def get_conversations() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.session_id, m.role, m.content, m.created_at,
                   m.agent_id, a.name AS agent_name,
                   au.username AS owner_username, au.id AS owner_admin_id
            FROM messages m
            LEFT JOIN agents a ON a.id = m.agent_id
            LEFT JOIN admin_users au ON au.id = a.owner_admin_id
            ORDER BY m.id
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversations_for_admin(admin_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.session_id, m.role, m.content, m.created_at,
                   m.agent_id, a.name AS agent_name
            FROM messages m
            INNER JOIN agents a ON a.id = m.agent_id
            WHERE a.owner_admin_id = %s
            ORDER BY m.id
            """,
            (admin_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversations_summary(
    admin_id: int | None = None, role: str | None = None
) -> list[dict]:
    if admin_id is not None and role != "super_admin":
        return _conversation_summaries_clause("WHERE a.owner_admin_id = %s", [admin_id])
    return _conversation_summaries_clause("", [])


def _conversation_summaries_clause(clause: str, params: list) -> list[dict]:
    query = f"""
        SELECT m.session_id,
               m.agent_id,
               a.name AS agent_name,
               au.username AS owner_username,
               COUNT(*) AS message_count,
               MIN(m.created_at) AS started_at,
               MAX(m.created_at) AS last_activity_at,
               (SELECT content FROM messages m2
                WHERE m2.session_id = m.session_id
                  AND m2.agent_id IS NOT DISTINCT FROM m.agent_id
                ORDER BY m2.id DESC LIMIT 1) AS last_message
        FROM messages m
        LEFT JOIN agents a ON a.id = m.agent_id
        LEFT JOIN admin_users au ON au.id = a.owner_admin_id
        {clause}
        GROUP BY m.session_id, m.agent_id, a.name, au.username
        ORDER BY last_activity_at DESC
    """
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

PERIODS = ("today", "week", "month", "all")


def _period_cutoff(period: str) -> str | None:
    """Return the earliest allowed created_at (formatted like the DB now
    expression) for a period, or None for 'all'. UTC-based, matching NOW_SQL."""
    now = datetime.utcnow()
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        return None
    return start.strftime("%Y-%m-%d %H:%M:%S")


def _period_condition(period: str) -> tuple[str, list]:
    cutoff = _period_cutoff(period)
    if cutoff is None:
        return "", []
    return "WHERE created_at >= %s", [cutoff]


def get_total_conversations(period: str = "all") -> int:
    where, params = _period_condition(period)
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT COUNT(DISTINCT session_id) AS c FROM messages {where}",
            params,
        ).fetchone()
    return row["c"] if row else 0


def get_total_messages(period: str = "all") -> int:
    where, params = _period_condition(period)
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM messages {where}",
            params,
        ).fetchone()
    return row["c"] if row else 0


def get_fallback_rate(period: str = "all") -> float:
    where, params = _period_condition(period)
    where_clause = "WHERE role = 'assistant'"
    if where:
        where_clause += " AND created_at >= %s"
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN was_fallback = 1 THEN 1 ELSE 0 END) AS fallbacks
            FROM messages
            {where_clause}
            """,
            params,
        ).fetchone()
    total = row["total"] if row else 0
    fallbacks = row["fallbacks"] if row and row["fallbacks"] is not None else 0
    if not total:
        return 0.0
    return round(fallbacks / total * 100, 2)


def get_avg_messages_per_conversation(period: str = "all") -> float:
    total_messages = get_total_messages(period)
    total_conversations = get_total_conversations(period)
    if not total_conversations:
        return 0.0
    return round(total_messages / total_conversations, 2)


def get_top_questions(limit: int = 5) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT content FROM messages WHERE role = 'user'"
        ).fetchall()
    counts: Counter = Counter()
    for row in rows:
        normalized = _normalize_question(row["content"])
        if normalized:
            counts[normalized] += 1
    return [
        {"question": question, "count": count}
        for question, count in counts.most_common(limit)
    ]


def _normalize_question(text: str) -> str:
    lower = text.lower().strip()
    return re.sub(r"[^a-z0-9\s]", "", lower).strip()


def get_conversations_per_day(last_n_days: int = 7) -> list[dict]:
    start = (datetime.utcnow() - timedelta(days=last_n_days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_str = start.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT LEFT(created_at, 10) AS day, COUNT(DISTINCT session_id) AS c
            FROM messages
            WHERE created_at >= %s
            GROUP BY LEFT(created_at, 10)
            """,
            [start_str],
        ).fetchall()
    by_day = {r["day"]: r["c"] for r in rows}

    result = []
    for i in range(last_n_days):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        result.append({"date": day, "count": by_day.get(day, 0)})
    return result


def get_admin_activity_overview() -> list[dict]:
    """Per-admin activity summary for the Super Admin dashboard."""
    admins = list_admin_users()
    result = []
    with get_conn() as conn:
        for a in admins:
            admin_id = a["id"]

            agents_row = conn.execute(
                "SELECT COUNT(*) AS c FROM agents WHERE owner_admin_id = %s",
                (admin_id,),
            ).fetchone()
            agent_count = agents_row["c"] if agents_row else 0

            conv_row = conn.execute(
                """
                SELECT COUNT(DISTINCT m.session_id) AS c
                FROM messages m
                INNER JOIN agents ag ON ag.id = m.agent_id
                WHERE ag.owner_admin_id = %s
                """,
                (admin_id,),
            ).fetchone()
            conv_count = conv_row["c"] if conv_row else 0

            msg_row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM messages m
                INNER JOIN agents ag ON ag.id = m.agent_id
                WHERE ag.owner_admin_id = %s
                """,
                (admin_id,),
            ).fetchone()
            msg_count = msg_row["c"] if msg_row else 0

            ho_row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM handoffs h
                INNER JOIN agents ag ON ag.id = h.agent_id
                WHERE ag.owner_admin_id = %s AND h.status = 'pending'
                """,
                (admin_id,),
            ).fetchone()
            handoff_count = ho_row["c"] if ho_row else 0

            last_row = conn.execute(
                """
                SELECT MAX(m.created_at) AS last_active
                FROM messages m
                INNER JOIN agents ag ON ag.id = m.agent_id
                WHERE ag.owner_admin_id = %s
                """,
                (admin_id,),
            ).fetchone()
            last_active = last_row["last_active"] if last_row else None

            doc_count = 0
            for agent_id_row in conn.execute(
                "SELECT id FROM agents WHERE owner_admin_id = %s", (admin_id,)
            ).fetchall():
                agent_dir = _get_agent_uploaded_files_dir(agent_id_row["id"])
                if os.path.isdir(agent_dir):
                    doc_count += len([
                        f for f in os.listdir(agent_dir)
                        if os.path.isfile(os.path.join(agent_dir, f))
                        and f.lower().endswith((".pdf", ".txt"))
                    ])

            result.append({
                "admin_id": admin_id,
                "username": a["username"],
                "role": a["role"],
                "created_at": a["created_at"],
                "agent_count": agent_count,
                "conversation_count": conv_count,
                "message_count": msg_count,
                "pending_handoffs": handoff_count,
                "document_count": doc_count,
                "last_active": last_active,
            })
    return result


def _hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def backfill_api_key_hashes():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, api_key FROM api_keys WHERE api_key_hash IS NULL"
        ).fetchall()
        for row in rows:
            if row["api_key"]:
                conn.execute(
                    "UPDATE api_keys SET api_key_hash = %s WHERE id = %s",
                    (_hash_api_key(row["api_key"]), row["id"]),
                )


def scrub_plaintext_api_keys():
    """Replace legacy raw keys with a non-secret marker. Keys keep working via
    api_key_hash. Idempotent."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE api_keys SET api_key = 'sha256:' || api_key_hash "
            "WHERE api_key_hash IS NOT NULL AND api_key NOT LIKE 'sha256:%'"
        )


def backfill_message_agent_ids():
    """Attach legacy NULL-agent messages to the session's most recent agent."""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE messages
            SET agent_id = (
                SELECT m2.agent_id FROM messages m2
                WHERE m2.session_id = messages.session_id
                  AND m2.agent_id IS NOT NULL
                ORDER BY m2.id DESC LIMIT 1
            )
            WHERE agent_id IS NULL
              AND EXISTS (
                SELECT 1 FROM messages m3
                WHERE m3.session_id = messages.session_id
                  AND m3.agent_id IS NOT NULL
              )
            """
        )


def create_api_key(
    label: str, admin_id: int | None = None, agent_id: int | None = None
) -> str:
    api_key = "n2x_" + secrets.token_hex(24)
    key_hash = _hash_api_key(api_key)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO api_keys (api_key, api_key_hash, label, admin_id, agent_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("sha256:" + key_hash, key_hash, label, admin_id, agent_id),
        )
    return api_key


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return key
    return key[:6] + "…" + key[-4:]


def list_api_keys(
    admin_id: int | None = None,
    role: str | None = None,
    agent_id: int | None = None,
) -> list[dict]:
    query = """
        SELECT k.id, k.label, k.admin_id, k.agent_id, k.is_active,
               k.last_used_at, k.created_at,
               a.name AS agent_name
        FROM api_keys k
        LEFT JOIN agents a ON a.id = k.agent_id
    """
    params: list = []
    clauses: list[str] = []
    if admin_id is not None and role != "super_admin":
        clauses.append("k.admin_id = %s")
        params.append(admin_id)
    if agent_id is not None:
        if role == "super_admin":
            clauses.append("k.agent_id = %s")
            params.append(agent_id)
        else:
            clauses.append("k.agent_id = %s AND k.admin_id = %s")
            params += [agent_id, admin_id]
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY k.id DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["api_key"] = _mask_key("")
        result.append(item)
    return result


def delete_api_key(
    key_id: int, admin_id: int | None = None, role: str | None = None
) -> bool:
    params: list = [key_id]
    scope = ""
    if admin_id is not None and role != "super_admin":
        scope = " AND admin_id = %s"
        params.append(admin_id)
    with get_conn() as conn:
        cur = conn.execute(f"DELETE FROM api_keys WHERE id = %s{scope}", params)
    return cur.rowcount > 0


def resolve_api_key(raw_key: str, want_agent_id: int | None = None) -> dict | None:
    if not raw_key:
        return None
    hashed = _hash_api_key(raw_key)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE api_key_hash = %s", (hashed,)
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE api_key = %s AND api_key_hash IS NULL",
                (raw_key,),
            ).fetchone()
    if not row or not row["is_active"]:
        return None
    key = dict(row)
    if want_agent_id is not None and key.get("agent_id") != want_agent_id:
        return None
    with get_conn() as conn:
        conn.execute(
            f"UPDATE api_keys SET last_used_at = {NOW_SQL} WHERE id = %s",
            (key["id"],),
        )
    return key


def create_admin_session(token: str, admin_user_id: int | None = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO admin_sessions (token, admin_user_id) VALUES (%s, %s)",
            (token, admin_user_id),
        )


def admin_session_exists(token: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM admin_sessions WHERE token = %s",
            (token,),
        ).fetchone()
    return row is not None


def get_session_admin_id(token: str) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT admin_user_id FROM admin_sessions WHERE token = %s",
            (token,),
        ).fetchone()
    return row["admin_user_id"] if row else None


def delete_admin_session(token: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM admin_sessions WHERE token = %s", (token,))
    return cur.rowcount > 0


def get_agent_by_slug(slug: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT a.*, au.username AS owner_username
            FROM agents a
            LEFT JOIN admin_users au ON au.id = a.owner_admin_id
            WHERE a.slug = %s
            """,
            (slug,),
        ).fetchone()
    return _mark_custom_prompt(dict(row)) if row else None


def get_agent_for_request(
    slug: str | None = None,
    api_key: str | None = None,
    agent_id: int | None = None,
) -> dict | None:
    if agent_id is not None:
        return get_agent(agent_id)
    if slug:
        return get_agent_by_slug(slug)
    if api_key:
        key_row = resolve_api_key(api_key)
        if key_row and key_row.get("agent_id"):
            return get_agent(key_row["agent_id"])
    return None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return slug or "agent"


def _unique_slug(
    conn: psycopg.Connection,
    base: str = "",
    exclude_agent_id: int | None = None,
) -> str:
    candidate = _slugify(base)
    n = 2
    while True:
        if exclude_agent_id is not None:
            row = conn.execute(
                "SELECT 1 FROM agents WHERE slug = %s AND id != %s",
                (candidate, exclude_agent_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM agents WHERE slug = %s",
                (candidate,),
            ).fetchone()
        if not row:
            return candidate
        candidate = f"{_slugify(base)}-{n}"
        n += 1


def backfill_agent_slugs():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name FROM agents WHERE slug IS NULL OR slug = '' ORDER BY id"
        ).fetchall()
        for row in rows:
            slug = _unique_slug(conn, row["name"], exclude_agent_id=row["id"])
            conn.execute(
                "UPDATE agents SET slug = %s WHERE id = %s", (slug, row["id"])
            )


def _extract_agent_description(legacy_prompt: str, name: str) -> str:
    legacy = (legacy_prompt or "").strip()
    if "N2X System's friendly chat assistant" in legacy:
        return DEFAULT_AGENT_DESCRIPTION
    match = re.search(r"You are (?:the |a |an )?([^.\n]{8,250})\.?", legacy)
    if match:
        return match.group(1).replace("*", "").strip()
    return f"{name} - Aapke sawalon ke jawab dene ke liye."


def backfill_agent_descriptions():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, system_prompt FROM agents "
            "WHERE description IS NULL OR description = ''"
        ).fetchall()
        for row in rows:
            description = _extract_agent_description(row["system_prompt"], row["name"])
            conn.execute(
                "UPDATE agents SET description = %s WHERE id = %s",
                (description, row["id"]),
            )


def _resolve_system_prompt(name: str, description: str, custom: str = "") -> str:
    custom_prompt = (custom or "").strip()
    if custom_prompt:
        return custom_prompt
    return build_system_prompt(name, description)


def create_agent(
    name: str,
    description: str = "",
    greeting: str = "",
    owner_admin_id: int | None = None,
    slug: str | None = None,
    system_prompt: str = "",
    primary_color: str = "#2563EB",
) -> dict:
    with get_conn() as conn:
        final_slug = _unique_slug(conn, slug or name)
        row = conn.execute(
            "INSERT INTO agents "
            "(name, description, system_prompt, greeting, owner_admin_id, slug, primary_color) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                name,
                description,
                _resolve_system_prompt(name, description, system_prompt),
                greeting,
                owner_admin_id,
                final_slug,
                primary_color or "#2563EB",
            ),
        ).fetchone()
        agent_id = row["id"]
    return get_agent(agent_id)


def _mark_custom_prompt(agent: dict) -> dict:
    stored = (agent.get("system_prompt") or "").strip()
    expected = build_system_prompt(
        agent.get("name") or "", agent.get("description") or ""
    )
    agent["has_custom_prompt"] = bool(stored) and stored != expected
    return agent


def get_agent(
    agent_id: int,
    admin_id: int | None = None,
    role: str | None = None,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT a.*, au.username AS owner_username
            FROM agents a
            LEFT JOIN admin_users au ON au.id = a.owner_admin_id
            WHERE a.id = %s
            """,
            (agent_id,),
        ).fetchone()
    if not row:
        return None
    agent = dict(row)
    if admin_id is not None and role != "super_admin":
        if agent.get("owner_admin_id") != admin_id:
            return None
    return _mark_custom_prompt(agent)


def list_agents(admin_id: int | None = None) -> list[dict]:
    query = """
        SELECT a.id, a.name, a.description, a.system_prompt, a.greeting, a.slug,
               a.created_at, a.owner_admin_id, a.primary_color,
               au.username AS owner_username
        FROM agents a
        LEFT JOIN admin_users au ON au.id = a.owner_admin_id
    """
    params: list = []
    if admin_id is not None:
        query += " WHERE a.owner_admin_id = %s"
        params.append(admin_id)
    query += " ORDER BY a.id"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_mark_custom_prompt(dict(r)) for r in rows]


def update_agent(
    agent_id: int,
    name: str,
    description: str = "",
    greeting: str = "",
    admin_id: int | None = None,
    role: str | None = None,
    slug: str | None = None,
    system_prompt: str = "",
    primary_color: str | None = None,
) -> bool:
    with get_conn() as conn:
        final_slug = _unique_slug(conn, slug or name, exclude_agent_id=agent_id)
        params: list = [
            name,
            description,
            _resolve_system_prompt(name, description, system_prompt),
            greeting,
            final_slug,
        ]
        color_sql = ""
        if primary_color is not None:
            color_sql = ", primary_color = %s"
            params.append(primary_color)
        params.append(agent_id)
        scope = ""
        if admin_id is not None and role != "super_admin":
            scope = " AND owner_admin_id = %s"
            params.append(admin_id)
        cur = conn.execute(
            "UPDATE agents SET name = %s, description = %s, system_prompt = %s, "
            "greeting = %s, slug = %s{color_sql} WHERE id = %s{scope}".format(
                color_sql=color_sql, scope=scope
            ),
            params,
        )
    return cur.rowcount > 0


def delete_agent(
    agent_id: int,
    admin_id: int | None = None,
    role: str | None = None,
) -> bool:
    params: list = [agent_id]
    scope = ""
    if admin_id is not None and role != "super_admin":
        scope = " AND owner_admin_id = %s"
        params.append(admin_id)
    with get_conn() as conn:
        cur = conn.execute(f"DELETE FROM agents WHERE id = %s{scope}", params)
        if cur.rowcount > 0:
            conn.execute("DELETE FROM documents WHERE agent_id = %s", (agent_id,))
            conn.execute("DELETE FROM api_keys WHERE agent_id = %s", (agent_id,))
            conn.execute(
                f"UPDATE handoffs SET status = 'resolved', resolved_at = {NOW_SQL} "
                "WHERE agent_id = %s AND status = 'pending'",
                (agent_id,),
            )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

DOCUMENT_STATUSES = ("pending", "processing", "ready", "failed")


def create_document(
    agent_id: int | None,
    owner_admin_id: int | None,
    filename: str,
    original_filename: str,
    file_path: str | None = None,
    file_size: int = 0,
) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO documents
                (agent_id, owner_admin_id, filename, original_filename,
                 file_path, file_size, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'processing')
            RETURNING id
            """,
            (agent_id, owner_admin_id, filename, original_filename, file_path, file_size),
        ).fetchone()
        return row["id"]


def update_document_status(
    document_id: int,
    status: str,
    chunks_count: int | None = None,
    error_message: str | None = None,
) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            f"""
            UPDATE documents
            SET status = %s,
                chunks_count = COALESCE(%s, chunks_count),
                error_message = %s,
                updated_at = {NOW_SQL}
            WHERE id = %s
            """,
            (status, chunks_count, error_message, document_id),
        )
    return cur.rowcount > 0


def set_document_file_size(document_id: int, file_size: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE documents SET file_size = %s, updated_at = {NOW_SQL} WHERE id = %s",
            (file_size, document_id),
        )
    return cur.rowcount > 0


def get_document(
    document_id: int,
    admin_id: int | None = None,
    role: str | None = None,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
    if not row:
        return None
    doc = dict(row)
    if admin_id is not None and role != "super_admin" and doc.get("owner_admin_id") != admin_id:
        return None
    return doc


def list_documents(
    scope: str = "shared",
    agent_id: int | None = None,
    admin_id: int | None = None,
    role: str | None = None,
) -> list[dict]:
    if scope == "agent" and agent_id is None:
        return []
    if scope == "agent":
        where = "WHERE agent_id = %s"
        params: list = [agent_id]
        if admin_id is not None and role != "super_admin":
            where += " AND agent_id IN (SELECT id FROM agents WHERE owner_admin_id = %s)"
            params.append(admin_id)
        query = "SELECT * FROM documents {where} ORDER BY id".format(where=where)
    else:
        where = "WHERE agent_id IS NULL"
        params = []
        if admin_id is not None and role != "super_admin":
            where += " AND owner_admin_id = %s"
            params.append(admin_id)
        query = "SELECT * FROM documents {where} ORDER BY id".format(where=where)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def count_documents_for_admin(
    admin_id: int,
    statuses: tuple[str, ...] = ("processing", "ready"),
) -> int:
    if not statuses:
        return 0
    placeholders = ",".join("%s" for _ in statuses)
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS c FROM documents
            WHERE owner_admin_id = %s AND status IN ({placeholders})
            """,
            (admin_id, *statuses),
        ).fetchone()
    return row["c"] if row else 0


def delete_document_record_by_scope(agent_id: int | None, filename: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM documents "
            "WHERE agent_id IS NOT DISTINCT FROM %s AND filename = %s",
            (agent_id, filename),
        )
    return cur.rowcount > 0


def backfill_documents():
    """Create a documents row for every file already on disk with no record.

    Postgres enforces foreign keys, unlike SQLite. Stale upload folders for a
    deleted agent (or with a deleted owner admin) would abort the entire
    startup transaction, so orphaned folders are skipped with a warning
    instead of failing the whole migration.
    """
    import os as _os

    def _exists(conn, agent_id, filename):
        row = conn.execute(
            "SELECT 1 FROM documents "
            "WHERE agent_id IS NOT DISTINCT FROM %s AND filename = %s LIMIT 1",
            (agent_id, filename),
        ).fetchone()
        return row is not None

    base = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "uploaded_files")
    _os.makedirs(base, exist_ok=True)
    with get_conn() as conn:
        # Shared scope (agent_id IS NULL) — no FK to check.
        for name in _os.listdir(base):
            full = _os.path.join(base, name)
            if _os.path.isfile(full):
                if not _exists(conn, None, name):
                    conn.execute(
                        """
                        INSERT INTO documents
                            (agent_id, owner_admin_id, filename, original_filename,
                             file_path, file_size, status, chunks_count)
                        VALUES (NULL, NULL, %s, %s, %s, %s, 'ready', 0)
                        """,
                        (name, name, name, _os.path.getsize(full)),
                    )

        # Agent-scoped folders: skip orphans whose agent row is gone.
        agent_dir_prefix = "agent_"
        for entry in _os.listdir(base):
            full = _os.path.join(base, entry)
            if not (_os.path.isdir(full) and entry.startswith(agent_dir_prefix)):
                continue
            try:
                agent_id = int(entry.split("_", 1)[1])
            except ValueError:
                continue

            agent_row = conn.execute(
                "SELECT id, owner_admin_id FROM agents WHERE id = %s", (agent_id,)
            ).fetchone()
            if not agent_row:
                logger.warning(
                    "backfill_documents: skipping orphaned folder %s "
                    "(agent id %d no longer exists in agents table)",
                    entry, agent_id,
                )
                continue

            owner_id = agent_row["owner_admin_id"]
            # Validate owner_admin_id too — the admin may have been deleted.
            if owner_id is not None:
                owner_ok = conn.execute(
                    "SELECT 1 FROM admin_users WHERE id = %s", (owner_id,)
                ).fetchone()
                if not owner_ok:
                    logger.warning(
                        "backfill_documents: agent %d points to missing admin %d; "
                        "storing documents with owner_admin_id=NULL",
                        agent_id, owner_id,
                    )
                    owner_id = None

            for fname in _os.listdir(full):
                fpath = _os.path.join(full, fname)
                if _os.path.isfile(fpath) and not _exists(conn, agent_id, fname):
                    conn.execute(
                        """
                        INSERT INTO documents
                            (agent_id, owner_admin_id, filename, original_filename,
                             file_path, file_size, status, chunks_count)
                        VALUES (%s, %s, %s, %s, %s, %s, 'ready', 0)
                        """,
                        (agent_id, owner_id, fname, fname,
                         _os.path.join(entry, fname), _os.path.getsize(fpath)),
                    )


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def _seed_plan(conn: psycopg.Connection, spec: dict) -> None:
    row = conn.execute(
        "SELECT 1 FROM plans WHERE name = %s", (spec["name"],)
    ).fetchone()
    if not row:
        conn.execute(
            """
            INSERT INTO plans
                (name, price, currency, billing_interval, max_agents,
                 max_documents, unlimited_documents, max_messages_per_period,
                 unlimited_messages, is_active,
                 max_support_agents, unlimited_ai_agents, unlimited_support_agents)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                spec["name"],
                spec["price"],
                spec["currency"],
                spec["billing_interval"],
                spec["max_agents"],
                spec["max_documents"],
                1 if spec.get("max_documents") is None else 0,
                spec["max_messages_per_period"],
                1 if spec.get("max_messages_per_period") is None else 0,
                spec["is_active"],
                spec.get("max_support_agents"),
                1 if spec.get("unlimited_ai_agents") else 0,
                1 if spec.get("unlimited_support_agents") else 0,
            ),
        )
        return

    conn.execute(
        """
        UPDATE plans
        SET max_support_agents = COALESCE(max_support_agents, %s),
            unlimited_ai_agents = COALESCE(unlimited_ai_agents, %s),
            unlimited_support_agents = COALESCE(unlimited_support_agents, %s),
            unlimited_documents = COALESCE(unlimited_documents,
                CASE WHEN max_documents IS NULL THEN 1 ELSE 0 END),
            unlimited_messages = COALESCE(unlimited_messages,
                CASE WHEN max_messages_per_period IS NULL THEN 1 ELSE 0 END)
        WHERE name = %s
        """,
        (
            spec.get("max_support_agents"),
            1 if spec.get("unlimited_ai_agents") else 0,
            1 if spec.get("unlimited_support_agents") else 0,
            spec["name"],
        ),
    )


def seed_plans():
    """Seed the 4 default plans: Free / Monthly / Yearly / Lifetime."""
    default_plans = [
        {
            "name": "Free",
            "price": 0.0,
            "currency": "PKR",
            "billing_interval": "monthly",
            "max_agents": 1,
            "max_support_agents": 1,
            "unlimited_ai_agents": False,
            "unlimited_support_agents": False,
            "max_documents": 10,
            "max_messages_per_period": 1000,
            "is_active": 1,
        },
        {
            "name": "Monthly",
            "price": 3000.0,
            "currency": "PKR",
            "billing_interval": "monthly",
            "max_agents": 3,
            "max_support_agents": 5,
            "unlimited_ai_agents": False,
            "unlimited_support_agents": False,
            "max_documents": 50,
            "max_messages_per_period": 10000,
            "is_active": 1,
        },
        {
            "name": "Yearly",
            "price": 300000.0,
            "currency": "PKR",
            "billing_interval": "yearly",
            "max_agents": 10,
            "max_support_agents": 20,
            "unlimited_ai_agents": False,
            "unlimited_support_agents": False,
            "max_documents": 200,
            "max_messages_per_period": 120000,
            "is_active": 1,
        },
        {
            "name": "Lifetime",
            "price": 79999.0,
            "currency": "PKR",
            "billing_interval": "lifetime",
            "max_agents": None,
            "max_support_agents": None,
            "unlimited_ai_agents": True,
            "unlimited_support_agents": True,
            "max_documents": None,
            "max_messages_per_period": None,
            "is_active": 1,
        },
    ]
    with get_conn() as conn:
        for spec in default_plans:
            _seed_plan(conn, spec)


def rename_plan():
    """Deactivate legacy sample plans (Basic/Pro)."""
    with get_conn() as conn:
        for old in ("Basic", "Pro"):
            conn.execute(
                "UPDATE plans SET is_active = 0 WHERE name = %s AND is_active = 1",
                (old,),
            )


def get_plan(plan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE id = %s", (plan_id,)
        ).fetchone()
    return _normalize_plan(dict(row)) if row else None


def get_plan_by_name(name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE name = %s", (name,)
        ).fetchone()
    return _normalize_plan(dict(row)) if row else None


def _normalize_plan(plan: dict) -> dict:
    plan.setdefault("max_support_agents", plan.get("max_support_agents"))
    plan.setdefault("unlimited_ai_agents", int(plan.get("max_agents") is None))
    plan.setdefault(
        "unlimited_support_agents", int(plan.get("max_support_agents") is None)
    )
    plan.setdefault("unlimited_documents", int(plan.get("max_documents") is None))
    plan.setdefault(
        "unlimited_messages", int(plan.get("max_messages_per_period") is None)
    )
    plan["max_ai_agents"] = plan.get("max_agents")
    return plan


def list_plans(only_active: bool = True) -> list[dict]:
    query = "SELECT * FROM plans"
    params: list = []
    if only_active:
        query += " WHERE is_active = 1"
    query += " ORDER BY id"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_normalize_plan(dict(r)) for r in rows]


def list_all_plans() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM plans ORDER BY id").fetchall()
    return [_normalize_plan(dict(r)) for r in rows]


def update_plan(plan_id: int, fields: dict) -> bool:
    allowed = {
        "name", "price", "max_agents", "max_support_agents",
        "unlimited_ai_agents", "unlimited_support_agents", "is_active",
        "max_documents", "max_messages_per_period",
        "unlimited_documents", "unlimited_messages",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    setting: list[str] = []
    params: list = []
    for key, value in updates.items():
        if key in (
            "unlimited_ai_agents", "unlimited_support_agents",
            "unlimited_documents", "unlimited_messages",
        ):
            value = 1 if value else 0
        elif key in (
            "max_agents", "max_support_agents", "max_documents",
            "max_messages_per_period",
        ):
            value = None if value is None else int(value)
        setting.append(f"{key} = %s")
        params.append(value)
    setting.append(f"updated_at = {NOW_SQL}")
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE plans SET {', '.join(setting)} WHERE id = %s",
            [*params, plan_id],
        )
    return cur.rowcount > 0


def get_plan_by_id(plan_id: int) -> dict | None:
    return get_plan(plan_id)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

def create_subscription(
    admin_id: int,
    plan_id: int,
    status: str = "pending",
    current_period_start: str | None = None,
    current_period_end: str | None = None,
) -> int:
    """Insert a subscription. Pass SQL_NOW / SQL_PLUS_30 / SQL_PLUS_1Y /
    SQL_PLUS_1000Y as start/end to use DB-side now expressions, or pass a
    literal "YYYY-MM-DD HH:MM:SS" string to store it verbatim."""
    if current_period_start is None:
        current_period_start = SQL_NOW
    if current_period_end is None:
        current_period_end = SQL_PLUS_30
    sql_start = _SQL_EXPR.get(current_period_start, "%s")
    sql_end = _SQL_EXPR.get(current_period_end, "%s")
    params: list = [admin_id, plan_id, status]
    if sql_start == "%s":
        params.append(current_period_start)
    if sql_end == "%s":
        params.append(current_period_end)
    with get_conn() as conn:
        row = conn.execute(
            f"""
            INSERT INTO subscriptions
                (admin_id, plan_id, status, current_period_start, current_period_end)
            VALUES (%s, %s, %s, {sql_start}, {sql_end})
            RETURNING id
            """,
            params,
        ).fetchone()
        return row["id"]


def get_current_subscription(admin_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE admin_id = %s
            ORDER BY
                CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                id DESC
            LIMIT 1
            """,
            (admin_id,),
        ).fetchone()
    return dict(row) if row else None


def list_subscriptions(admin_id: int | None = None) -> list[dict]:
    query = "SELECT * FROM subscriptions"
    params: list = []
    if admin_id is not None:
        query += " WHERE admin_id = %s"
        params.append(admin_id)
    query += " ORDER BY id DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def set_subscription_status(subscription_id: int, status: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE subscriptions SET status = %s, updated_at = {NOW_SQL} WHERE id = %s",
            (status, subscription_id),
        )
    return cur.rowcount > 0


def backfill_subscriptions():
    """Give every existing admin an active Free-plan subscription if none."""
    free = get_plan_by_name("Free")
    if free is None:
        return
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM admin_users").fetchall()
        for r in rows:
            has = conn.execute(
                "SELECT 1 FROM subscriptions WHERE admin_id = %s LIMIT 1", (r["id"],)
            ).fetchone()
            if not has:
                conn.execute(
                    f"""
                    INSERT INTO subscriptions
                        (admin_id, plan_id, status, current_period_start, current_period_end)
                    VALUES (%s, %s, 'active', {NOW_SQL}, {PLUS_30_DAYS_SQL})
                    """,
                    (r["id"], free["id"]),
                )


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

PAYMENT_STATUSES = ("pending", "success", "failed", "cancelled")
PAYMENT_PROVIDERS = ("easypaisa", "jazzcash", "manual")


def create_payment(
    admin_id: int,
    subscription_id: int,
    provider: str,
    amount: float,
    currency: str = "PKR",
    transaction_id: str | None = None,
    provider_reference: str | None = None,
    provider_response: str | None = None,
) -> dict:
    """Create a payment record. Always starts as 'pending'."""
    record = {
        "admin_id": admin_id,
        "subscription_id": subscription_id,
        "provider": provider,
        "transaction_id": transaction_id,
        "amount": amount,
        "currency": currency,
        "provider_reference": provider_reference,
    }
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO payments
                (admin_id, subscription_id, provider, transaction_id,
                 amount, currency, status, provider_reference, provider_response)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s)
            RETURNING id
            """,
            (
                record["admin_id"],
                record["subscription_id"],
                record["provider"],
                record["transaction_id"],
                record["amount"],
                record["currency"],
                record["provider_reference"],
                provider_response,
            ),
        ).fetchone()
        record["id"] = row["id"]
    return record


def get_payment(
    payment_id: int,
    admin_id: int | None = None,
    role: str | None = None,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE id = %s", (payment_id,)
        ).fetchone()
    if not row:
        return None
    payment = dict(row)
    if admin_id is not None and role != "super_admin" and payment.get("admin_id") != admin_id:
        return None
    return payment


def list_payments(admin_id: int | None = None) -> list[dict]:
    query = "SELECT * FROM payments"
    params: list = []
    if admin_id is not None:
        query += " WHERE admin_id = %s"
        params.append(admin_id)
    query += " ORDER BY id DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def set_payment_status(payment_id: int, status: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE payments SET status = %s, updated_at = {NOW_SQL} WHERE id = %s",
            (status, payment_id),
        )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Usage tracking (foundation; not yet wired into the chat hot-path)
# ---------------------------------------------------------------------------

def get_usage_record(
    admin_id: int, period_start: str, period_end: str
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM usage_records
            WHERE admin_id = %s AND period_start = %s AND period_end = %s
            LIMIT 1
            """,
            (admin_id, period_start, period_end),
        ).fetchone()
    return dict(row) if row else None


def increment_usage(
    admin_id: int, period_start: str, period_end: str, amount: int = 1
) -> None:
    row = get_usage_record(admin_id, period_start, period_end)
    with get_conn() as conn:
        if row:
            conn.execute(
                f"UPDATE usage_records SET message_count = message_count + %s, "
                f"updated_at = {NOW_SQL} WHERE id = %s",
                (amount, row["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO usage_records
                    (admin_id, period_start, period_end, message_count)
                VALUES (%s, %s, %s, %s)
                """,
                (admin_id, period_start, period_end, amount),
            )


def get_usage_for_period(admin_id: int, period_start: str, period_end: str) -> int:
    row = get_usage_record(admin_id, period_start, period_end)
    return row["message_count"] if row else 0