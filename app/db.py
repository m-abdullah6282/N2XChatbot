import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timedelta

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME

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
                agent_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key TEXT NOT NULL UNIQUE,
                api_key_hash TEXT,
                label TEXT NOT NULL,
                admin_id INTEGER,
                agent_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_used_at TEXT,
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
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL,
                greeting TEXT NOT NULL,
                owner_admin_id INTEGER REFERENCES admin_users(id),
                slug TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS handoffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                agent_id INTEGER,
                question TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                status TEXT NOT NULL DEFAULT 'pending',
                resolved_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER REFERENCES agents(id),
                owner_admin_id INTEGER REFERENCES admin_users(id),
                filename TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                file_path TEXT,
                file_size INTEGER NOT NULL DEFAULT 0,
                chunks_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL REFERENCES admin_users(id),
                plan_id INTEGER NOT NULL REFERENCES plans(id),
                status TEXT NOT NULL DEFAULT 'pending',
                current_period_start TEXT,
                current_period_end TEXT,
                cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL REFERENCES admin_users(id),
                subscription_id INTEGER REFERENCES subscriptions(id),
                provider TEXT NOT NULL DEFAULT 'manual',
                transaction_id TEXT,
                amount REAL NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'PKR',
                status TEXT NOT NULL DEFAULT 'pending',
                provider_reference TEXT,
                provider_response TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL REFERENCES admin_users(id),
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
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
        # Plans: new editable fields. max_agents stands in for max_ai_agents and
        # max_support_agents is added alongside an unlimited flag. None = unlimited.
        _ensure_column(conn, "plans", "max_support_agents", "INTEGER")
        _ensure_column(conn, "plans", "unlimited_ai_agents", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "plans", "unlimited_support_agents", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "plans", "unlimited_documents", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "plans", "unlimited_messages", "INTEGER NOT NULL DEFAULT 0")

        # SQLite cannot add a UNIQUE constraint via ALTER TABLE ADD COLUMN, so
        # the slug's uniqueness is enforced with a dedicated index. NULL slugs
        # (pre-migration rows) are permitted until backfill_agent_slugs runs.
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_slug ON agents(slug)")
        # A document filename is unique within its scope (agent_id or shared
        # NULL scope). SQLite permits multiple NULLs in a UNIQUE index, which
        # matches the shared-scope behavior (agent_id IS NULL).
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_scope_filename "
            "ON documents(agent_id, filename)"
        )

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

    - agent_id=None  → shared root:  <project>/uploaded_files/
    - agent_id given → agent folder: <project>/uploaded_files/agent_<id>/
    """
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploaded_files")
    if agent_id is None:
        return base
    return os.path.join(base, f"agent_{agent_id}")

# The ONE universal system-prompt template every agent shares. It is a single
# constant that carries all FIXED behavior rules (language handling, greeting
# hygiene, casual vs factual classification, contact/address handling, fallback,
# tone, answer length). Admins never edit it.
#
# The template has exactly two placeholders the agent fills in:
#   {agent_name}        -> the agent's name
#   {agent_description} -> the agent's one-line description/purpose
#
# build_system_prompt() fills them; a custom "Advanced System Prompt" (optional,
# power-user) can override the whole thing per-agent and is stored in the row.
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
        # Lazy import to avoid circular deps / heavy startup cost
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
        # RAG module not available — graceful degradation
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
    """Return the correct system prompt for a resolved agent dict.

    - If the agent has a non-empty custom (Advanced) system prompt, use it.
    - Otherwise, build the universal template filled with the agent's
      name + description.
    - Falls back to DEFAULT_SYSTEM_PROMPT when agent is None.
    """
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
    """Return the greeting message for a resolved agent dict."""
    if not agent:
        return DEFAULT_GREETING
    return (agent.get("greeting") or DEFAULT_GREETING).strip() or DEFAULT_GREETING


def seed_default_agent():
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM agents").fetchone()
        if row["c"] == 0:
            conn.execute(
                "INSERT INTO agents (name, description, system_prompt, greeting, slug) VALUES (?, ?, ?, ?, ?)",
                ("N2X Assistant", DEFAULT_AGENT_DESCRIPTION, DEFAULT_SYSTEM_PROMPT, DEFAULT_GREETING, "n2x-assistant"),
            )


def _default_agent_owner(conn: sqlite3.Connection) -> int | None:
    """The admin agents are assigned to during migration. Prefer the original
    .env super admin, then any super admin, then the oldest admin."""
    row = conn.execute(
        "SELECT id FROM admin_users WHERE username = ? ORDER BY id LIMIT 1",
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
    """Migration safety: assign every agent without an owner to the original
    .env super admin so no pre-existing agent is left orphaned."""
    with get_conn() as conn:
        owner_id = _default_agent_owner(conn)
        if owner_id is None:
            return
        conn.execute(
            "UPDATE agents SET owner_admin_id = ? WHERE owner_admin_id IS NULL",
            (owner_id,),
        )


# ---------------------------------------------------------------------------
# Admin users
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password with PBKDF2-HMAC-SHA256 and a per-user random salt.
    Returns (password_hash, salt)."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    )
    return digest.hex(), salt


def seed_default_admin():
    """Ensure at least one super admin exists.

    On an empty table, seeds the .env ADMIN_USERNAME / ADMIN_PASSWORD as the
    super admin. On an existing DB the column migration gives every row the
    default 'admin' role; here we promote the original .env-seeded admin so
    there is always at least one super admin in the system."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM admin_users").fetchone()
        if row["c"] == 0:
            password_hash, salt = _hash_password(ADMIN_PASSWORD)
            conn.execute(
                "INSERT INTO admin_users (username, password_hash, salt, role) VALUES (?, ?, ?, ?)",
                (ADMIN_USERNAME, password_hash, salt, "super_admin"),
            )
            return

        env_admin = conn.execute(
            "SELECT id FROM admin_users WHERE username = ? ORDER BY id LIMIT 1",
            (ADMIN_USERNAME,),
        ).fetchone()
        if env_admin:
            conn.execute(
                "UPDATE admin_users SET role = 'super_admin' WHERE id = ?",
                (env_admin["id"],),
            )
            return

        super_count = conn.execute(
            "SELECT COUNT(*) AS c FROM admin_users WHERE role = 'super_admin'"
        ).fetchone()["c"]
        if super_count == 0:
            first = conn.execute("SELECT id FROM admin_users ORDER BY id LIMIT 1").fetchone()
            if first:
                conn.execute(
                    "UPDATE admin_users SET role = 'super_admin' WHERE id = ?",
                    (first["id"],),
                )


