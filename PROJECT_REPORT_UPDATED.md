# N2X Knowledge Chatbot — Updated Full Project Report

**Base document compared against:** `PROJECT_REPORT.md` (old report, tracked in git).
**Verified against the live codebase** at commit `266d633`. All paths, endpoints, schemas and source code below were re-read from the current working tree, not assumed.

---

## CHANGELOG (changes since the old report)

### 🆕 Naya (NEW)
- **Human handoff system** — jab bot factual answer de saka na to vo `FALLBACK_MESSAGE` bolta hai aur conversation *handoff* hone ke liye flag hoti hai:
  - Naya DB table `handoffs` (`session_id`, `agent_id`, `question`, `status`, `resolved_at`).
  - Naye admin endpoints: `GET /admin/handoffs`, `POST /admin/handoffs/{session_id}/reply`, `POST /admin/handoffs/{session_id}/resolve`.
  - Naya public endpoint `GET /chat/messages/{session_id}` — widget isko poll karta hai human reply dekhne ke liye.
- **Analytics module** — `app/db.py` mein naye functions (`get_total_conversations`, `get_total_messages`, `get_fallback_rate`, `get_avg_messages_per_conversation`, `get_top_questions`, `get_conversations_per_day`) + naya admin endpoint `GET /admin/analytics?period=today|week|month|all`.
- **`was_fallback` column** in `messages` table (+ automatic `ALTER TABLE` migration for existing DBs). Naye constants `FALLBACK_MESSAGE` aur `NO_RELEVANT_CONTEXT_FOUND`.
- **`/chat` response extension** — ab `user_message_id` aur `message_id` (exact SQLite row ids) bhi return karta hai taaki widget apna "last seen" cursor update kar sake.
- **Casual/small-talk short-circuit** in `app/routes/chat.py` (`_casual_response`) — greeting/thanks/bye bina embeddings aur Qdrant ke handle hote hain.
- **Resilience layer**:
  - `app/services/embeddings.py` — model ab import-parnahi, lazy singleton load hota hai.
  - Qdrant unreachable ho to `search_similar_chunks` `(chunks, available)` return karta hai aur chat `RETRIEVAL_UNAVAILABLE_MESSAGE` bhejta hai.
  - `app/services/llm.py` — `MAX_RETRIES=3` backoff retry (rate-limit aware, daily-TPD quota aur connection/timeout errors handle hote hain).
- **Naye scripts**: `scripts/reindex_n2x_knowledge.py`, `scripts/qdrant_knowledge_base.py` (collection inventory / wipe CLI), `scripts/debug_retrieval.py` (+ artifacts `debug_retrieval_output.txt`, `debug_retrieval_error.txt`).
- **`GET /portfolio`** endpoint — `uploaded_files/N2X-System-Portfolio.pdf` serve karta hai (⚠️ ye file currently `uploaded_files/` mein exist nahi karti, isliye abhi ye endpoint 404 deta hai).
- **`static/index.html`** — pehle ek khaali stub tha; ab poora Tailwind marketing landing page hai (hero, services, stats, projects showcase, footer, portfolio + admin links) with chat widget v9.
- **`static/widget.js`** — agent picker dropdown, per-agent greeting, localStorage mein selected agent + last-seen cursor persistence, 15s polling for human handoff replies, naya brand color `#00C2B8`, panel launcher ke left side.
- **`static/admin.html`** — 6 tabs (Agents, Knowledge Base, Chat History, Needs Attention, Analytics, API Keys); agent create/edit with optional initial KB upload; KB scope selector (General vs per-agent); handoff reply/dismiss UI; analytics dashboard with SVG bar chart + top-5 questions.
- **`static/login.html`** — Tailwind redesign (pehle plain card tha).
- **`sales_special.txt`** — naya confidential pricing sheet. `uploaded_files/` mein ab: `n2x_knowledge.txt` (shared), `sales_special.txt` (shared), `agent_1/n2x_knowledge.txt`, `agent_4/sales_special.txt`.
- **Current DB runtime state**: `agents` = **N2X Assistant** (id 1) + **Sales Assistant** (id 4); `handoffs` = 14 rows; `messages` = 341 rows.

### 🔄 CHANGED / MODIFIED
- **LLM model**: `llama-3.3-70b-versatile` → **`groq/compound-mini`**, with `max_tokens=250`. `generate_answer(question, context)` → `generate_answer(question, context, system_prompt=DEFAULT_SYSTEM_PROMPT)`; prompt ab `BEHAVIOR_RULES` (TYPE A casual / TYPE B factual classification; factual = context-only, exact fallback message) ke sath compose hota hai.
- **`DEFAULT_SYSTEM_PROMPT`** rewrite — ab classification, context-only answering, EXACT fallback message, "baat = contact" rule, greeting restrictions (Hindi greetings forbidden) ke saath `f-string` constants se built hai.
- **Chunking** (`app/services/pdf_processor.py`): naive 500-char/50-overlap → **section/heading-aware chunking** (default `chunk_size=1500`, `overlap=0` unused), paragraph-boundary splitting, no mid-word breaks.
- **`app/services/vector_store.py`**: points ab `agent_id` payload + payload index rakhte hain; `store_chunks`/`delete_points_by_filename` agent-scoped; naya `delete_points_by_agent`; search ab `score_threshold=0.15`, agent filtering (**agent chat → shared + us agent ke points**, **no-agent chat → sirf shared**), aur heading/keyword boost (`query_text`) se enhanced hai; return ab `(chunks, availability)` tuple.
- **`app/db.py` `save_message`** — signature `(session_id, role, content, was_fallback=0)`, rowid return karta hai; naya `get_session_messages`.
- **`app/main.py`** — `logging.basicConfig` + `PORTFOLIO_PATH` + `/portfolio` route added.
- **Agent CRUD improvements** (`admin.py`) — blank-name → 400, duplicate-name `sqlite3.IntegrityError` → 400 "already exists", `PUT` returns updated agent. (Endpoints pehle se report mein the; implementation ab stricter hai.)
- **Chat flow** — contact disclaimers ab har jagah nahi hain balki context/KB + prompt se aate hain; `sources_used` ab retrieved chunks count par based hai (0 bhi ho sakta hai).
- **Widget UX** — static placeholder message removed; greeting ab selected agent se aata hai.

### 🗑️ REMOVED / DEPRECATED
- **`CONTACT_KEYWORDS` / `CONTACT_CHUNK` / `_is_contact_question`** in `app/routes/chat.py` — hardcoded contact-chunk injection hata diya (contact behavior ab system prompt + KB se handle hota hai).
- **Old naive 500/50 chunking** logic.
- **Import-time embedding model download** (ab lazy).
- **`all-points` retrieval for shared chats** — old report ab-described "shared OR agent's own" behavior; shared chat ab sirf shared points dekh sakta hai.
- **`N2X-System-Portfolio.pdf`** ab `uploaded_files/` mein nahi hai (old report had it) — hence `/portfolio` 404.
- `static/index.html` ka purana khaali stub → ab full landing page (old stub replaced).

### ♻️ UNCHANGED / STILL TRUE
- `requirements.txt` (bilkul wahi 9 pins), `.env` keys (GROQ_API_KEY, QDRANT_URL, QDRANT_API_KEY, ADMIN_USERNAME, ADMIN_PASSWORD), auth/session/cookie system, `api_keys` table (ab bhi `/chat` par validate nahi hota), CORS `*`, no rate limiting, no upload size limit, `start.bat` ab bhi empty, `.start.bat` same, `README.md` ab bhi sirf `# N2XChatbot` (UTF-16), DB tables `messages/api_keys/admin_sessions/agents` base structure.

---

## 1. Project Overview

**Name:** N2X Knowledge Chatbot (git repo: `N2XChatbot`)

**Purpose:** A retrieval-augmented generation (RAG) chatbot for **N2X System**, a software development agency in Lahore, Pakistan. Website visitors can chat with an AI assistant about the company (services, projects, pricing, contact) using a knowledge base uploaded by admins.

