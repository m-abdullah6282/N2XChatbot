import os
import sqlite3
import uuid

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chatbot.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


def save_message(session_id: str, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )


def get_conversations() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, created_at
            FROM messages
            ORDER BY id
            """
        ).fetchall()
    return [dict(r) for r in rows]


def create_api_key(label: str) -> str:
    api_key = "n2x_" + uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO api_keys (api_key, label) VALUES (?, ?)",
            (api_key, label),
        )
    return api_key


def list_api_keys() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, api_key, label, created_at
            FROM api_keys
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def delete_api_key(key_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    return cur.rowcount > 0


def create_admin_session(token: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO admin_sessions (token) VALUES (?)",
            (token,),
        )


def admin_session_exists(token: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM admin_sessions WHERE token = ?",
            (token,),
        ).fetchone()
    return row is not None


def delete_admin_session(token: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
    return cur.rowcount > 0