def create_admin_user(username: str, password: str, role: str = "admin") -> dict:
    password_hash, salt = _hash_password(password)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO admin_users (username, password_hash, salt, role) VALUES (?, ?, ?, ?)",
            (username, password_hash, salt, role),
        )
        admin_id = cur.lastrowid
    # Grant an active Free subscription so a newly-created normal admin is not
    # locked out of plan-limit enforcement (mirrors the migration backfill).
    seed_plans()
    if get_current_subscription(admin_id) is None:
        free = get_plan_by_name("Free")
        if free is not None:
            create_subscription(admin_id, free["id"], "active")
    return get_admin_user(admin_id)


def get_admin_role(admin_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT role FROM admin_users WHERE id = ?",
            (admin_id,),
        ).fetchone()
    return row["role"] if row else None


def get_admin_user(admin_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, role, created_at FROM admin_users WHERE id = ?",
            (admin_id,),
        ).fetchone()
    return dict(row) if row else None


def get_admin_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, role, created_at FROM admin_users WHERE username = ?",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def verify_admin_user(username: str, password: str) -> dict | None:
    """Return the admin user info if credentials match, else None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, salt FROM admin_users WHERE username = ?",
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
    """Delete an admin user. Returns False (and deletes nothing) when it is
    the last remaining admin, or the last remaining super_admin, so at least
    one admin and one super_admin always survive."""
    with get_conn() as conn:
        target = conn.execute(
            "SELECT role FROM admin_users WHERE id = ?", (admin_id,)
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
        cur = conn.execute("DELETE FROM admin_users WHERE id = ?", (admin_id,))
        if cur.rowcount > 0:
            conn.execute(
                "DELETE FROM admin_sessions WHERE admin_user_id = ?", (admin_id,)
            )
    return cur.rowcount > 0


def change_admin_password(admin_id: int, new_password: str) -> bool:
    password_hash, salt = _hash_password(new_password)
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE admin_users SET password_hash = ?, salt = ? WHERE id = ?",
            (password_hash, salt, admin_id),
        )
    return cur.rowcount > 0


def save_message(
    session_id: str, role: str, content: str, was_fallback: int = 0, agent_id: int | None = None
) -> int:
    """Insert a message and return its autoincrement id so callers (e.g. the
    /chat response) can tell the widget exactly which row was created. When an
    agent_id is known (new conversations) it is persisted so every conversation
    reliably belongs to an agent."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, was_fallback, agent_id) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, was_fallback, agent_id),
        )
        return cur.lastrowid