**Key capabilities (current):**
- Chat widget (embeddable) talking to a FastAPI backend.
- **Multiple AI agents**: admin creates/edits/deletes agents, each with its own **name**, **greeting**, **instructions (system prompt)**, and **separate knowledge base**. Seeded defaults: **N2X Assistant** (id 1) and **Sales Assistant** (id 4).
- **Agent picker in widget**: visitors switch agents via a dropdown in the chat header.
- Upload PDF/TXT docs → chunked (heading-aware), embedded, stored in Qdrant. Docs scoped to a specific agent or to the shared/general KB. Shared points are visible to every agent; a no-agent chat sees *only* shared points.
- On each factual question: embed query → search top-3 chunks (score threshold 0.15) → context to a Groq-hosted LLM (`groq/compound-mini`) which writes the answer using the selected agent's system prompt + universal behavior rules.
- **Behavior guardrails**: factual questions are answered ONLY from context; if no relevant info is found the bot replies with an exact fallback message and creates a **human handoff**.
- **Human handoff**: pending questions appear in admin "Needs Attention" tab; admin can write a reply (saved as an assistant message, delivered to the visitor's widget via polling) or dismiss/resolve.
- **Analytics**: total conversations/messages, fallback rate, avg messages per conversation, top-5 questions, conversations-per-day chart (today/week/month/all).
- Admin panel with login, agent management, per-agent KB upload/delete, chat history viewer, handoff queue, analytics, and API-key management.

---

## 2. Tech Stack

| Layer          | Technology                                             |
|----------------|--------------------------------------------------------|
| Web framework  | FastAPI 0.115 + Uvicorn 0.32 (ASGI server)             |
| Data validation| Pydantic 2.9                                           |
| LLM (inference)| Groq API — model `groq/compound-mini` (max_tokens 250, retry/backoff) |
| Embeddings     | `sentence-transformers` 3.2.1 — `all-MiniLM-L6-v2` (384-dim), lazy-loaded |
| Vector DB      | Qdrant (cloud) via `qdrant-client` 1.12, cosine distance, `knowledge_base` collection |
| PDF parsing    | `pypdf` 5.1                                             |
| Relational DB  | SQLite (local file `chatbot.db`)                       |
| Config         | `.env` via `python-dotenv`                             |
| Frontend       | Plain HTML/CSS/JS + **Tailwind CDN**, served as static files |

**Note:** The embedding model still runs locally (weights ~90 MB, downloaded on first lazy use). Qdrant and Groq are external network services. RAG pipeline remains hand-written (no LangChain).

---

## 3. Directory Structure

```
knowledge-chatbot/
├── .env                        # Secrets (GROQ_API_KEY, QDRANT_URL, QDRANT_API_KEY, ADMIN_USERNAME, ADMIN_PASSWORD)
├── .gitignore                  # venv/, .env, uploaded_files/, __pycache__/, *.pyc, chatbot.db
├── README.md                   # Only "# N2XChatbot" (UTF-16 encoded)
├── requirements.txt
├── start.bat                   # Empty file
├── .start.bat                  # Launcher: activate venv, open browser, run uvicorn --reload
├── chatbot.db                  # SQLite database (runtime)
├── PROJECT_REPORT.md           # OLD report (this doc's predecessor)
├── PROJECT_REPORT_UPDATED.md   # THIS report
├── n2x_knowledge.txt           # Company knowledge base (source)
├── sales_special.txt           # Confidential pricing sheet (source)
├── uploaded_files/             # Stored user/uploads
│   ├── n2x_knowledge.txt       # shared KB
│   ├── sales_special.txt       # shared KB
│   ├── agent_1/n2x_knowledge.txt
│   └── agent_4/sales_special.txt
├── venv/                       # Python virtual environment
├── scripts/
│   ├── reindex_n2x_knowledge.py    # re-index shared + agent copies (section-aware chunks)
│   ├── qdrant_knowledge_base.py    # inventory / wipe CLI for the collection
│   ├── debug_retrieval.py          # raw top-10 retrieval diagnostics (no score threshold)
│   ├── debug_retrieval_output.txt  # runtime artifact
│   └── debug_retrieval_error.txt   # runtime artifact
├── app/
│   ├── __init__.py             # empty
│   ├── config.py               # env vars
│   ├── db.py                   # SQLite helpers: messages w/ was_fallback, handoffs, analytics, agents, api_keys, sessions
│   ├── main.py                 # FastAPI app, CORS, logging, page routes, /portfolio
│   ├── models/
│   │   ├── __init__.py         # empty
│   │   └── schemas.py          # Pydantic models (ChatRequest, ApiKeyCreate, AgentCreate/Update, HandoffReply)
│   ├── routes/
│   │   ├── __init__.py         # empty
│   │   ├── admin.py            # auth, agents, documents, conversations, handoffs, analytics, api-keys
│   │   ├── chat.py             # POST /chat, GET /chat/messages/{session_id}
│   │   └── upload.py           # POST /upload (agent-scoped)
│   └── services/
│       ├── __init__.py         # empty
│       ├── auth.py             # login/session/auth dependency
│       ├── embeddings.py       # lazy SentenceTransformer wrapper
│       ├── llm.py              # Groq call w/ retries + BEHAVIOR_RULES
│       ├── pdf_processor.py    # PDF text extraction + heading-aware chunking
│       └── vector_store.py     # Qdrant operations (agent scoping, threshold, keyword boost)
└── static/
    ├── index.html              # Full Tailwind landing page (hero/services/stats/projects/footer) + widget v9
    ├── widget.js               # Chat widget (launcher + panel + agent picker + handoff polling)
    ├── admin.html              # 6-tab admin panel (Agents / KB / History / Needs Attention / Analytics / Keys)
    └── login.html              # Tailwind admin login
```

---

## 4. Data Flow

### 4.1 Document ingestion (admin uploads a file)

```
Admin uploads PDF/TXT (+ optional agent_id)  ->  POST /upload (admin cookie)
   -> file saved to uploaded_files/           (agent_id omitted -> shared/general)
      or uploaded_files/agent_<id>/<filename> (agent_id provided -> that agent only)
   -> text extracted (pypdf for PDF, decode for TXT)
   -> text split into HEADING-AWARE chunks (sections; 1500-char cap, paragraph boundaries)
   -> each chunk embedded (all-MiniLM-L6-v2 -> 384-dim)
   -> Qdrant collection "knowledge_base" ensured (filename + agent_id payload indexes)
   -> old points with same filename AND same agent scope deleted
   -> new points upserted (payload: text + filename [+ agent_id])
```

Each vector point carries an optional `agent_id` payload field. Points without `agent_id` belong to the **shared/general** knowledge base.

### 4.2 Chat (user asks a question)

```
POST /chat  { question, session_id?, agent_id? }
   -> if session_id: user message saved (rowid kept) -> was_fallback=0
   -> _casual_response() early-return for greetings/thanks/bye (no embeddings needed)
   -> question embedded (on failure -> RETRIEVAL_UNAVAILABLE_MESSAGE reply)
   -> search top-3 chunks in Qdrant (score >= 0.15); returns (chunks, available)
        agent_id given  -> shared (is_empty) OR that agent's points
        agent_id absent -> shared points ONLY
      on Qdrant failure -> RETRIEVAL_UNAVAILABLE_MESSAGE reply
   -> optional heading/keyword-boosted chunk prepended (query_text scan)
   -> chunks joined as "context"; if none -> context = NO_RELEVANT_CONTEXT_FOUND
   -> system_prompt = selected agent's prompt (or DEFAULT_SYSTEM_PROMPT)
   -> LLM (groq/compound-mini) composes prompt = system_prompt + BEHAVIOR_RULES + context
        - casual messages: warm reply (never fallback)
        - factual: answer only from context; if context == NO_RELEVANT_CONTEXT_FOUND
          reply EXACTLY the fallback message
   -> assistant answer saved with was_fallback flag; if fallback -> handoff row created
   -> { question, answer, sources_used, user_message_id, message_id } returned
```

Widget polling: while the chat panel is open, the widget calls `GET /chat/messages/{session_id}` every 15 s and renders assistant messages newer than its `last_seen` cursor — so a human admin reply to a handoff appears live to the visitor.

### 4.3 Human handoff (admin "Needs Attention")

```
Fallback answer detected -> create_or_update_handoff(session_id, question, agent_id)
   -> handoffs table row (status 'pending'); re-trunk timestamps if already pending
GET  /admin/handoffs                       -> pending handoffs (+ agent_name via join)
POST /admin/handoffs/{session_id}/reply    -> save human message as assistant row,
                                              resolve_handoff (status='resolved', resolved_at)
POST /admin/handoffs/{session_id}/resolve  -> dismiss (resolve without a reply)
```

### 4.4 Analytics (admin)

```
GET /admin/analytics?period=today|week|month|all  (default week)
   -> total_conversations   = COUNT(DISTINCT session_id) in period
   -> total_messages        = COUNT(*) in period
   -> fallback_rate         = % of assistant messages with was_fallback=1
   -> avg_messages_per_conversation
   -> top_questions         = normalized COUNT of user messages (top 5, phonetic normalization)
   -> conversations_per_day = last 7 days, filled with zeros
```

### 4.5 Agent management (admin)

```
POST   /agents             ->  create agent (name required, unique; system_prompt, greeting)
GET    /agents             ->  public list (id, name, greeting) — widget picker
GET    /agents/{id}        ->  full detail incl. system_prompt (admin only)
PUT    /agents/{id}        ->  edit agent (blank-name 400, duplicate-name 400)
DELETE /agents/{id}        ->  delete agent + its Qdrant points + its uploaded_files/agent_<id>/ folder
```

`init_db()` seeds the default **N2X Assistant** agent if the `agents` table is empty.

### 4.6 Auth (admin login)

```
POST /admin/login  ->  verify username/password vs env vars (hmac.compare_digest)
   -> generate 32-byte url-safe token
   -> store token in admin_sessions
   -> set httpOnly cookie "n2x_admin" (7-day max age, SameSite=lax)
Protected routes use Depends(require_admin). Logout deletes row + cookie.
```

---

## 5. API Endpoints

### Pages (no auth)
| Method | Path        | Description |
|--------|-------------|-------------|
| GET    | `/`          | Serves `static/index.html` (no-cache) |
| GET    | `/admin`     | Serves admin panel if authenticated, else redirect to `/login` |
| GET    | `/login`     | Serves login page, redirects to `/admin` if already authed |
| GET    | `/portfolio` | Streams `uploaded_files/N2X-System-Portfolio.pdf` as PDF (**404 currently — file not present**) |
| GET    | `/static/*`  | Static files mount |

### Chat
| Method | Path                     | Auth | Description |
|--------|--------------------------|------|-------------|
| POST | `/chat`                    | None | Body `{question, session_id?, agent_id?}` → `{question, answer, sources_used, user_message_id, message_id}` |
| GET  | `/chat/messages/{session_id}` | None | All messages for a session (polled by widget for human replies) |

### Agents
| Method | Path            | Auth (cookie) | Description |
|--------|-----------------|---------------|-------------|
| GET    | `/agents`         | public | List `{id, name, greeting}` (widget picker) |
| POST   | `/agents`         | required | Body `{name, system_prompt, greeting}` → creates agent (400 if name blank/duplicate) |
| GET    | `/agents/{id}`    | required | Full agent detail incl. `system_prompt` |
| PUT    | `/agents/{id}`    | required | Body `{name, system_prompt, greeting}` → updates agent, returns updated row |
| DELETE | `/agents/{id}`    | required | Deletes agent + its Qdrant points + its file folder |

### Admin / Auth / Documents / Handoffs / Analytics / Keys
| Method | Path                              | Auth (cookie) | Description |
|--------|-----------------------------------|---------------|-------------|
| POST   | `/admin/login`                      | – | Body `{username, password}` → sets cookie; 401 on bad creds |
| POST   | `/admin/logout`                     | – | Destroys session row + clears cookie |
| GET    | `/admin/check`                      | – | `{authenticated: bool}` |
| POST   | `/upload`                           | required | Multipart file (PDF/TXT) + optional `agent_id` → embeds into vector DB |
| GET    | `/documents`                        | required | List `{filename, size}`; optional `?agent_id=` scopes the list |
| DELETE | `/documents/{filename}`             | required | Delete file + its Qdrant points; optional `?agent_id=` |
| GET    | `/conversations`                    | required | All messages ordered by id |
| GET    | `/admin/handoffs`                   | required | Pending handoffs with `agent_name` |
| POST   | `/admin/handoffs/{session_id}/reply`| required | Body `{message}` → saves human assistant message + resolves handoff |
| POST   | `/admin/handoffs/{session_id}/resolve` | required | Dismiss handoff (resolve without reply); 404 if none pending |
| GET    | `/admin/analytics`                  | required | `?period=today\|week\|month\|all` → analytics aggregate |
| POST   | `/api-keys`                         | required | Body `{label}` → returns new API key |
| GET    | `/api-keys`                         | required | List API keys |
| DELETE | `/api-keys/{id}`                    | required | Delete API key |

**Note (unchanged):** There is still **no endpoint that validates API keys** on `/chat`. Keys are created/stored/listed/deleted but never checked — intended for future programmatic access.

---

## 6. Database Schema (SQLite `chatbot.db`)

Created/migrated by `init_db()` on startup.

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    was_fallback INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    system_prompt TEXT NOT NULL,
    greeting TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER,
    question TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'pending',
    resolved_at TEXT
);
```

Migration note: `messages.was_fallback` is added via `_ensure_column` (`ALTER TABLE` if missing), so pre-existing databases are upgraded automatically.

**Current DB state (runtime):** tables `messages, api_keys, admin_sessions, agents, handoffs`; agents = **N2X Assistant** (id 1), **Sales Assistant** (id 4); 14 handoff rows; 341 messages.

---

## 7. Configuration (`.env`)

| Variable         | Description                          | Default if missing |
|------------------|--------------------------------------|--------------------|
| `GROQ_API_KEY`   | API key for Groq LLM                 | (none — app fails at import) |
| `QDRANT_URL`     | Qdrant cloud URL                     | (none)             |
| `QDRANT_API_KEY` | Qdrant cloud API key                 | (none)             |
| `ADMIN_USERNAME` | Admin login username                 | `admin`            |
| `ADMIN_PASSWORD` | Admin login password                 | `change_this_password` |

(Identical to old report — `.env` file still contains exactly these 5 keys.)

---

## 8. Source Code (verbatim)

### 8.1 `requirements.txt`
```
fastapi==0.115.0
uvicorn==0.32.0
python-multipart==0.0.12
pypdf==5.1.0
sentence-transformers==3.2.1
qdrant-client==1.12.0
groq==0.11.0
python-dotenv==1.0.1
pydantic==2.9.2
```

### 8.2 `.start.bat`
```bat
@echo off
cd /d D:\N2X\knowledge-chatbot
call venv\Scripts\activate
start http://127.0.0.1:8000
uvicorn app.main:app --reload
```

### 8.3 `app/config.py`
```python
from dotenv import load_dotenv
import os

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change_this_password")
```

### 8.4 `app/db.py`
```python
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


