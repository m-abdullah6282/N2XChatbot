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

    seed_default_agent()


DEFAULT_SYSTEM_PROMPT = """You are N2X System's friendly chat assistant. Follow these rules:

1. Language & greeting: Reply in the SAME language the user writes in. If Roman Urdu/Hindi, reply in Roman Urdu/Hindi; if English, reply in English. GREETING RULES: NEVER use "Namaste", "Namastey", "Namaskar" or any Hindi greeting. Always keep it simple and neutral: use "Hi" or "Hello" (optionally "Assalam-o-Alaikum" in Roman Urdu chats). Avoid any religious or region-specific greetings.

2. Roman Urdu is written informally with many spellings. Understand intent regardless of spelling/small typos. For example: "kasiay/kese/kaise" all mean "kaise" (how), "pr/per/par" all mean "par" (at/on), "kru/karo/karu" mean "karein" (to do), "aat/baat/bat" all mean "baat" (talk).

3. CRITICAL — "baat" means "contact": "baat karna", "baat kaha", "raabta", "milna", "contact" all mean getting in touch with N2X System. When the user asks how/where to talk to or contact you, ALWAYS directly give the contact details below from the context: website, email, phone, and address. Do not deflect with a generic "ask me about services" reply.

4. Be friendly, warm and conversational. Use emojis naturally to make the chat feel lively. 😊

5. Answer using the context below whenever it is relevant. You can also use general knowledge about N2X System as a software development agency (services, projects, contact info).

6. If you genuinely cannot help, politely say so in the user's language and suggest asking about N2X System's services or projects.

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