def get_session_messages(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, agent_id, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY id
            """,
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Human agent handoff
# ---------------------------------------------------------------------------

def create_or_update_handoff(session_id: str, question: str, agent_id: int | None = None):
    """Flag a conversation for human review. If a pending handoff already
    exists for this session, refresh its question/timestamp instead of
    creating a duplicate row."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM handoffs WHERE session_id = ? AND status = 'pending'",
            (session_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE handoffs
                SET question = ?, agent_id = ?, created_at = datetime('now')
                WHERE id = ?
                """,
                (question, agent_id, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO handoffs (session_id, agent_id, question) VALUES (?, ?, ?)",
                (session_id, agent_id, question),
            )


def get_pending_handoffs(admin_id: int | None = None, role: str | None = None) -> list[dict]:
    """Pending fallbacks, scoped by admin role:
    - super_admin (admin_id=None too): every pending fallback.
    - regular admin: only fallbacks from agents they own, plus unassigned
      (agent_id NULL) shared fallbacks that belong to no specific agent."""
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
            "(SELECT id FROM agents WHERE owner_admin_id = ?))"
        )
        params.append(admin_id)
    query += " ORDER BY h.id DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_handoff(session_id: str) -> dict | None:
    """Latest handoff row for a session (any status), so replies can stay
    attributed to the conversation's agent."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, session_id, agent_id, question, status, created_at
            FROM handoffs
            WHERE session_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def resolve_handoff(session_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE handoffs
            SET status = 'resolved', resolved_at = datetime('now')
            WHERE session_id = ? AND status = 'pending'
            """,
            (session_id,),
        )
    return cur.rowcount > 0


def get_conversations() -> list[dict]:
    """All conversation messages with agent + owner info joined in (legacy
    messages may have NULL agent_id). Used by the Super Admin."""
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
    """Conversation messages scoped to one normal admin: only messages whose
    agent is owned by that admin, plus legacy messages that carry no agent
    (recall that historical pre-agent rows cannot be reliably attributed to an
    owner, so they are intentionally excluded for normal admins to avoid
    leaking another admin's data)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.session_id, m.role, m.content, m.created_at,
                   m.agent_id, a.name AS agent_name
            FROM messages m
            INNER JOIN agents a ON a.id = m.agent_id
            WHERE a.owner_admin_id = ?
            ORDER BY m.id
            """,
            (admin_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversations_summary(
    admin_id: int | None = None, role: str | None = None
) -> list[dict]:
    """Grouped conversation summaries for the chat-history / live-chat views.

    Super admin (admin_id None): every conversation across all admins/agents.
    Normal admin: conversations on their own agents only.

    Each summary carries: session_id, agent_id, agent_name, owner display,
    first + last activity time, last message preview, and message count.
    Conversations are identified per session+agent so the same session id
    against two agents is two distinct entries."""
    if admin_id is not None and role != "super_admin":
        return _conversation_summaries_clause("WHERE a.owner_admin_id = ?", [admin_id])
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
                  AND m2.agent_id IS m.agent_id
                ORDER BY m2.id DESC LIMIT 1) AS last_message
        FROM messages m
        LEFT JOIN agents a ON a.id = m.agent_id
        LEFT JOIN admin_users au ON au.id = a.owner_admin_id
        {clause}
        GROUP BY m.session_id, m.agent_id
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


def get_admin_activity_overview() -> list[dict]:
    """Per-admin activity summary for the Super Admin dashboard.
    Returns a list of dicts with username, role, agents count, total conversations,
    total messages, pending handoffs, and last activity time."""
    admins = list_admin_users()
    result = []
    with get_conn() as conn:
        for a in admins:
            admin_id = a["id"]
            # Count agents owned by this admin
            agents_row = conn.execute(
                "SELECT COUNT(*) AS c FROM agents WHERE owner_admin_id = ?",
                (admin_id,),
            ).fetchone()
            agent_count = agents_row["c"] if agents_row else 0

            # Count conversations (distinct session_id) for this admin's agents
            conv_row = conn.execute(
                """
                SELECT COUNT(DISTINCT m.session_id) AS c
                FROM messages m
                INNER JOIN agents ag ON ag.id = m.agent_id
                WHERE ag.owner_admin_id = ?
                """,
                (admin_id,),
            ).fetchone()
            conv_count = conv_row["c"] if conv_row else 0

            # Count total messages for this admin's agents
            msg_row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM messages m
                INNER JOIN agents ag ON ag.id = m.agent_id
                WHERE ag.owner_admin_id = ?
                """,
                (admin_id,),
            ).fetchone()
            msg_count = msg_row["c"] if msg_row else 0

            # Count pending handoffs for this admin's agents
            ho_row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM handoffs h
                INNER JOIN agents ag ON ag.id = h.agent_id
                WHERE ag.owner_admin_id = ? AND h.status = 'pending'
                """,
                (admin_id,),
            ).fetchone()
            handoff_count = ho_row["c"] if ho_row else 0

            # Last activity time
            last_row = conn.execute(
                """
                SELECT MAX(m.created_at) AS last_active
                FROM messages m
                INNER JOIN agents ag ON ag.id = m.agent_id
                WHERE ag.owner_admin_id = ?
                """,
                (admin_id,),
            ).fetchone()
            last_active = last_row["last_active"] if last_row else None

            # Count documents uploaded for this admin's agents
            doc_count = 0
            for agent_id_row in conn.execute(
                "SELECT id FROM agents WHERE owner_admin_id = ?", (admin_id,)
            ).fetchall():
                agent_dir = os.path.join("uploaded_files", f"agent_{agent_id_row['id']}")
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
    """Migration safety: populate api_key_hash for any pre-hashing plaintext
    key whose hash column is still NULL, so those legacy keys validate via the
    hash path on a later run. The raw key column is left in place (it cannot
    be reliably erased without breaking nothing; it is only used as a
    fallback lookup). Idempotent."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, api_key FROM api_keys WHERE api_key_hash IS NULL"
        ).fetchall()
        for row in rows:
            if row["api_key"]:
                conn.execute(
                    "UPDATE api_keys SET api_key_hash = ? WHERE id = ?",
                    (_hash_api_key(row["api_key"]), row["id"]),
                )


def backfill_message_agent_ids():
    """Migration safety: attach legacy NULL-agent messages (assistant/human
    replies persisted before agent attribution) to the most recently observed
    agent of their session, so they are no longer dropped by the conversation
    summary's agent JOIN. Sessions with no attributable message keep NULL
    (truly un-attributable legacy/test rows stay visible only to super admins
    via the raw /conversations feed). Idempotent."""
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


def create_api_key(label: str, admin_id: int | None = None, agent_id: int | None = None) -> str:
    api_key = "n2x_" + secrets.token_hex(24)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO api_keys (api_key, api_key_hash, label, admin_id, agent_id) VALUES (?, ?, ?, ?, ?)",
            (api_key, _hash_api_key(api_key), label, admin_id, agent_id),
        )
    return api_key


def _mask_key(key: str) -> str:
    """Return a truncated, non-sensitive key display for the UI (the raw key is
    shown once at creation time and never echoed again)."""
    if not key:
        return ""
    if len(key) <= 10:
        return key
    return key[:6] + "…" + key[-4:]


def list_api_keys(admin_id: int | None = None, role: str | None = None, agent_id: int | None = None) -> list[dict]:
    """List API keys. A regular admin only sees keys they own; a super admin
    may optionally filter by agent_id. Keys are never stored in plaintext, so
    the raw key cannot be shown; a masked preview is returned instead."""
    query = """
        SELECT k.id, k.label, k.admin_id, k.agent_id, k.is_active, k.last_used_at, k.created_at,
               a.name AS agent_name
        FROM api_keys k
        LEFT JOIN agents a ON a.id = k.agent_id
    """
    params: list = []
    clauses: list[str] = []
    if admin_id is not None and role != "super_admin":
        clauses.append("k.admin_id = ?")
        params.append(admin_id)
    if agent_id is not None:
        if role == "super_admin":
            clauses.append("k.agent_id = ?")
            params.append(agent_id)
        else:
            clauses.append("k.agent_id = ? AND k.admin_id = ?")
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


def delete_api_key(key_id: int, admin_id: int | None = None, role: str | None = None) -> bool:
    """Revoke/delete an API key. A regular admin can only delete their own keys.
    Historical keys are hard-deleted (the raw secret is never recoverable)."""
    params: list = [key_id]
    scope = ""
    if admin_id is not None and role != "super_admin":
        scope = " AND admin_id = ?"
        params.append(admin_id)
    with get_conn() as conn:
        cur = conn.execute(f"DELETE FROM api_keys WHERE id = ?{scope}", params)
    return cur.rowcount > 0


def resolve_api_key(raw_key: str, want_agent_id: int | None = None) -> dict | None:
    """Resolve a raw API key to its agent + admin, enforcing that the key is
    active and (when :param want_agent_id: is given) that the key belongs to
    that agent. Returns None when invalid/revoked/mismatched. Updates
    last_used_at on success.

    Lookup order: a new key is stored as its SHA-256 hash (api_key_hash), so we
    match by hash first. Legacy keys predate hashing and live in plaintext in
    the api_key column, so we fall back to a plaintext match for them. The raw
    key is never surfaced."""
    if not raw_key:
        return None
    hashed = _hash_api_key(raw_key)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE api_key_hash = ?", (hashed,)
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE api_key = ?", (raw_key,)
            ).fetchone()
    if not row or not row["is_active"]:
        return None
    key = dict(row)
    if want_agent_id is not None and key.get("agent_id") != want_agent_id:
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?",
            (key["id"],),
        )
    return key


