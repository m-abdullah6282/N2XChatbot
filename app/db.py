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

        _ensure_column(conn, "messages", "was_fallback", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "admin_sessions", "admin_user_id", "INTEGER")
        _ensure_column(conn, "admin_users", "role", "TEXT NOT NULL DEFAULT 'admin'")
        _ensure_column(conn, "agents", "owner_admin_id", "INTEGER REFERENCES admin_users(id)")
        _ensure_column(conn, "agents", "slug", "TEXT")
        _ensure_column(conn, "agents", "description", "TEXT NOT NULL DEFAULT ''")

        # SQLite cannot add a UNIQUE constraint via ALTER TABLE ADD COLUMN, so
        # the slug's uniqueness is enforced with a dedicated index. NULL slugs
        # (pre-migration rows) are permitted until backfill_agent_slugs runs.
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_slug ON agents(slug)")

    seed_default_agent()
    seed_default_admin()
    backfill_agent_owners()
    backfill_agent_slugs()
    backfill_agent_descriptions()


NO_RELEVANT_CONTEXT_FOUND = "NO_RELEVANT_CONTEXT_FOUND"

FALLBACK_MESSAGE = (
    "Mujhe iski exact information nahi mili. "
    "Main aapko hamare team se connect kar deta hoon."
)

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
  - TYPE B (FACTUAL): answer ONLY from the Context below. You MUST NOT use outside knowledge, general knowledge, or anything learned during training for any factual claim. Never guess or make anything up. If the Context is exactly "{NO_RELEVANT_CONTEXT_FOUND}", it means no relevant information was found in the knowledge base; in that case reply with EXACTLY this message and nothing else:
{FALLBACK_MESSAGE}
Do NOT attempt to answer the question and do NOT use general knowledge when the Context has no relevant information.

5. Be friendly, warm and conversational. Use emojis naturally to make the chat feel lively. 😊

6. Keep answers short and to the point (2-4 sentences max).

Examples of correct behavior:
Q: "in se baat kaha pr kru?"
A: "Hi! 😊 Aap N2X System se baat karne ke liye email info@n2xsystem.com, phone +92 323 452 9766, ya website www.n2xsystem.com use kar sakte hain. Address: Plot C 12, Street 195, DHA Phase 1, Lahore."

Q: "tum se contact kaise karu?"
A: "Hello! Aap humein email info@n2xsystem.com par likh sakte hain, +92 323 452 9766 par call kar sakte hain, ya website www.n2xsystem.com par visit kar sakte hain. 😊"""  # noqa: E501

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


def save_message(session_id: str, role: str, content: str, was_fallback: int = 0) -> int:
    """Insert a message and return its autoincrement id so callers (e.g. the
    /chat response) can tell the widget exactly which row was created."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, was_fallback) VALUES (?, ?, ?, ?)",
            (session_id, role, content, was_fallback),
        )
        return cur.lastrowid


def get_session_messages(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, created_at
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
) -> dict:
    with get_conn() as conn:
        final_slug = _unique_slug(conn, slug or name)
        cur = conn.execute(
            "INSERT INTO agents (name, description, system_prompt, greeting, owner_admin_id, slug) VALUES (?, ?, ?, ?, ?, ?)",
            (
                name,
                description,
                _resolve_system_prompt(name, description, system_prompt),
                greeting,
                owner_admin_id,
                final_slug,
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
               a.created_at, a.owner_admin_id, au.username AS owner_username
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
            agent_id,
        ]
        scope = ""
        if admin_id is not None and role != "super_admin":
            scope = " AND owner_admin_id = ?"
            params.append(admin_id)
        cur = conn.execute(
            "UPDATE agents SET name = ?, description = ?, system_prompt = ?, greeting = ?, slug = ? WHERE id = ?{scope}".format(scope=scope),
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