def get_pending_handoffs() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT h.id, h.session_id, h.question, h.created_at,
                   a.name AS agent_name
            FROM handoffs h
            LEFT JOIN agents a ON a.id = h.agent_id
            WHERE h.status = 'pending'
            ORDER BY h.id DESC
            """
        ).fetchall()
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
```

### 8.5 `app/main.py`
```python
import os
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from app.db import init_db
from app.routes import upload, chat, admin
from app.services.auth import COOKIE_NAME, is_authenticated

PORTFOLIO_PATH = "uploaded_files/N2X-System-Portfolio.pdf"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

init_db()

app = FastAPI(title="Knowledge Base Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(chat.router)
app.include_router(admin.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


def _no_cache_file(path: str):
    return FileResponse(path, headers={
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
    })


@app.get("/")
def root():
    return _no_cache_file("static/index.html")


@app.get("/admin")
def admin_page(request: Request):
    if not is_authenticated(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse(url="/login", status_code=302)
    return _no_cache_file("static/admin.html")


@app.get("/login")
def login_page(request: Request):
    if is_authenticated(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse(url="/admin", status_code=302)
    return _no_cache_file("static/login.html")


@app.get("/portfolio")
def portfolio():
    if not os.path.isfile(PORTFOLIO_PATH):
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return FileResponse(
        PORTFOLIO_PATH,
        media_type="application/pdf",
        filename="N2X-System-Portfolio.pdf",
        headers={"Cache-Control": "no-store"},
    )
```

### 8.6 `app/models/schemas.py`
```python
from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    agent_id: int | None = None


class ApiKeyCreate(BaseModel):
    label: str


class AgentCreate(BaseModel):
    name: str
    system_prompt: str
    greeting: str = ""


class AgentUpdate(BaseModel):
    name: str
    system_prompt: str
    greeting: str = ""


class HandoffReply(BaseModel):
    message: str
```

### 8.7 `app/routes/chat.py`
```python
import re
import logging
import traceback

from fastapi import APIRouter

from app.models.schemas import ChatRequest
from app.services.embeddings import generate_embedding
from app.services.vector_store import search_similar_chunks
from app.services.llm import generate_answer
from app.db import (
    save_message,
    get_agent,
    get_session_messages,
    create_or_update_handoff,
    DEFAULT_SYSTEM_PROMPT,
    FALLBACK_MESSAGE,
    NO_RELEVANT_CONTEXT_FOUND,
)

router = APIRouter()
logger = logging.getLogger(__name__)

RETRIEVAL_UNAVAILABLE_MESSAGE = (
    "Hamari knowledge service filhal available nahi hai. "
    "Aap N2X System se info@n2xsystem.com ya +92 323 452 9766 par rabta kar sakte hain."
)


def _casual_response(question: str) -> str | None:
    """Keep lightweight conversation working when the knowledge service is down."""
    normalized = re.sub(r"[^a-z0-9\s]", "", question.lower()).strip()
    words = set(normalized.split())
    greeting_words = {
        "hi", "hello", "hey", "salam", "aoa", "assalamualaikum", "good", "morning",
        "evening", "there", "bro", "yaar",
    }

    if words and words <= {"thanks", "thank", "you", "so", "much", "shukriya", "jazakallah"}:
        return "Khushi hui! Aap ko N2X System ke bare mein koi bhi sawal ho to pooch sakte hain."
    if words and words <= {"bye", "goodbye", "allahhafiz", "khudahafiz", "ok", "okay"}:
        return "Allah Hafiz! Jab bhi zaroorat ho, hum yahan hain."
    if words and words <= greeting_words or normalized in {"kya haal hai", "how are you", "whats up"}:
        if normalized in {"hi", "hello", "hey", "good morning", "good evening"}:
            return "Hello! How can I help you with N2X System today?"
        return "Hi! Main theek hoon. N2X System ke bare mein aap ko kis cheez mein madad chahiye?"
    return None


def _generate_answer_or_fallback(question: str, context: str, fallback: str) -> str:
    try:
        return generate_answer(question, context)
    except Exception as exc:
        logger.exception("LLM request failed")
        logger.error("LLM request failed -> %s: %s", type(exc).__name__, exc)
        traceback.print_exc()
        return fallback


@router.post("/chat")
async def chat(request: ChatRequest):
    # Ids of the rows this request inserts. The widget needs the assistant
    # message id to advance its "last seen" cursor past its own answer;
    # without it a stale cursor makes polling re-render old messages.
    user_message_id: int | None = None
    if request.session_id:
        user_message_id = save_message(request.session_id, "user", request.question)

    def _reply(answer: str, sources_used: int = 0, was_fallback: int = 0):
        message_id: int | None = None
        if request.session_id:
            message_id = save_message(
                request.session_id, "assistant", answer, was_fallback=was_fallback
            )
            if was_fallback:
                create_or_update_handoff(request.session_id, request.question, request.agent_id)
        return {
            "question": request.question,
            "answer": answer,
            "sources_used": sources_used,
            "user_message_id": user_message_id,
            "message_id": message_id,
        }

    casual_answer = _casual_response(request.question)
    if casual_answer is not None:
        return _reply(casual_answer)

    # 1. Embed the question
    try:
        query_embedding = generate_embedding(request.question)
    except Exception as exc:
        logger.exception("Embedding generation failed")
        logger.error("Embedding generation failed -> %s: %s", type(exc).__name__, exc)
        return _reply(RETRIEVAL_UNAVAILABLE_MESSAGE)

    # 2. Search Qdrant for relevant chunks (agent-specific + shared)
    relevant_chunks, retrieval_available = search_similar_chunks(
        query_embedding,
        top_k=3,
        agent_id=request.agent_id,
        query_text=request.question,
    )

    if not retrieval_available:
        return _reply(RETRIEVAL_UNAVAILABLE_MESSAGE)

    # 3. Combine only retrieved chunks into the context.
    relevant_chunks = list(relevant_chunks)

    sources_used = 0
    if relevant_chunks:
        context = "\n\n".join(relevant_chunks)
        sources_used = len(relevant_chunks)
    else:
        context = NO_RELEVANT_CONTEXT_FOUND

    # 4. Use the selected agent's system prompt (if any), else the default
    system_prompt = DEFAULT_SYSTEM_PROMPT
    if request.agent_id is not None:
        agent = get_agent(request.agent_id)
        if agent:
            system_prompt = agent["system_prompt"]

    # 5. Ask LLM
    answer = _generate_answer_or_fallback(
        request.question, context, RETRIEVAL_UNAVAILABLE_MESSAGE
    )

    was_fallback = 1 if answer == FALLBACK_MESSAGE else 0
    return _reply(answer, sources_used=sources_used, was_fallback=was_fallback)


@router.get("/chat/messages/{session_id}")
async def session_messages(session_id: str):
    """Lightweight public endpoint the widget polls to pick up new
    (e.g. human-agent) assistant messages for its own session."""
    return get_session_messages(session_id)
```

### 8.8 `app/routes/upload.py`
```python
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
import shutil
import os

from app.services.pdf_processor import extract_text_from_pdf, chunk_text
from app.services.embeddings import generate_embeddings_batch
from app.services.auth import require_admin
from app.services.vector_store import create_collection_if_not_exists, delete_points_by_filename, store_chunks

router = APIRouter()
UPLOAD_DIR = "uploaded_files"
ALLOWED_EXTENSIONS = (".pdf", ".txt")


def agent_upload_dir(agent_id: int) -> str:
    return os.path.join(UPLOAD_DIR, f"agent_{agent_id}")


@router.post("/upload", dependencies=[Depends(require_admin)])
async def upload_pdf(file: UploadFile = File(...), agent_id: int | None = Form(None)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and TXT files are allowed")

    upload_dir = agent_upload_dir(agent_id) if agent_id is not None else UPLOAD_DIR
    if agent_id is not None:
        os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Extract text
    text = extract_text(file_path, ext)

    # Chunk it
    chunks = [c for c in chunk_text(text) if c.strip()]

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No text could be extracted from this file. The PDF may be scanned/image-only. Upload the content as a .txt file instead."
        )

    # Generate embeddings
    embeddings = generate_embeddings_batch(chunks)

    # Store in Qdrant, replacing any previously stored points for this file
    create_collection_if_not_exists()
    delete_points_by_filename(file.filename, agent_id)
    store_chunks(chunks, embeddings, file.filename, agent_id)

    return {
        "filename": file.filename,
        "message": "File uploaded and processed successfully",
        "chunks_created": len(chunks)
    }


def extract_text(file_path: str, ext: str) -> str:
    if ext == ".txt":
        with open(file_path, "rb") as f:
            raw = f.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")
    return extract_text_from_pdf(file_path)
```

### 8.9 `app/routes/admin.py`
```python
import os
import shutil
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.db import (
    get_conversations,
    save_message,
    get_total_conversations,
    get_total_messages,
    get_fallback_rate,
    get_avg_messages_per_conversation,
    get_top_questions,
    get_conversations_per_day,
    create_api_key,
    list_api_keys,
    delete_api_key,
    create_agent,
    get_agent,
    list_agents,
    update_agent,
    delete_agent,
    get_pending_handoffs,
    resolve_handoff,
)
from app.models.schemas import ApiKeyCreate, AgentCreate, AgentUpdate, HandoffReply
from app.services.auth import (
    COOKIE_NAME,
    create_session,
    destroy_session,
    is_authenticated,
    require_admin,
)
from app.services.vector_store import delete_points_by_filename, delete_points_by_agent
from app.routes.upload import agent_upload_dir

router = APIRouter()
UPLOAD_DIR = "uploaded_files"
ALLOWED_EXTENSIONS = (".pdf", ".txt")


class LoginRequest(BaseModel):
    username: str
    password: str


def _safe_filename(filename: str) -> bool:
    if os.path.basename(filename) != filename:
        return False
    return filename.lower().endswith(ALLOWED_EXTENSIONS)


@router.post("/admin/login")
def login(req: LoginRequest, response: Response):
    token = create_session(req.username, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="lax",
    )
    return {"message": "Login successful"}


@router.post("/admin/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        destroy_session(token)
    response.delete_cookie(key=COOKIE_NAME)
    return {"message": "Logged out"}


@router.get("/admin/check")
def check_auth(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    return {"authenticated": is_authenticated(token)}


@router.get("/documents", dependencies=[Depends(require_admin)])
def list_documents(agent_id: int | None = None):
    base_dir = agent_upload_dir(agent_id) if agent_id is not None else UPLOAD_DIR
    if not os.path.isdir(base_dir):
        return []
    files = []
    for name in os.listdir(base_dir):
        path = os.path.join(base_dir, name)
        if os.path.isfile(path) and name.lower().endswith(ALLOWED_EXTENSIONS):
            files.append({"filename": name, "size": os.path.getsize(path)})
    return files


@router.delete("/documents/{filename}", dependencies=[Depends(require_admin)])
def delete_document(filename: str, agent_id: int | None = None):
    if not _safe_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    base_dir = agent_upload_dir(agent_id) if agent_id is not None else UPLOAD_DIR
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        os.remove(path)

    delete_points_by_filename(filename, agent_id)
    return {"filename": filename, "message": "Document deleted"}


@router.get("/conversations", dependencies=[Depends(require_admin)])
def conversations():
    return get_conversations()


@router.get("/admin/handoffs", dependencies=[Depends(require_admin)])
def handoffs():
    return get_pending_handoffs()


@router.post("/admin/handoffs/{session_id}/reply", dependencies=[Depends(require_admin)])
def reply_to_handoff(session_id: str, req: HandoffReply):
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    save_message(session_id, "assistant", message, was_fallback=0)
    resolve_handoff(session_id)
    return {"message": "Reply sent"}


@router.post("/admin/handoffs/{session_id}/resolve", dependencies=[Depends(require_admin)])
def resolve_existing_handoff(session_id: str):
    if not resolve_handoff(session_id):
        raise HTTPException(status_code=404, detail="Pending handoff not found")
    return {"message": "Handoff resolved"}


@router.get("/admin/analytics", dependencies=[Depends(require_admin)])
def analytics(period: str = "week"):
    if period not in ("today", "week", "month", "all"):
        period = "week"
    return {
        "total_conversations": get_total_conversations(period),
        "total_messages": get_total_messages(period),
        "fallback_rate": get_fallback_rate(period),
        "avg_messages_per_conversation": get_avg_messages_per_conversation(period),
        "top_questions": get_top_questions(5),
        "conversations_per_day": get_conversations_per_day(7),
    }


@router.post("/api-keys", dependencies=[Depends(require_admin)])
def create_key(req: ApiKeyCreate):
    api_key = create_api_key(req.label)
    return {"api_key": api_key, "label": req.label, "message": "API key created"}


@router.get("/api-keys", dependencies=[Depends(require_admin)])
def list_keys():
    return list_api_keys()


@router.delete("/api-keys/{key_id}", dependencies=[Depends(require_admin)])
def delete_key(key_id: int):
    if not delete_api_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"message": "API key deleted"}


@router.get("/agents")
def get_public_agents():
    return [{"id": a["id"], "name": a["name"], "greeting": a["greeting"]} for a in list_agents()]


@router.post("/agents", dependencies=[Depends(require_admin)])
def create_new_agent(req: AgentCreate):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Agent name is required")
    try:
        return create_agent(req.name.strip(), req.system_prompt, req.greeting)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="An agent with this name already exists")


@router.get("/agents/{agent_id}", dependencies=[Depends(require_admin)])
def get_agent_detail(agent_id: int):
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/agents/{agent_id}", dependencies=[Depends(require_admin)])
def update_existing_agent(agent_id: int, req: AgentUpdate):
    if not get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Agent name is required")
    try:
        ok = update_agent(agent_id, req.name.strip(), req.system_prompt, req.greeting)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="An agent with this name already exists")
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return get_agent(agent_id)


@router.delete("/agents/{agent_id}", dependencies=[Depends(require_admin)])
def delete_existing_agent(agent_id: int):
    if not get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    delete_points_by_agent(agent_id)
    shutil.rmtree(agent_upload_dir(agent_id), ignore_errors=True)
    delete_agent(agent_id)
    return {"message": "Agent deleted"}
```

### 8.10 `app/services/auth.py`
```python
import hmac
import secrets

from fastapi import HTTPException, Request

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME
from app.db import (
    admin_session_exists,
    create_admin_session,
    delete_admin_session,
)

COOKIE_NAME = "n2x_admin"


def verify_credentials(username: str, password: str) -> bool:
    user_ok = hmac.compare_digest(username, ADMIN_USERNAME)
    pass_ok = hmac.compare_digest(password, ADMIN_PASSWORD)
    return user_ok and pass_ok


def create_session(username: str, password: str) -> str | None:
    if not verify_credentials(username, password):
        return None
    token = secrets.token_urlsafe(32)
    create_admin_session(token)
    return token


def destroy_session(token: str) -> None:
    delete_admin_session(token)


def is_authenticated(token: str | None) -> bool:
    return bool(token) and admin_session_exists(token)


def require_admin(request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not is_authenticated(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
```

### 8.11 `app/services/embeddings.py`
```python
from sentence_transformers import SentenceTransformer

model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global model
    if model is None:
        model = SentenceTransformer("all-MiniLM-L6-v2")
    return model

def generate_embedding(text: str) -> list[float]:
    embedding = _get_model().encode(text)
    return embedding.tolist()

def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    embeddings = _get_model().encode(texts)
    return embeddings.tolist()
```

### 8.12 `app/services/llm.py`
```python
import time
import logging
from groq import Groq, RateLimitError, APIConnectionError, APITimeoutError
from app.config import GROQ_API_KEY
from app.db import DEFAULT_SYSTEM_PROMPT, FALLBACK_MESSAGE, NO_RELEVANT_CONTEXT_FOUND

client = Groq(api_key=GROQ_API_KEY)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def _is_daily_limit(exc: RateLimitError) -> bool:
    """Daily (TPD) quota exhaustion cannot be fixed by short backoff, so retries
    are pointless. Per-minute (TPM) limits reset in seconds and are retryable."""
    return "tokens per day" in str(exc)


def _create_completion(prompt: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model="groq/compound-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=250,
            )
            return response.choices[0].message.content
        except RateLimitError as exc:
            last_error = exc
            if _is_daily_limit(exc):
                logger.error(
                    "Groq daily token quota exhausted (no retry): %s", exc
                )
                raise exc
            delay = attempt * 5.0
            logger.warning(
                "LLM rate limited (attempt %d/%d): %s. Retrying in %.1fs",
                attempt,
                MAX_RETRIES,
                exc,
                delay,
            )
            time.sleep(delay)
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = exc
            delay = attempt * 5.0
            logger.warning(
                "LLM request failed (attempt %d/%d): %s. Retrying in %.1fs",
                attempt,
                MAX_RETRIES,
                exc,
                delay,
            )
            time.sleep(delay)
    raise last_error

BEHAVIOR_RULES = f"""
UNIVERSAL RULES (apply on top of any persona above):