def create_admin_session(token: str, admin_user_id: int | None = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO admin_sessions (token, admin_user_id) VALUES (?, ?)",
            (token, admin_user_id),
        )


def admin_session_exists(token: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM admin_sessions WHERE token = ?",
            (token,),
        ).fetchone()
    return row is not None


def get_session_admin_id(token: str) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT admin_user_id FROM admin_sessions WHERE token = ?",
            (token,),
        ).fetchone()
    return row["admin_user_id"] if row else None


def delete_admin_session(token: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
    return cur.rowcount > 0


def get_agent_by_slug(slug: str) -> dict | None:
    """Fetch an agent by its URL-friendly slug (used by /chat/{slug})."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT a.*, au.username AS owner_username
            FROM agents a
            LEFT JOIN admin_users au ON au.id = a.owner_admin_id
            WHERE a.slug = ?
            """,
            (slug,),
        ).fetchone()
    return _mark_custom_prompt(dict(row)) if row else None


def get_agent_for_request(
    slug: str | None = None,
    api_key: str | None = None,
    agent_id: int | None = None,
) -> dict | None:
    """Resolve the active agent for an incoming chat request.

    Priority:
      1. ``agent_id`` directly (internal / already resolved calls)
      2. ``slug``     (public widget / embed URL  e.g. /chat/my-agent)
      3. ``api_key``  (API consumers that pass X-API-Key header)

    Returns the full agent dict (same shape as ``get_agent``), or None when
    nothing matches. The caller should 404 / reject on None.
    """
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
    """Turn a name into a URL-friendly slug: lowercase, hyphen-separated,
    no special characters (e.g. "Sales Assistant!" -> "sales-assistant")."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return slug or "agent"


def _unique_slug(conn: sqlite3.Connection, base: str = "", exclude_agent_id: int | None = None) -> str:
    """Return a unique slug derived from ``base``, appending -2, -3, ... when
    a collision exists (or when the same agent already holds it)."""
    candidate = _slugify(base)
    n = 2
    while True:
        if exclude_agent_id is not None:
            row = conn.execute(
                "SELECT 1 FROM agents WHERE slug = ? AND id != ?",
                (candidate, exclude_agent_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM agents WHERE slug = ?",
                (candidate,),
            ).fetchone()
        if not row:
            return candidate
        candidate = f"{_slugify(base)}-{n}"
        n += 1


def backfill_agent_slugs():
    """Migration safety: give every pre-slug agent a slug derived from its
    name. Idempotent — rows updated once, collisions get -2/-3 suffixes."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name FROM agents WHERE slug IS NULL OR slug = '' ORDER BY id"
        ).fetchall()
        for row in rows:
            slug = _unique_slug(conn, row["name"], exclude_agent_id=row["id"])
            conn.execute("UPDATE agents SET slug = ? WHERE id = ?", (slug, row["id"]))


