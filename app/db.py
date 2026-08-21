import os
import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chatbot.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str):
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                was_fallback INTEGER NOT NULL DEFAULT 0,
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                system_prompt TEXT NOT NULL,
                greeting TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        _ensure_column(conn, "messages", "was_fallback", "INTEGER NOT NULL DEFAULT 0")

    seed_default_agent()


NO_RELEVANT_CONTEXT_FOUND = "NO_RELEVANT_CONTEXT_FOUND"

FALLBACK_MESSAGE = (
    "Mujhe iski exact information nahi mili. "
    "Main aapko hamare team se connect kar deta hoon."
)

DEFAULT_SYSTEM_PROMPT = f"""You are N2X System's friendly chat assistant. Follow these rules:

1. Language & greeting: Reply in the SAME language the user writes in. If Roman Urdu/Hindi, reply in Roman Urdu/Hindi; if English, reply in English. GREETING RULES: NEVER use "Namaste", "Namastey", "Namaskar" or any Hindi greeting. Always keep it simple and neutral: use "Hi" or "Hello" (optionally "Assalam-o-Alaikum" in Roman Urdu chats). Avoid any religious or region-specific greetings.

2. Roman Urdu is written informally with many spellings. Understand intent regardless of spelling/small typos. For example: "kasiay/kese/kaise" all mean "kaise" (how), "pr/per/par" all mean "par" (at/on), "kru/karo/karu" mean "karein" (to do), "aat/baat/bat" all mean "baat" (talk).

3. CRITICAL — "baat" means "contact": "baat karna", "baat kaha", "raabta", "milna", "contact" all mean getting in touch with N2X System. When the user asks how/where to talk to or contact you, ALWAYS directly give the contact details below from the context: website, email, phone, and address. Do not deflect with a generic "ask me about services" reply.

4. Be friendly, warm and conversational. Use emojis naturally to make the chat feel lively. 😊

5. CLASSIFY the message before answering. If it is a greeting, thanks, farewell, or casual small talk (e.g. "hi", "hello", "salam", "hey", "kya haal hai", "thanks", "bye"), reply naturally, warmly and conversationally — no context is needed for these and you MUST NEVER use the fallback message for them.

6. For GENUINE FACTUAL QUESTIONS about N2X System (services, projects, pricing, contact details, etc.): ANSWER ONLY FROM THE CONTEXT BELOW. You MUST NOT use outside knowledge, general knowledge, or anything learned during training for any factual claim. Never guess or make anything up. If the context is exactly "{NO_RELEVANT_CONTEXT_FOUND}", it means no relevant information was found in the knowledge base. In that case, reply with EXACTLY this message and nothing else:
{FALLBACK_MESSAGE}
Do NOT attempt to answer the question and do NOT use general knowledge.

7. Keep answers short and to the point (2-4 sentences max).

Examples of correct behavior:
Q: "in se baat kaha pr kru?"
A: "Hi! 😊 Aap N2X System se baat karne ke liye email info@n2xsystem.com, phone +92 323 452 9766, ya website www.n2xsystem.com use kar sakte hain. Address: Plot C 12, Street 195, DHA Phase 1, Lahore."

Q: "tum se contact kaise karu?"
A: "Hello! Aap humein email info@n2xsystem.com par likh sakte hain, +92 323 452 9766 par call kar sakte hain, ya website www.n2xsystem.com par visit kar sakte hain. 😊"""

DEFAULT_GREETING = "Hello! Main aapki kaise madad kar sakta hoon?"


def seed_default_agent():
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM agents").fetchone()
        if row["c"] == 0:
            conn.execute(
                "INSERT INTO agents (name, system_prompt, greeting) VALUES (?, ?, ?)",
                ("N2X Assistant", DEFAULT_SYSTEM_PROMPT, DEFAULT_GREETING),
            )


def save_message(session_id: str, role: str, content: str, was_fallback: int = 0):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, was_fallback) VALUES (?, ?, ?, ?)",
            (session_id, role, content, was_fallback),
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


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

PERIODS = ("today", "week", "month", "all")


def _period_cutoff(period: str) -> str | None:
    """Return the earliest allowed created_at (SQLite datetime string) for a
    period, or None for 'all'. Days are counted from UTC now, matching the
    datetime('now') default used by the messages table."""
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
    return "WHERE created_at >= ?", [cutoff]


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
        where_clause += " AND created_at >= ?"
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
    fallbacks = row["fallbacks"] if row else 0
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
            SELECT date(created_at) AS day, COUNT(DISTINCT session_id) AS c
            FROM messages
            WHERE created_at >= ?
            GROUP BY day
            """,
            [start_str],
        ).fetchall()
    by_day = {r["day"]: r["c"] for r in rows}

    result = []
    for i in range(last_n_days):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        result.append({"date": day, "count": by_day.get(day, 0)})
    return result


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


def create_agent(name: str, system_prompt: str, greeting: str) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO agents (name, system_prompt, greeting) VALUES (?, ?, ?)",
            (name, system_prompt, greeting),
        )
        agent_id = cur.lastrowid
    return get_agent(agent_id)


def get_agent(agent_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ?",
            (agent_id,),
        ).fetchone()
    return dict(row) if row else None


def list_agents() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, system_prompt, greeting, created_at
            FROM agents
            ORDER BY id
            """
        ).fetchall()
    return [dict(r) for r in rows]


def update_agent(agent_id: int, name: str, system_prompt: str, greeting: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE agents SET name = ?, system_prompt = ?, greeting = ? WHERE id = ?",
            (name, system_prompt, greeting, agent_id),
        )
    return cur.rowcount > 0


def delete_agent(agent_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    return cur.rowcount > 0