STEP 1 - CLASSIFY the user's message into one of two types:
  - TYPE A (CASUAL / SMALL TALK): greetings ("hi", "hello", "salam", "hey", "yo", "good morning"),
    how-are-you questions ("kya haal hai", "kaise ho", "what's up"), thanks, farewells, or any
    non-informational remark.
  - TYPE B (FACTUAL QUESTION): a genuine request for information about N2X System (services, projects,
    pricing, portfolio, contact details, technologies, capabilities, etc.).

STEP 2 - RESPOND according to the type:
  - TYPE A (CASUAL): reply naturally, warmly and conversationally in the user's language, keeping your
    persona/tone. You do NOT need the Context below for these. NEVER use the fallback message here.
  - TYPE B (FACTUAL): answer ONLY from the Context below. You MUST NOT use outside knowledge, general
    knowledge, or anything learned during training for any factual claim. If the Context is exactly
    "{NO_RELEVANT_CONTEXT_FOUND}", it means no relevant information was found in the knowledge base;
    in that case reply with EXACTLY this message and nothing else:
{FALLBACK_MESSAGE}
Do NOT guess, and do NOT answer a factual question from memory when the Context has no relevant information.

Keep answers short and to the point (2-4 sentences max).
"""


def generate_answer(question: str, context: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    prompt = f"""{system_prompt}