def _extract_agent_description(legacy_prompt: str, name: str) -> str:
    """Derive a short one-line purpose for a legacy agent whose row predates
    the name/description/greeting schema."""
    legacy = (legacy_prompt or "").strip()
    if "N2X System's friendly chat assistant" in legacy:
        return DEFAULT_AGENT_DESCRIPTION
    match = re.search(r"You are (?:the |a |an )?([^.\n]{8,250})\.?", legacy)
    if match:
        return match.group(1).replace("*", "").strip()
    return f"{name} - Aapke sawalon ke jawab dene ke liye."


def backfill_agent_descriptions():
    """Migration safety: give every pre-description agent a one-line purpose
    derived from its legacy system prompt. Idempotent — only rows whose
    description is still empty/whitespace get updated."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, system_prompt FROM agents WHERE description IS NULL OR description = ''"
        ).fetchall()
        for row in rows:
            description = _extract_agent_description(row["system_prompt"], row["name"])
            conn.execute(
                "UPDATE agents SET description = ? WHERE id = ?",
                (description, row["id"]),
            )


def _resolve_system_prompt(name: str, description: str, custom: str = "") -> str:
    """The stored prompt is the universal template filled with the agent's
    name/description — unless the admin provided a non-empty custom override
    (Advanced System Prompt)."""
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
        cur = conn.execute(
            "INSERT INTO agents (name, description, system_prompt, greeting, owner_admin_id, slug, primary_color) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                description,
                _resolve_system_prompt(name, description, system_prompt),
                greeting,
                owner_admin_id,
                final_slug,
                primary_color or "#2563EB",
            ),
        )
        agent_id = cur.lastrowid
    return get_agent(agent_id)


def _mark_custom_prompt(agent: dict) -> dict:
    """Expose whether the stored system prompt is a manual (Advanced) override
    rather than the auto-built universal-template prompt. The admin UI uses
    this to pre-expand the Advanced section for legacy/custom agents."""
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
    """Fetch an agent. When admin_id/role are given, a non-super admin only
    gets their own agents (anything else returns None)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT a.*, au.username AS owner_username
            FROM agents a
            LEFT JOIN admin_users au ON au.id = a.owner_admin_id
            WHERE a.id = ?
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
    """List agents, optionally scoped to one admin. The super admin case
    (admin_id=None) returns every agent, each with its owner username."""
    query = """
        SELECT a.id, a.name, a.description, a.system_prompt, a.greeting, a.slug,
               a.created_at, a.owner_admin_id, a.primary_color,
               au.username AS owner_username
        FROM agents a
        LEFT JOIN admin_users au ON au.id = a.owner_admin_id
    """
    params: list = []
    if admin_id is not None:
        query += " WHERE a.owner_admin_id = ?"
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
    """Update an agent. A non-super admin can only update their own agents
    (returns False otherwise). The slug is always kept unique: when a non-empty
    slug is supplied its slugified form is used, otherwise it is re-derived
    from ``name``. The stored system prompt defaults to the universal template
    filled with name/description; a non-empty ``system_prompt`` overrides it."""
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
            color_sql = ", primary_color = ?"
            params.append(primary_color)
        params.append(agent_id)
        scope = ""
        if admin_id is not None and role != "super_admin":
            scope = " AND owner_admin_id = ?"
            params.append(admin_id)
        cur = conn.execute(
            "UPDATE agents SET name = ?, description = ?, system_prompt = ?, greeting = ?, slug = ?{color_sql} WHERE id = ?{scope}".format(
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
    """Delete an agent. A non-super admin can only delete their own agents
    (returns False otherwise)."""
    params: list = [agent_id]
    scope = ""
    if admin_id is not None and role != "super_admin":
        scope = " AND owner_admin_id = ?"
        params.append(admin_id)
    with get_conn() as conn:
        cur = conn.execute(f"DELETE FROM agents WHERE id = ?{scope}", params)
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Documents (relational record of uploaded knowledge files)
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
    """Insert a document record and return its id. agent_id=None represents a
    shared (platform-level) document, mirroring the existing Qdrant scope
    convention where a missing agent_id payload means 'shared'."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO documents
                (agent_id, owner_admin_id, filename, original_filename,
                 file_path, file_size, status)
            VALUES (?, ?, ?, ?, ?, ?, 'processing')
            """,
            (agent_id, owner_admin_id, filename, original_filename, file_path, file_size),
        )
        return cur.lastrowid


def update_document_status(
    document_id: int,
    status: str,
    chunks_count: int | None = None,
    error_message: str | None = None,
) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE documents
            SET status = ?,
                chunks_count = COALESCE(?, chunks_count),
                error_message = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (status, chunks_count, error_message, document_id),
        )
    return cur.rowcount > 0


def set_document_file_size(document_id: int, file_size: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE documents SET file_size = ?, updated_at = datetime('now') WHERE id = ?",
            (file_size, document_id),
        )
    return cur.rowcount > 0


def get_document(document_id: int, admin_id: int | None = None, role: str | None = None) -> dict | None:
    """Fetch a document. A non-super admin can only fetch documents they own
    (or, for shared agent_id=NULL documents, only the ones they uploaded)."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
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
    """List documents within one scope.

    - scope='shared' (agent_id=None): platform-level documents that every admin
      may see (existing shared-knowledge behaviour is preserved). A normal admin
      additionally sees only the shared documents they uploaded.
    - scope='agent' (agent_id given): documents for one agent. A normal admin
      only sees documents on agents they own.
    """
    if scope == "agent" and agent_id is None:
        return []
    if scope == "agent":
        where = "WHERE agent_id = ?"
        params: list = [agent_id]
        if admin_id is not None and role != "super_admin":
            where += " AND agent_id IN (SELECT id FROM agents WHERE owner_admin_id = ?)"
            params.append(admin_id)
        query = "SELECT * FROM documents {where} ORDER BY id".format(where=where)
    else:
        where = "WHERE agent_id IS NULL"
        params = []
        if admin_id is not None and role != "super_admin":
            where += " AND owner_admin_id = ?"
            params.append(admin_id)
        query = "SELECT * FROM documents {where} ORDER BY id".format(where=where)
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def count_documents_for_admin(
    admin_id: int,
    statuses: tuple[str, ...] = ("processing", "ready"),
) -> int:
    """Count documents owned by an admin (by owner_admin_id) in the given
    statuses. Used for plan document-limit enforcement. Shared documents
    uploaded by this admin are included so uploads are not a loophole."""
    if not statuses:
        return 0
    placeholders = ",".join("?" for _ in statuses)
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS c FROM documents
            WHERE owner_admin_id = ? AND status IN ({placeholders})
            """,
            (admin_id, *statuses),
        ).fetchone()
    return row["c"] if row else 0


def delete_document_record_by_scope(agent_id: int | None, filename: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM documents WHERE agent_id IS ? AND filename = ?",
            (agent_id, filename),
        )
    return cur.rowcount > 0