{BEHAVIOR_RULES}

Context:
{context}

Question: {question}

Answer:"""

    response = _create_completion(prompt)

    return response
```

### 8.13 `app/services/pdf_processor.py`
```python
from pypdf import PdfReader
import re

def extract_text_from_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 0) -> list[str]:
    """Split knowledge documents at headings instead of fixed character offsets.

    A section such as ``SERVICES`` or ``Project 3: ...`` remains a single
    semantic chunk whenever it fits in ``chunk_size``.  Very large sections
    are only split at paragraph boundaries, never in the middle of a word or
    list item. ``overlap`` is retained for backwards-compatible callers but
    is intentionally unused: overlapping sections create duplicate search
    hits and less useful retrieval context.
    """
    del overlap
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    uppercase_heading_pattern = re.compile(r"^[A-Z][A-Z0-9/& -]{2,}$")
    project_heading_pattern = re.compile(r"^Project\s+\d+\s*:", re.IGNORECASE)
    sections: list[str] = []
    current: list[str] = []

    for line in normalized.split("\n"):
        # A top-level all-caps heading or Project N starts a distinct section.
        stripped_line = line.strip()
        is_heading = bool(
            uppercase_heading_pattern.match(stripped_line)
            or project_heading_pattern.match(stripped_line)
        )
        # Keep document titles with the first section, and keep container
        # headings (for example, ``PROJECTS``) with their first child.
        has_section_body = len([existing for existing in current if existing.strip()]) > 1
        if is_heading and has_section_body:
            section = "\n".join(current).strip()
            if section:
                sections.append(section)
            current = []
        current.append(line)

    if current:
        sections.append("\n".join(current).strip())

    chunks: list[str] = []
    for section in sections:
        if len(section) <= chunk_size:
            chunks.append(section)
            continue

        # Prefer paragraph boundaries for unusually long prose sections.
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", section) if paragraph.strip()]
        pending = ""
        for paragraph in paragraphs:
            candidate = f"{pending}\n\n{paragraph}".strip() if pending else paragraph
            if pending and len(candidate) > chunk_size:
                chunks.append(pending)
                pending = paragraph
            else:
                pending = candidate
        if pending:
            chunks.append(pending)

    return chunks
```

### 8.14 `app/services/vector_store.py`
```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition,
    MatchValue, FilterSelector, PayloadSchemaType, IsEmptyCondition, PayloadField,
)
import uuid
import logging
import re
from app.config import QDRANT_URL, QDRANT_API_KEY
 
client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
logger = logging.getLogger(__name__)

COLLECTION_NAME = "knowledge_base"

def create_collection_if_not_exists():
    collections = client.get_collections().collections
    collection_names = [c.name for c in collections]

    if COLLECTION_NAME not in collection_names:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE)
        )

    ensure_filename_index()
    ensure_agent_index()

def ensure_filename_index():
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="filename",
        field_schema=PayloadSchemaType.KEYWORD,
    )

def ensure_agent_index():
    try:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="agent_id",
            field_schema=PayloadSchemaType.INTEGER,
        )
    except Exception:
        pass

def store_chunks(chunks: list[str], embeddings: list[list[float]], filename: str, agent_id: int | None = None):
    points = []
    for chunk, embedding in zip(chunks, embeddings):
        payload = {"text": chunk, "filename": filename}
        if agent_id is not None:
            payload["agent_id"] = agent_id
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload=payload
        )
        points.append(point)

    client.upsert(collection_name=COLLECTION_NAME, points=points)

def _agent_conditions(filename: str, agent_id: int | None) -> list:
    conditions = [FieldCondition(key="filename", match=MatchValue(value=filename))]
    if agent_id is not None:
        conditions.append(FieldCondition(key="agent_id", match=MatchValue(value=agent_id)))
    else:
        # Points stored without an agent_id payload key. `is_empty` matches
        # both missing and null values; `is_null` does NOT match missing keys.
        conditions.append(IsEmptyCondition(is_empty=PayloadField(key="agent_id")))
    return conditions

def delete_points_by_filename(filename: str, agent_id: int | None = None):
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(
                must=_agent_conditions(filename, agent_id)
            )
        ),
    )

def delete_points_by_agent(agent_id: int):
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(key="agent_id", match=MatchValue(value=agent_id))]
            )
        ),
    )

def search_similar_chunks(query_embedding: list[float], top_k: int = 3, agent_id: int | None = None, score_threshold: float = 0.15, query_text: str | None = None) -> tuple[list[str], bool]:
    """Return matching chunks and whether Qdrant was reachable.

    The embedding model is English-only, so Roman Urdu queries score poorly
    against English sections. ``query_text`` enables a lightweight heading
    keyword boost: if the query contains a word that exactly matches a chunk's
    heading (first line), that chunk is prepended even when its vector score
    is low.
    """
    query_filter = None
    if agent_id is not None:
        query_filter = Filter(
            should=[
                IsEmptyCondition(is_empty=PayloadField(key="agent_id")),
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
            ]
        )
    else:
        # Shared (non-agent) chats should only see shared knowledge chunks.
        query_filter = Filter(
            must=[IsEmptyCondition(is_empty=PayloadField(key="agent_id"))]
        )
    try:
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=query_filter,
            score_threshold=score_threshold,
        )
    except Exception:
        logger.exception("Qdrant search failed; knowledge retrieval is unavailable")
        return [], False

    chunks = [result.payload["text"] for result in results]

    if query_text:
        heading_match = _heading_keyword_match(query_text, query_filter)
        if heading_match and heading_match not in chunks:
            chunks.insert(0, heading_match)
            chunks = chunks[: top_k + 1]

    return chunks, True


def _heading_keyword_match(query_text: str, query_filter: Filter | None) -> str | None:
    """Return the first chunk whose heading or leading content matches a
    significant query word.

    A "significant" word is 3+ alphanumeric characters; the match is
    case-insensitive against the chunk's heading and first few content lines
    (headings only were too strict for facts like ``20+ Clients`` that live in
    the body of a section).
    """
    tokens = {
        token
        for token in re.findall(r"[a-zA-Z0-9]+", query_text.lower())
        if len(token) >= 3
    }
    if not tokens:
        return None
    try:
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=1000,
            with_payload=True,
        )
        for point in result[0]:
            text = (point.payload or {}).get("text", "")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            haystack = "\n".join(lines[:6]).lower()
            if haystack and any(token in haystack for token in tokens):
                return text
    except Exception:
        logger.exception("Heading keyword scan failed")
        return None
    return None
```

### 8.15 `scripts/reindex_n2x_knowledge.py`
```python
"""Re-index the N2X knowledge document(s) with section-aware chunks.