def backfill_documents():
    """Migration safety: create a documents row for every file already on disk
    that has no record yet. Nothing is deleted. Ownership:
    - agent-scoped files inherit the agent's owner_admin_id.
    - shared (agent_id=NULL) files cannot have their original uploader
      recovered, so owner_admin_id is left NULL (unknown) rather than guessed.
    chunks_count is 0 because the historical count is not stored anywhere."""
    import os as _os

    def _exists(conn, agent_id, filename):
        row = conn.execute(
            "SELECT 1 FROM documents WHERE agent_id IS ? AND filename = ? LIMIT 1",
            (agent_id, filename),
        ).fetchone()
        return row is not None

    base = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "uploaded_files")
    _os.makedirs(base, exist_ok=True)
    with get_conn() as conn:
        for name in _os.listdir(base):
            full = _os.path.join(base, name)
            if _os.path.isfile(full):
                if not _exists(conn, None, name):
                    conn.execute(
                        """
                        INSERT INTO documents
                            (agent_id, owner_admin_id, filename, original_filename,
                             file_path, file_size, status, chunks_count)
                        VALUES (NULL, NULL, ?, ?, ?, ?, 'ready', 0)
                        """,
                        (name, name, name, _os.path.getsize(full)),
                    )
        agent_dir_prefix = "agent_"
        for entry in _os.listdir(base):
            full = _os.path.join(base, entry)
            if _os.path.isdir(full) and entry.startswith(agent_dir_prefix):
                try:
                    agent_id = int(entry.split("_", 1)[1])
                except ValueError:
                    continue
                owner = conn.execute(
                    "SELECT owner_admin_id FROM agents WHERE id = ?", (agent_id,)
                ).fetchone()
                owner_id = owner["owner_admin_id"] if owner else None
                for fname in _os.listdir(full):
                    fpath = _os.path.join(full, fname)
                    if _os.path.isfile(fpath) and not _exists(conn, agent_id, fname):
                        conn.execute(
                            """
                            INSERT INTO documents
                                (agent_id, owner_admin_id, filename, original_filename,
                                 file_path, file_size, status, chunks_count)
                            VALUES (?, ?, ?, ?, ?, ?, 'ready', 0)
                            """,
                            (agent_id, owner_id, fname, fname,
                             _os.path.join(entry, fname), _os.path.getsize(fpath)),
                        )


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def _seed_plan(conn: sqlite3.Connection, spec: dict) -> None:
    """Insert a plan only if its name does not exist yet. For existing plans it
    safely backfills the new limit columns from the spec — it does NOT overwrite
    admin-edited values on later runs (only fills NULLs/0s)."""
    row = conn.execute(
        "SELECT 1 FROM plans WHERE name = ?", (spec["name"],)
    ).fetchone()
    if not row:
        conn.execute(
            """
            INSERT INTO plans
                (name, price, currency, billing_interval, max_agents,
                 max_documents, unlimited_documents, max_messages_per_period,
                 unlimited_messages, is_active,
                 max_support_agents, unlimited_ai_agents, unlimited_support_agents)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    # Backfill the new unlimited columns for an existing plan whose row
    # predates them (NULL/0 only, never overwriting configured values).
    conn.execute(
        """
        UPDATE plans
        SET max_support_agents = COALESCE(max_support_agents, ?),
            unlimited_ai_agents = COALESCE(unlimited_ai_agents, ?),
            unlimited_support_agents = COALESCE(unlimited_support_agents, ?),
            unlimited_documents = COALESCE(unlimited_documents,
                CASE WHEN max_documents IS NULL THEN 1 ELSE 0 END),
            unlimited_messages = COALESCE(unlimited_messages,
                CASE WHEN max_messages_per_period IS NULL THEN 1 ELSE 0 END)
        WHERE name = ?
        """,
        (
            spec.get("max_support_agents"),
            1 if spec.get("unlimited_ai_agents") else 0,
            1 if spec.get("unlimited_support_agents") else 0,
            spec["name"],
        ),
    )


def seed_plans():
    """Seed the 4 default plans with production-default values:
    Free / Monthly / Yearly / Lifetime. None for a numeric limit means
    'unlimited'. Non-destructive: only inserts plans whose name is absent and
    only NULL-backfills the new limit columns of pre-existing plans."""
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
    """Migration safety: on an existing database the old sample plans
    (Basic/Pro) are left in place but deactivated after the Free/Lifetime
    defaults are seeded, so no working subscription breaks and historical rows
    survive. The 4 standard plan names are guaranteed present via seed_plans."""
    with get_conn() as conn:
        for old in ("Basic", "Pro"):
            conn.execute(
                "UPDATE plans SET is_active = 0 WHERE name = ? AND is_active = 1",
                (old,),
            )


def get_plan(plan_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return _normalize_plan(dict(row)) if row else None


def get_plan_by_name(name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM plans WHERE name = ?", (name,)).fetchone()
    return _normalize_plan(dict(row)) if row else None


def _normalize_plan(plan: dict) -> dict:
    """Expose plan limits in a stable shape plus legacy alias fields so
    existing consumers (subscription_service, UI) keep working. None for a
    numeric max is the 'unlimited' marker; the explicit unlimited_* booleans
    are also surfaced."""
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
    """All plans including inactive ones (for the Super Admin plan editor)."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM plans ORDER BY id").fetchall()
    return [_normalize_plan(dict(r)) for r in rows]


def update_plan(plan_id: int, fields: dict) -> bool:
    """Update editable plan fields. Allowed keys mirror the Super Admin plan
    editor. Numeric limits store NULL when marked unlimited. Only returns True
    when the plan exists."""
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
        elif key in ("max_agents", "max_support_agents", "max_documents", "max_messages_per_period"):
            value = None if value is None else int(value)
        setting.append(f"{key} = ?")
        params.append(value)
    setting.append("updated_at = datetime('now')")
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE plans SET {', '.join(setting)} WHERE id = ?",
            [*params, plan_id],
        )
    return cur.rowcount > 0