Re-indexes both the shared copy (agent_id=None) and any agent-scoped copy
found under ``uploaded_files/agent_<id>/``.

Run from the repository root:
    .\venv\Scripts\python.exe scripts\reindex_n2x_knowledge.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.embeddings import generate_embeddings_batch
from app.services.pdf_processor import chunk_text
from app.services.vector_store import (
    create_collection_if_not_exists,
    delete_points_by_filename,
    store_chunks,
)


def _reindex(path: Path, agent_id: int | None) -> None:
    text = path.read_text(encoding="utf-8")
    chunks = chunk_text(text)
    scope = f"agent_id={agent_id}" if agent_id is not None else "shared"
    print(f"Re-indexing {path.name} ({scope}): {len(chunks)} section-aware chunks")
    for index, chunk in enumerate(chunks, start=1):
        print(f"\n--- chunk {index} ({len(chunk)} characters) ---\n{chunk}")

    embeddings = generate_embeddings_batch(chunks)
    create_collection_if_not_exists()
    delete_points_by_filename(path.name, agent_id)
    store_chunks(chunks, embeddings, path.name, agent_id)
    print(f"\nRe-index complete for {path.name} ({scope}).")


def main() -> None:
    shared = Path("uploaded_files/n2x_knowledge.txt")
    if shared.exists():
        _reindex(shared, None)

    for agent_dir in Path("uploaded_files").glob("agent_*/"):
        agent_id = int(agent_dir.name.split("_", 1)[1])
        for path in agent_dir.glob("n2x_knowledge.txt"):
            _reindex(path, agent_id)


if __name__ == "__main__":
    main()
```

### 8.16 `scripts/qdrant_knowledge_base.py`
```python
"""Inspect or explicitly wipe the Qdrant knowledge_base collection.

Run from the repository root:
    .\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py
    .\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py --full-text
    .\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py --wipe --confirm-wipe
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FilterSelector

from app.config import QDRANT_API_KEY, QDRANT_URL

COLLECTION_NAME = "knowledge_base"


def get_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


def inventory(client: QdrantClient, full_text: bool) -> int:
    offset = None
    filenames: Counter[str] = Counter()
    total = 0

    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            filename = str(payload.get("filename", "<missing filename>"))
            text = str(payload.get("text", ""))
            filenames[filename] += 1
            total += 1
            snippet = text if full_text else text.replace("\n", " ")[:240]
            print(f"id={point.id} | filename={filename} | text={snippet}")

        if offset is None:
            break

    print("\nFilename inventory:")
    if not filenames:
        print("  (collection is empty)")
    for filename, count in sorted(filenames.items()):
        print(f"  {filename}: {count} chunks")
    print(f"\nTotal points: {total}")
    return total


def wipe(client: QdrantClient) -> None:
    # An empty filter matches every point while retaining the collection schema.
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(filter=Filter(must=[])),
        wait=True,
    )
    remaining = client.count(collection_name=COLLECTION_NAME, exact=True).count
    print(f"Collection wipe complete. Remaining points: {remaining}")
    if remaining != 0:
        raise RuntimeError("Wipe did not remove every point")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or wipe the Qdrant knowledge_base collection.")
    parser.add_argument("--full-text", action="store_true", help="Print full chunk text instead of snippets.")
    parser.add_argument("--wipe", action="store_true", help="Delete every point in knowledge_base.")
    parser.add_argument(
        "--confirm-wipe",
        action="store_true",
        help="Required together with --wipe to prevent accidental deletion.",
    )
    args = parser.parse_args()

    if args.wipe and not args.confirm_wipe:
        parser.error("--wipe requires --confirm-wipe")
    if args.confirm_wipe and not args.wipe:
        parser.error("--confirm-wipe must be used with --wipe")

    try:
        client = get_client()
        if args.wipe:
            wipe(client)
        else:
            inventory(client, args.full_text)
    except Exception as exc:
        print(f"Qdrant operation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
```

### 8.17 `scripts/debug_retrieval.py`
```python
"""Print raw Qdrant retrieval results for the N2X knowledge-base queries.

Run from the repository root:
    .\venv\Scripts\python.exe scripts\debug_retrieval.py

This intentionally does *not* set ``score_threshold``. It is a temporary
diagnostic for seeing which chunks Qdrant would otherwise return.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Avoid an unnecessary Hugging Face metadata check when the model is already
# cached locally. This affects only the diagnostic process.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.services.embeddings import generate_embedding
from app.services.vector_store import COLLECTION_NAME, client


QUERIES = (
    "Aap ki services kya hain?",
    "Hospital Management System mein kya features hain?",
    "N2X kitne saal se kaam kar raha hai?",
)


def main() -> None:
    for query in QUERIES:
        print(f"\n{'=' * 80}\nQUERY: {query}\n{'=' * 80}")
        query_embedding = generate_embedding(query)
        print(f"Embedding dimensions: {len(query_embedding)}")

        # Deliberately omit score_threshold to inspect the raw top 10.
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            limit=10,
            with_payload=True,
        )
        for index, result in enumerate(results, start=1):
            payload = result.payload or {}
            print(f"\n#{index} score={result.score:.6f} filename={payload.get('filename', '<missing>')}")
            print("--- chunk text ---")
            print(payload.get("text", "<missing text>"))
            print("--- end chunk text ---")


if __name__ == "__main__":
    main()
```

### 8.18 `static/widget.js` (chat widget, verbatim)
```javascript
(function () {
  "use strict";

  var CONFIG = window.N2XChatConfig || {};
  var API_BASE = CONFIG.apiBase || "";

  var sessionId = localStorage.getItem("n2x_session_id");
  if (!sessionId) {
    sessionId = "session-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
    localStorage.setItem("n2x_session_id", sessionId);
  }

  var STYLE_ID = "n2x-widget-style";
  var root = document.createElement("div");
  root.id = "n2x-widget";
  root.innerHTML = "";

  function mount() {
    document.body.appendChild(root);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  var style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent =
    "#n2x-widget * { box-sizing: border-box; margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; }" +
    "#n2x-widget { position: fixed; right: 24px; bottom: 24px; z-index: 999999; font-size: 14px; }" +
    "#n2x-launcher { width: 60px; height: 60px; border-radius: 50%; border: none; cursor: pointer; background: #00C2B8; color: #fff; box-shadow: 0 4px 16px rgba(0, 194, 184, 0.4); display: flex; align-items: center; justify-content: center; transition: transform 0.15s ease; }" +
    "#n2x-launcher:hover { transform: scale(1.08); }" +
    "#n2x-panel { position: fixed; right: 96px; bottom: 24px; width: 320px; max-width: calc(100vw - 104px); height: 360px; max-height: calc(100dvh - 84px); background: #fff; border-radius: 14px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25); display: flex; flex-direction: column; overflow: hidden; border: 1px solid #e5e7eb; }" +
    "#n2x-panel.hidden { display: none; }" +
    "#n2x-header { background: #00C2B8; color: #fff; padding: 14px 16px; display: flex; align-items: center; gap: 10px; }" +
    "#n2x-header .dot { width: 9px; height: 9px; border-radius: 50%; background: #34d399; flex-shrink: 0; }" +
    "#n2x-agent-select { flex: 1; background: transparent; color: #fff; border: none; font-size: 14px; font-weight: 600; outline: none; cursor: pointer; }" +
    "#n2x-agent-select option { color: #111; }" +
    "#n2x-close { background: none; border: none; color: #fff; font-size: 20px; cursor: pointer; line-height: 1; }" +
    "#n2x-messages { flex: 1; overflow-y: auto; padding: 16px; background: #f9fafb; display: flex; flex-direction: column; gap: 10px; }" +
    "#n2x-messages .msg { max-width: 80%; padding: 10px 12px; border-radius: 12px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }" +
    "#n2x-messages .msg.user { align-self: flex-end; background: #00C2B8; color: #fff; border-bottom-right-radius: 3px; }" +
    "#n2x-messages .msg.bot { align-self: flex-start; background: #fff; color: #111; border: 1px solid #e5e7eb; border-bottom-left-radius: 3px; }" +
    "#n2x-messages .msg.typing { color: #6b7280; font-style: italic; }" +
    "#n2x-input-row { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e5e7eb; background: #fff; }" +
    "#n2x-input { flex: 1; border: 1px solid #d1d5db; border-radius: 8px; padding: 10px 12px; font-size: 14px; outline: none; }" +
    "#n2x-input:focus { border-color: #00C2B8; }" +
    "#n2x-send { background: #00C2B8; color: #fff; border: none; border-radius: 8px; padding: 0 18px; font-size: 14px; font-weight: 600; cursor: pointer; }" +
    "#n2x-send:hover { background: #0d9488; }" +
    "@media (max-width: 480px) { #n2x-widget { right: 12px; bottom: 12px; } #n2x-panel { right: 84px; bottom: 12px; width: calc(100vw - 96px); height: 340px; max-height: calc(100dvh - 84px); } }";

  document.head.appendChild(style);

  root.innerHTML =
    '<button id="n2x-launcher" aria-label="Open chat">' +
    '  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '    <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>' +
    '  </svg>' +
    "</button>" +
    '<div id="n2x-panel" class="hidden">' +
    '  <div id="n2x-header">' +
    '    <span class="dot"></span>' +
    '    <select id="n2x-agent-select" title="Choose agent"></select>' +
    '    <button id="n2x-close" aria-label="Close chat">&times;</button>' +
    "  </div>" +
    '  <div id="n2x-messages"></div>' +
    '  <div id="n2x-input-row">' +
    '    <input id="n2x-input" type="text" placeholder="Apna sawal likho..." autocomplete="off" />' +
    '    <button id="n2x-send">Send</button>' +
    "  </div>" +
    "</div>";

  var launcher = root.querySelector("#n2x-launcher");
  var panel = root.querySelector("#n2x-panel");
  var messagesEl = root.querySelector("#n2x-messages");
  var inputEl = root.querySelector("#n2x-input");
  var sendBtn = root.querySelector("#n2x-send");
  var closeBtn = root.querySelector("#n2x-close");
  var agentSelect = root.querySelector("#n2x-agent-select");

  var agents = [];
  var currentAgentId = null;

  // --- Human handoff reply polling ---
  // The widget normally only shows messages from the live browser session.
  // When a human admin replies to a handoff from the admin panel, that reply
  // is saved server-side as an assistant message. While the chat panel is
  // open we poll a lightweight endpoint every 15s and render any assistant
  // messages newer than our last-seen id, so the user sees the human reply.
  var POLL_MS = 15000;
  var pollTimer = null;
  var pendingOwnRequest = 0;

  function lastSeenKey() {
    return "n2x_last_seen_" + sessionId;
  }

  // The cursor survives page reloads (persisted per session). Anything above
  // it is genuinely new for THIS visitor — e.g. a human reply that arrived
  // while the page was closed — and must not be silently marked as seen.
  var lastSeenMsgId = parseInt(localStorage.getItem(lastSeenKey()), 10) || 0;

  // Forward-only: never lets a stale/out-of-order response drag the cursor
  // backward (which would make polling re-render old messages as "new").
  function advanceCursor(id) {
    if (typeof id !== "number" || isNaN(id)) return;
    if (id > lastSeenMsgId) {
      lastSeenMsgId = id;
      try {
        localStorage.setItem(lastSeenKey(), String(id));
      } catch (e) {}
    }
  }

  async function fetchSessionMessages() {
    try {
      var res = await fetch(API_BASE + "/chat/messages/" + encodeURIComponent(sessionId));
      if (!res.ok) return [];
      return (await res.json()) || [];
    } catch (e) {
      return [];
    }
  }

  function renderNewMessages(msgs) {
    var maxId = lastSeenMsgId;
    msgs.forEach(function (m) {
      if (m.id > maxId) maxId = m.id;
      if (m.id > lastSeenMsgId && m.role === "assistant") addMessage(m.content, "bot");
    });
    advanceCursor(maxId);
  }

  async function pollMessages() {
    var msgs = await fetchSessionMessages();
    if (pendingOwnRequest > 0) {
      // Our own /chat answer arrives via the direct response, which carries
      // its exact message id — that alone advances the cursor. Do NOT touch
      // the cursor here: a human reply inserted while our request was in
      // flight must stay "new" so the next tick renders it.
      return;
    }
    renderNewMessages(msgs);
  }

  function startPolling() {
    if (pollTimer) return;
    pollMessages();
    pollTimer = setInterval(pollMessages, POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // First-ever visit for this browser (no stored cursor): adopt whatever
  // history already exists as "seen" so old rows are not replayed. The
  // zero-check at resolve time prevents a slow baseline fetch from marking
  // genuinely new messages (e.g. an early human reply) as seen.
  if (!lastSeenMsgId) {
    fetchSessionMessages().then(function (msgs) {
      if (msgs.length && lastSeenMsgId === 0) {
        advanceCursor(msgs[msgs.length - 1].id);
      }
    });
  }

  function selectAgent(agent) {
    currentAgentId = agent.id;
    localStorage.setItem("n2x_agent_id", String(agent.id));
    messagesEl.innerHTML = '<div class="msg bot">' + (agent.greeting || "Hello!") + "</div>";
  }

  async function loadAgents() {
    try {
      var res = await fetch(API_BASE + "/agents");
      agents = (await res.json()) || [];
    } catch (e) {
      agents = [];
    }
    agents.forEach(function (a) {
      var opt = document.createElement("option");
      opt.value = a.id;
      opt.textContent = a.name;
      agentSelect.appendChild(opt);
    });
    if (!agents.length) return;

    var saved = localStorage.getItem("n2x_agent_id");
    var savedId = saved ? parseInt(saved, 10) : null;
    var target = agents.filter(function (a) { return a.id === savedId; })[0] || agents[0];
    agentSelect.value = target.id;
    selectAgent(target);
  }

  agentSelect.addEventListener("change", function () {
    var target = agents.filter(function (a) { return a.id === parseInt(agentSelect.value, 10); })[0];
    if (target) selectAgent(target);
  });

  loadAgents();

  function openPanel() {
    panel.classList.remove("hidden");
    inputEl.focus();
    messagesEl.scrollTop = messagesEl.scrollHeight;
    startPolling();
  }

  function closePanel() {
    panel.classList.add("hidden");
    stopPolling();
  }

  launcher.addEventListener("click", openPanel);
  closeBtn.addEventListener("click", closePanel);

  function addMessage(text, sender) {
    var el = document.createElement("div");
    el.className = "msg " + sender;
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  async function sendQuestion() {
    var question = inputEl.value.trim();
    if (!question) return;

    inputEl.value = "";
    addMessage(question, "user");

    var typingEl = addMessage("Soch raha hoon...", "bot typing");

    pendingOwnRequest++;
    var data = null;
    try {
      var res = await fetch(API_BASE + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, session_id: sessionId, agent_id: currentAgentId }),
      });
      data = await res.json();
      typingEl.classList.remove("typing");
      typingEl.textContent = data.answer || "Koi answer nahi mila.";
    } catch (err) {
      typingEl.classList.remove("typing");
      typingEl.textContent = "Error: server se connect nahi ho paya.";
    }
    // The /chat response carries the exact id of the assistant row it saved
    // (normal answer, fallback, or service-unavailable notice). Advance past
    // it immediately so polling can never mistake our own answer — e.g. a
    // fallback — for a newly arriving message and render it twice.
    if (data && typeof data.message_id === "number") {
      advanceCursor(data.message_id);
    }
    pendingOwnRequest--;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  sendBtn.addEventListener("click", sendQuestion);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendQuestion();
  });
})();
```

**How to embed:** include `<script src="/static/widget.js"></script>`; optionally set `window.N2XChatConfig = { apiBase: "https://your-server" }` before it. The session id lives in `localStorage["n2x_session_id"]`; selected agent and last-seen cursor are also persisted in `localStorage` (`n2x_agent_id`, `n2x_last_seen_<session>`).

### 8.19 `static/index.html` (abbreviated summary, was a stub before)
Full Tailwind landing page (`<script src="https://cdn.tailwindcss.com">`), brand colors `#08B8B5`/teal, fonts Inter + Sora. Sections: fixed nav (Home / Services / Projects / About / Careers / Contact + "Get a Quote" → `#contact`); hero "We Build Digital Products That Look Premium & Perform Fast."; services grid (AI Development, Mobile Apps, Web Development, UI/UX Design, ChatGPT Integrations, Digital Marketing); stats band (200+ Projects Delivered, 99.9% Reliable Delivery, 24/7 Client Support); About N2X System (Lahore + London); "Download Portfolio" → **`/portfolio`**; projects showcase (N2X Knowledge Chatbot, Premium Product UI); footer with socials, contact links (info@n2xsystem.com, Lahore, London), **Admin** link, © 2026. At the bottom:
```html
<script>
    window.N2XChatConfig = { apiBase: "" };
</script>
<script src="/static/widget.js?v=9"></script>
```