def get_plan_by_id(plan_id: int) -> dict | None:
    return get_plan(plan_id)


# ---------------------------------------------------------------------------
# Subscriptions (history preserved; at most one 'active' per admin)
# ---------------------------------------------------------------------------

def create_subscription(
    admin_id: int,
    plan_id: int,
    status: str = "pending",
    current_period_start: str | None = None,
    current_period_end: str | None = None,
) -> int:
    if current_period_start is None:
        current_period_start = "datetime('now')"
    if current_period_end is None:
        current_period_end = "datetime('now', '+30 days')"
    sql_start = (
        current_period_start
        if current_period_start.startswith("datetime(")
        else "?"
    )
    sql_end = current_period_end if current_period_end.startswith("datetime(") else "?"
    params: list = [admin_id, plan_id, status]
    if sql_start == "?":
        params.append(current_period_start)
    if sql_end == "?":
        params.append(current_period_end)
    with get_conn() as conn:
        cur = conn.execute(
            f"""
            INSERT INTO subscriptions
                (admin_id, plan_id, status, current_period_start, current_period_end)
            VALUES (?, ?, ?, {sql_start}, {sql_end})
            """,
            params,
        )
        return cur.lastrowid


def get_current_subscription(admin_id: int) -> dict | None:
    """Return the latest subscription row for an admin (the most recently
    created active one if several exist, otherwise the latest overall)."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE admin_id = ?
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
        query += " WHERE admin_id = ?"
        params.append(admin_id)
    query += " ORDER BY id DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def set_subscription_status(subscription_id: int, status: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE subscriptions SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, subscription_id),
        )
    return cur.rowcount > 0


def backfill_subscriptions():
    """Migration safety: give every existing admin user an active Free-plan
    subscription if they have none, so pre-existing admins keep working and
    plan-limit enforcement does not lock them out. This is a legacy/migration
    grant, not a payment-backed activation; it is clearly labelled as such."""
    free = get_plan_by_name("Free")
    if free is None:
        return
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM admin_users").fetchall()
        for r in rows:
            has = conn.execute(
                "SELECT 1 FROM subscriptions WHERE admin_id = ? LIMIT 1", (r["id"],)
            ).fetchone()
            if not has:
                conn.execute(
                    """
                    INSERT INTO subscriptions
                        (admin_id, plan_id, status, current_period_start, current_period_end)
                    VALUES (?, ?, 'active', datetime('now'), datetime('now', '+30 days'))
                    """,
                    (r["id"], free["id"]),
                )


# ---------------------------------------------------------------------------
# Payments (provider-independent; no API credentials stored)
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
    """Create a payment record. Always starts as 'pending'. A payment record
    never activates a subscription by itself — backend-side provider
    verification must do that via mark_payment_success + activate_subscription."""
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
        cur = conn.execute(
            """
            INSERT INTO payments
                (admin_id, subscription_id, provider, transaction_id,
                 amount, currency, status, provider_reference, provider_response)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (record["admin_id"], record["subscription_id"], record["provider"],
             record["transaction_id"], record["amount"], record["currency"],
             record["provider_reference"], provider_response),
        )
        record["id"] = cur.lastrowid
    return record


def get_payment(payment_id: int, admin_id: int | None = None, role: str | None = None) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
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
        query += " WHERE admin_id = ?"
        params.append(admin_id)
    query += " ORDER BY id DESC"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def set_payment_status(payment_id: int, status: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE payments SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, payment_id),
        )
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Usage tracking (foundation; not yet wired into the chat hot-path)
# ---------------------------------------------------------------------------

def get_usage_record(admin_id: int, period_start: str, period_end: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM usage_records
            WHERE admin_id = ? AND period_start = ? AND period_end = ?
            LIMIT 1
            """,
            (admin_id, period_start, period_end),
        ).fetchone()
    return dict(row) if row else None


def increment_usage(admin_id: int, period_start: str, period_end: str, amount: int = 1) -> None:
    """Increment (or create) the message usage for one admin within one period.
    Called at most once per message request by the usage service — it must not
    be invoked multiple times for the same request."""
    row = get_usage_record(admin_id, period_start, period_end)
    with get_conn() as conn:
        if row:
            conn.execute(
                "UPDATE usage_records SET message_count = message_count + ?, updated_at = datetime('now') WHERE id = ?",
                (amount, row["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO usage_records (admin_id, period_start, period_end, message_count)
                VALUES (?, ?, ?, ?)
                """,
                (admin_id, period_start, period_end, amount),
            )


def get_usage_for_period(admin_id: int, period_start: str, period_end: str) -> int:
    row = get_usage_record(admin_id, period_start, period_end)
    return row["message_count"] if row else 0