### 8.20 `static/admin.html` (abbreviated summary — reworked)
Tailwind + Inter, brand `#00C2B8`. Header (Back to site, Logout). Tab bar with 6 tabs: **Agents, Knowledge Base, Chat History, Needs Attention, Analytics, API Keys**. See Changelog for the features of each. Key JS behaviors:
- Agent create/edit form (hidden `#agentId` for edit); optional initial-KB file selection (`createKnowledgeFile`) uploaded to `/upload` with the new agent's `id`; `PUT` on edit; delete with confirm.
- Knowledge Base: scope selector (`#kbAgentSel`, blank = General/Shared), drag-drop upload → `/upload` (+ `agent_id` if scope), docs table from `/documents` (deleting with scoped `?agent_id=` URL).
- Chat History: groups `/conversations` by `session_id`, renders user/bot lines.
- Needs Attention: pending handoffs from `/admin/handoffs`, each row has reply input → `POST /admin/handoffs/{sid}/reply`, and dismiss → `POST /admin/handoffs/{sid}/resolve`.
- Analytics: period select → `/admin/analytics?period=`; 4 stat cards, pure-SVG bar chart for last-7-days conversations, top-5 questions list.
- API Keys: generate with label → `/api-keys`, list, delete.
- `api()` helper redirects to `/login` on 401; `checkAuth()` on load.

### 8.21 `static/login.html` (abbreviated summary — Tailwind redesign)
Dark gradient background, centered card with N2 logo, Username + Password fields, submit → `POST /admin/login` (JSON), success → `/admin`, error message in Roman Urdu, "← Waps site par" link → `/`. Button shows "Logging in..." while disabled during the request.

### 8.22 `start.bat`
(empty — 0 bytes; the real launcher is `.start.bat`, section 8.2)

---

## 9. Knowledge Base Content

### `n2x_knowledge.txt` (shared + `agent_1/`)
Sections (heading-aware chunking groups these): **ABOUT US** (10+ years, 20+ clients, 50+ projects, mission/vision), **SERVICES** (10: Web Dev, Mobile Apps, UI/UX, eCommerce, ML & AI, Cyber Security, Product Development, Game Development, QA, DevOps & Cloud), **PROJECTS** (8: CarSharePK, TrueTrucker, HMS, Digital Tajer, N2X CRM System, Jabulani Group, Hospital Management System, Garage Management System — each with website + tech stack), **WHY CHOOSE N2X SYSTEM** (6 bullets), **CONTACT** (www.n2xsystem.com · info@n2xsystem.com · +92 323 452 9766 · Plot C 12, Street 195, DHA Phase 1, Lahore 54000).

### `sales_special.txt` (shared + `agent_4/`) — **NEW**
Internal confidential pricing sheet: MVP development fixed $5,000 (≤4 weeks); standard web app from $12,000; mobile app from $10,000 (iOS+Android; push notifications +$1,000, in-app payments +$2,000); hourly consulting $75/hr (senior); discount policy (20% startups first project, 10% returning clients); sales contact sales@n2xsystem.com.

**Current `uploaded_files/`:** `n2x_knowledge.txt`, `sales_special.txt`, `agent_1/n2x_knowledge.txt`, `agent_4/sales_special.txt`. ⚠️ `N2X-System-Portfolio.pdf` (referenced by `/portfolio`) is NOT present, so that endpoint currently 404s.

---

## 10. Security & Design Review

### Still good
- `hmac.compare_digest` credential check; `secrets.token_urlsafe(32)` session tokens; httpOnly + SameSite=Lax 7-day cookie; server-side revocable sessions.
- Parameterized SQL everywhere; PDF/TXT upload whitelist + `_safe_filename` path-traversal guard.
- Fallback/handoff feature is now wired end-to-end (good design: exact fallback contract + human queue + live delivery).

### Issues / things to note
1. **API keys still unused** — `/chat` remains completely unauthenticated (no key validation). Groq calls are paid; with CORS `*` the widget can be embedded anywhere.
2. **`GET /chat/messages/{session_id}` is public** — anyone who knows/guesses a session id (format `session-<base36>-<random>`) can read that session's message history. Low-risk but consider admin auth or a secret suffix.
3. **`/portfolio` 404** — `uploaded_files/N2X-System-Portfolio.pdf` is missing from the working tree; the landing-page "Download Portfolio" button currently errors until the file is re-uploaded.
4. **`sales_special.txt` is confidential pricing** — it is a tracked file in git and lives in the *shared* KB, so the bot reveals internal pricing to every visitor (by design for the Sales Assistant, but deliberate).
5. **No rate limiting** on `/chat` (public + paid LLM).
6. **No upload size limit**; filename collision still overwrites.
7. **Handoff data grows** — `handoffs` rows accumulate (resolved rows never purged); messages too (no retention).
8. **Session tokens stored in plaintext** in SQLite (acceptable for scope).
9. **Embedding model** still downloads on first lazy use (~90 MB, network needed).
10. **`score_threshold=0.15` + heading keyword boost** is heuristic — works for heading-style docs, but a wrong keyword match can still inject an off-topic chunk (bounded to 1 extra chunk).
11. **Fallback detection is exact-string based** (`answer == FALLBACK_MESSAGE`); any whitespace/character drift by the model silently breaks handoff creation.
12. **Groq model is `groq/compound-mini`** — a cost-optimized experimental model; `max_tokens=250` caps long answers.
13. **Analytics `today`/`week` use UTC** dates vs `datetime('now')` — consistent with SQLite defaults, but displays may differ from local timezone.
14. **Widget polling** adds 1 request per session every 15 s while the panel is open (minor traffic).

---

## 11. How to Run

```bat
cd /d D:\N2X\knowledge-chatbot
venv\Scripts\activate
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000 (or run `.start.bat`, which activates the venv, opens the browser, and starts uvicorn).

**Preconditions:**
- `pip install -r requirements.txt` in the venv.
- `.env` populated with valid `GROQ_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, and admin credentials.
- Qdrant cloud instance reachable; embedding model downloads on first lazy use.
- For `/portfolio`, ensure `uploaded_files/N2X-System-Portfolio.pdf` exists.

**Utility scripts (from repo root):**
```bat
.\venv\Scripts\python.exe scripts\reindex_n2x_knowledge.py
.\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py            (inventory)
.\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py --wipe --confirm-wipe
.\venv\Scripts\python.exe scripts\debug_retrieval.py
```

---

## 12. Summary

The project has evolved from a simple RAG chatbot into a **production-flavoured support stack**: agent-scoped retrieval with heading-aware chunking, a strict context-only/fallback answer contract, human handoff with live widget delivery, and admin analytics. The RAG pipeline stays hand-written and cleanly layered (routes/services/models). LLM model changed to `groq/compound-mini` with retries and universal behavior rules; chat now works even when Qdrant or the embedding model is down (casual short-circuit + availability flags). Main outstanding work: wire the API-key system into `/chat`, add rate limiting, tighten CORS/upload-size defaults, restore the portfolio PDF, and consider a retention policy for messages/handoffs.