# N2X Knowledge Chatbot — Updated Full Project Report

**Base document compared against:** `PROJECT_REPORT.md` (old report, tracked in git).
**Verified against the live codebase** at commit `577c56c` — *"Added multi-admin roles, agent ownership, human handoff, ratings, and bug fixes"* (branch `main`, working tree clean). All paths, endpoints, schemas and source code below were re-read from the current working tree, not assumed.

> **Purpose of this document:** To be fully **self-contained** — it captures every detail of the project (architecture, data flow, every API endpoint, full DB schema, configuration, all backend source code verbatim, frontend behavior, supporting scripts, knowledge-base content, and current runtime DB state) so that any other AI model (opencode terminal, ChatGPT, Claude, etc.) can understand the whole system **without reading any source file**. All code blocks are **verbatim** from the repo (only line numbers were stripped).

---

## CHANGELOG (changes since the OLD report at commit `266d633`)

### 🆕 NEW
- **Multi-admin roles** — `admin_users` table now has a `role` column: `super_admin` vs `admin`. `super_admin` can manage admin accounts; a regular `admin` only sees/edits/deletes **their own** agents and documents.
- **Agent ownership** — `agents` table gained `owner_admin_id` (references `admin_users.id`). Every agent has an owner admin. Regular admins are scoped to agents they own; super admins see everything.
- **Admin user management endpoints** — `GET /admin/users` (list + current user), `POST /admin/users` (create admin with role), `DELETE /admin/users/{id}`, `POST /admin/users/{id}/change-password`. All gated behind `require_super_admin`.
- **PBKDF2 password hashing** — passwords stored as PBKDF2-HMAC-SHA256 (`hashlib.pbkdf2_hmac("sha256", password, salt, 100_000)`), 100,000 iterations, per-user random 16-byte hex salt, compared with `hmac.compare_digest`. Legacy `.env` plain admin seeded as a `super_admin`.
- **Agent slugs & per-agent locked chat pages** — `agents.slug` (URL-friendly, unique via a dedicated unique index; collisions get `-2`, `-3`, …). New `GET /chat/{slug}` renders a full-page chat locked to one agent (no dropdown) via `static/agent_chat.html`; unknown slugs → friendly `static/agent_404.html`.
- **Agent descriptions** — `agents.description` one-liner; used to auto-build the system prompt and shown in agent management.
- **OCR fallback for scanned PDFs** — `app/services/pdf_processor.py::extract_text_from_pdf_ocr` uses `pdf2image` + `pytesseract` when plain text extraction yields < `TEXT_EXTRACTION_MIN_CHARS` (40) chars. Graceful user-facing error if nothing extractable. `pytesseract==0.3.13` and `pdf2image==1.17.0` added to `requirements.txt`.
- **Contact/heading retrieval boosts** — `app/services/vector_store.py` now force-includes CONTACT-typed chunks for contact/address queries (`baat/office/address/kaha`) and does a keyword heading scan so facts like "20+ Clients" that live in a heading/body match even when Roman-Urdu embeddings score poorly (embedding model is English-only).
- **Chunk truncation for LLM context** — `app/services/llm.py::truncate_chunks` keeps the most relevant chunks within `MAX_CONTEXT_CHARS = 16_000` so the Groq request body never exceeds its entity-size cap (HTTP 413).
- **Universal system-prompt template** — a single `SYSTEM_PROMPT_TEMPLATE` constant carries ALL fixed behavior rules (language/greeting hygiene, Roman-Urdu spelling tolerance, "baat = contact", casual-vs-factual classification, fallback, tone, 2-4 sentence length). Only `{agent_name}` and `{agent_description}` are filled. A per-agent optional **Advanced System Prompt** override is stored whole in `agents.system_prompt`.
- (Commit message says "ratings" — this means the **fallback-rate / analytics** feature, NOT a user chat-rating feature. Verified by grep: there is **no** `ratings` table, model, route, or UI anywhere in the codebase.)

### 🔄 CHANGED
- `uploaded_files/` layout — per-agent scoped dirs (`agent_1/`, `agent_4/`, `agent_14/`) alongside a shared root; KNOWN content now includes a shared `pakistan_test_series_records.pdf` plus an agent-scoped copy (see §6.7).
- `static/admin.html` — now 7 tabs: **Agents, Knowledge Base, Chat History, Needs Attention, Analytics, API Keys, Admins** (Admins tab only visible/usable for super admins).
- `static/login.html` — Tailwind redesign with the brand theme.
- `static/index.html` — full marketing landing page (hero, services, about, careers, projects, contact, footer) instead of the old stub.
- Admin panel now detects current role via `/admin/check` and hides/shows role-gated UI accordingly.

### 🗑️ REMOVED / DEPRECATED
- The old single monolithic full-page admin layout was replaced by the tabbed `admin.html`.

### ♻️ STILL TRUE (unchanged)
- Overall stack, Qdrant collection name `knowledge_base`, `all-MiniLM-L6-v2` embedding model (lazy singleton load), `groq/compound-mini` LLM, `.env` keys, SQLite `chatbot.db` at repo root, top-level routes (`/`, `/admin`, `/login`, `/portfolio`), `GET /portfolio` still serves `uploaded_files/N2X-System-Portfolio.pdf` (file absent → 404).

---

## 1. Project Overview

A **FastAPI-based RAG (Retrieval-Augmented Generation) customer-support chatbot** for **N2X System**, a Lahore-based software development agency.

- Users ask questions (English or Roman Urdu) through a floating chat widget (or a dedicated locked per-agent chat page).
- The system embeds the question, searches a **Qdrant** vector DB for relevant knowledge chunks, and asks **Groq** (`groq/compound-mini`) to answer using only the retrieved context plus a strict system prompt.
- An **admin panel** manages agents (multiple AI personas), knowledge-base documents (TXT/PDF, with OCR fallback), chat history, human-handoff fallbacks, analytics, API keys, and **admin user accounts**.
- All persistence is in **SQLite** (`chatbot.db`).

New since the old report: **multi-admin roles & ownership**, **per-agent slugs/locked pages**, **PBKDF2 hashing**, **OCR**, **contact/heading retrieval boosts**, **context truncation**, and the unified system-prompt template.

---

## 2. Tech Stack

| Layer | Technology | Version (pinned) |
|-------|-----------|------------------|
| Web framework | FastAPI | `0.115.0` |
| ASGI server | Uvicorn | `0.32.0` |
| DB | SQLite (via stdlib `sqlite3`) | — |
| Vector DB | Qdrant (client lib `qdrant-client`) | `1.12.0` |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (384-dim) | `3.2.1` |
| LLM | Groq `groq/compound-mini` | `groq==0.11.0` |
| PDF text | pypdf | `5.1.0` |
| OCR | pytesseract + pdf2image | `0.3.13` / `1.17.0` |
| Validation | Pydantic | `2.9.2` |
| Multipart / env | python-multipart / python-dotenv | `0.0.12` / `1.0.1` |
| Frontend | Tailwind CSS (CDN) + vanilla JS | — |
| Map/response | CORS wide open (`allow_origins=["*"]`) | — |

---

## 3. Directory Structure

```
knowledge-chatbot/
├── .env                     # 5 keys (GROQ_API_KEY, QDRANT_URL, QDRANT_API_KEY, ADMIN_USERNAME, ADMIN_PASSWORD)
├── .gitignore               # venv/, .env, uploaded_files/, __pycache__/, *.pyc, chatbot.db
├── .start.bat               # activates venv, opens browser, runs uvicorn --reload
├── README.md                # only "# N2XChatbot" (UTF-16 LE, BOM FF FE, 30 bytes)
├── requirements.txt         # 11 pinned packages
├── chatbot.db               # live SQLite DB (NOT tracked in git)
├── PROJECT_REPORT.md        # old report (superseded, kept in git for diffing)
├── PROJECT_REPORT_UPDATED.md# THIS report
├── app/
│   ├── __init__.py          # empty
│   ├── config.py            # .env loader
│   ├── db.py                # SQLite schema, sessions, agents, admins, handoffs, analytics, auth helpers
│   ├── main.py              # FastAPI app, page routes, middleware
│   ├── models/
│   │   ├── __init__.py      # empty
│   │   └── schemas.py       # Pydantic request bodies
│   ├── routes/
│   │   ├── __init__.py      # empty
│   │   ├── admin.py         # admin/auth/agents/documents/handoffs/analytics/keys/admin-users API
│   │   ├── chat.py          # /chat + /chat/messages/{session_id}
│   │   └── upload.py        # /upload (documents + OCR)
│   └── services/
│       ├── __init__.py      # empty
│       ├── auth.py          # cookie-session auth + role gates
│       ├── embeddings.py    # lazy singleton embedding model
│       ├── llm.py           # Groq calls, retries, truncation
│       ├── pdf_processor.py # PDF/TXT text extraction + OCR + heading-aware chunking
│       └── vector_store.py  # Qdrant collection, store/search/delete, contact & heading boosts
├── scripts/
│   ├── reindex_n2x_knowledge.py
│   ├── qdrant_knowledge_base.py
│   └── debug_retrieval.py
├── static/
│   ├── index.html           # marketing landing page (Tailwind)
│   ├── agent_chat.html      # locked per-agent full-page chat template
│   ├── agent_404.html       # friendly "chatbot not found" page
│   ├── login.html           # admin login page
│   ├── admin.html           # 7-tab admin panel
│   └── widget.js            # floating chat widget (v10 embedded present)
├── uploaded_files/          # knowledge documents (NOT tracked in git)
│   ├── n2x_knowledge.txt            # shared KB
│   ├── sales_special.txt            # shared confidential pricing sheet
│   ├── pakistan_test_series_records.pdf   # shared (test)
│   ├── agent_1/n2x_knowledge.txt
│   ├── agent_4/sales_special.txt
│   └── agent_14/pakistan_test_series_records (1).pdf
└── venv/                    # virtualenv (NOT tracked)
```

---

## 4. Data Flow

### 4.1 Document ingestion (admin uploads a file)
1. Admin (authenticated) POSTs a file to `/upload` (multipart form: `file`, optional `agent_id`).
2. `upload.py` checks extension (`.pdf`/`.txt`), checks agent access (owner rules), saves to `uploaded_files/` (or `uploaded_files/agent_<id>/`), then extracts text (with **OCR fallback** for scanned PDFs).
3. Text is split into **heading-aware chunks** (`chunk_text`, ~1500 chars/section).
4. Each chunk gets a 384-dim embedding (`all-MiniLM-L6-v2`).
5. Chunks (with `text`, `filename`, `agent_id`, `is_contact` payload) are upserted into Qdrant `knowledge_base`, replacing any previous points for that filename+scope.

### 4.2 Chat (user asks a question)
1. Widget POSTs `{question, session_id, agent_id}` to `/chat`.
2. If `session_id` present, the user message is saved (returns its row id).
3. `_casual_response` short-circuits greetings/thanks/bye *without* embeddings/Qdrant.
4. Otherwise: embed the question → `search_similar_chunks` (with contact & heading boosts) → build context via `truncate_chunks` → pick the agent's system prompt → call Groq (`generate_answer` with retry logic).
5. If context empty → `NO_RELEVANT_CONTEXT_FOUND`; if no retrieval available → `RETRIEVAL_UNAVAILABLE_MESSAGE`; else LLM answer.
6. The answer is saved (assistant row); if it equals `FALLBACK_MESSAGE`, a **handoff** is created. Response includes `user_message_id` and `message_id` for the widget cursor.

### 4.3 Human handoff (admin "Needs Attention" tab)
- When the bot can't answer, it replies `FALLBACK_MESSAGE` and inserts/updates a **pending** handoff row (`session_id`, `agent_id`, `question`).
- A super admin sees all pending handoffs; a regular admin only sees handoffs from their owned agents + unassigned (NULL `agent_id`) ones.
- Admin replies (`POST /admin/handoffs/{session_id}/reply`) → saves an assistant message + resolves the handoff; or dismisses (`POST /admin/handoffs/{session_id}/resolve`).
- The widget **polls** `GET /chat/messages/{session_id}` every 15 s while open and renders new assistant messages via a persisted last-seen cursor.

### 4.4 Analytics (admin "Analytics" tab)
- `GET /admin/analytics?period=today|week|month|all` returns: total conversations, total messages, **fallback rate** (%), avg messages/conversation, top-5 questions, conversations-per-day (last 7 days, SVG bar chart).

### 4.5 Agent management (admin "Agents" tab)
- Super admin: create/edit/delete ANY agent; regular admin: only own agents.
- Create fields: `name`, `description` (one-liner), `greeting`, `slug`, optional **Advanced System Prompt** override, optional initial KB file upload.
- Slug auto-generated from name (`lowercase`, hyphens, unique with `-2`/`-3` suffixes); admin can override.
- Editing preserves slug-uniqueness and resolves the system prompt (custom override wins otherwise universal template).

### 4.6 Auth & admin accounts (admin "Admins" tab — super admin only)
- Login via `POST /admin/login` → sets HTTP-only cookie `n2x_admin` (7-day, samesite=lax).
- `GET /admin/check` returns `{authenticated, role, username}`; the panel adapts to role.
- Super admins create other admins with role `admin` or `super_admin`, change passwords, delete accounts (with guardrails: cannot delete self, cannot delete the last admin or the last super admin).
- Passwords hashed with PBKDF2-HMAC-SHA256 (100k iterations, random salt). Sessions stored in `admin_sessions` keyed by a `secrets.token_urlsafe(32)` token.

---

## 5. API Endpoints

### Pages (no auth)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Landing page `static/index.html` (no-store). |
| GET | `/chat/{slug}` | Locked per-agent chat page (no-store). Unknown slug → `agent_404.html`. |
| GET | `/login` | Admin login page; redirects to `/admin` if already authed. |
| GET | `/portfolio` | Serves `uploaded_files/N2X-System-Portfolio.pdf`; 404 if file missing (it currently is). |
| GET | `/admin` | Admin panel; redirects to `/login` if not authed. |
| GET | `/static/*` | Static files mount. |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Main chat. Body `{question, session_id?, agent_id?}`. Returns `{question, answer, sources_used, user_message_id, message_id}`. |
| GET | `/chat/messages/{session_id}` | All messages for a session (widget polling). |

### Agents
| Method | Path | Description |
|--------|------|-------------|
| GET | `/agents` | Public: `{id, name, greeting, slug}`. Admin: full list, scoped to owned agents (super admin → all). |
| POST | `/agents` | Create agent (require_admin). Body `AgentCreate`. |
| GET | `/agents/{id}` | Detail (owner-checked; 403 if not owned by a regular admin). |
| PUT | `/agents/{id}` | Update agent (owner-checked). Body `AgentUpdate`. |
| DELETE | `/agents/{id}` | Delete agent + its Qdrant points + its uploaded dir. |

### Admin / Auth / Documents / Handoffs / Analytics / Keys
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/admin/login` | — | Login → set cookie. |
| POST | `/admin/logout` | — | Destroy session + clear cookie. |
| GET | `/admin/check` | — | `{authenticated, role, username}`. |
| GET | `/documents` | admin | List TXT/PDF files (optionally scoped `?agent_id=`). |
| DELETE | `/documents/{filename}` | admin | Delete file + its Qdrant points. |
| GET | `/conversations` | admin | All messages. |
| GET | `/admin/handoffs` | admin | Pending handoffs, role-scoped. |
| POST | `/admin/handoffs/{session_id}/reply` | admin | Save human reply + resolve. Body `HandoffReply`. |
| POST | `/admin/handoffs/{session_id}/resolve` | admin | Resolve pending handoff (404 if none). |
| GET | `/admin/analytics` | admin | `?period=` today/week/month/all metrics. |
| POST | `/api-keys` | admin | Create key. Body `{label}`. |
| GET | `/api-keys` | admin | List keys. |
| DELETE | `/api-keys/{id}` | admin | Delete key. |
| GET | `/admin/users` | **super_admin** | `{users[], current_user_id}`. |
| POST | `/admin/users` | **super_admin** | Create admin. Body `{username, password, role}`. |
| DELETE | `/admin/users/{admin_id}` | **super_admin** | Delete admin (guarded). |
| POST | `/admin/users/{admin_id}/change-password` | **super_admin** | Change admin password. Body `{password}`. |
| POST | `/upload` | admin | Upload document (multipart). |

---

## 6. Database Schema (SQLite `chatbot.db`)

`app/db.py::init_db()` creates tables and runs idempotent `ALTER TABLE` migrations (`_ensure_column`), a unique slug index, then seeds/backfills (default agent, default super admin, agent owners, slugs, descriptions).

### Messages
```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,          -- 'user' | 'assistant'
    content TEXT NOT NULL,
    was_fallback INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### api_keys
```sql
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT NOT NULL UNIQUE,   -- 'n2x_' + uuid4().hex
    label TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### admin_sessions
```sql
CREATE TABLE IF NOT EXISTS admin_sessions (
    token TEXT PRIMARY KEY,               -- secrets.token_urlsafe(32)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    admin_user_id INTEGER                 -- added via migration
);
```

### admin_users
```sql
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,          -- PBKDF2-HMAC-SHA256 hex (64 chars)
    salt TEXT NOT NULL,                   -- 32 hex chars (16 bytes)
    role TEXT NOT NULL DEFAULT 'admin',   -- 'admin' | 'super_admin'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### agents
```sql
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',   -- added via migration
    system_prompt TEXT NOT NULL,            -- resolved: custom override OR universal template filled
    greeting TEXT NOT NULL,
    owner_admin_id INTEGER REFERENCES admin_users(id),   -- added via migration
    slug TEXT,                              -- added via migration + unique index
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_slug ON agents(slug);
```

### handoffs
```sql
CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    agent_id INTEGER,
    question TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'resolved'
    resolved_at TEXT
);
```

### 6.6 Current DB runtime state (captured live)
- **Agents (3):**
  - id 1 `N2X Assistant` — desc "Sales Assistant for N2X System", owner_admin_id 1, slug `n2x-assistant`, system_prompt length **7454** (custom override).
  - id 4 `Sales Assistant` — desc "Sales Assistant for N2X System", owner_admin_id 1, slug `sales-assistant`, system_prompt length **7454** (custom override).
  - id 14 `cricket` — desc "ok", owner_admin_id 1, slug `cricket`, system_prompt length **2956** (universal template: stored prompt starts `You are cricket. ok\n\nUNIVERSAL RULES …`).
- **Admin users (3):**
  - id 1 `admin` — role `super_admin` (the original `.env` admin got promoted).
  - id 2 `ok` — role `admin`.
  - id 4 `hussain` — role `admin`.
  - (All `password_hash` length 64, `salt` length 32 → PBKDF2.)
- **Counts:** `messages` = **392**, `handoffs` = **18** (1 pending, 17 resolved), `api_keys` = **2** (labels `Abdulah`, `ok`), `admin_sessions` = **21**.
- **Known inconsistency (documented):** agents 1 and 4 store an identical custom "Sales Assistant System Prompt" (**7454 chars**, starts `# N2X System … Sales Assistant System Prompt`) that contains the **`{context}`, `{chat_history}`, `{question}` placeholders** — but `app/services/llm.py::generate_answer` does **NOT** substitute these placeholders (it only interpolates `system_prompt`, literal `context`, and literal `question` into a fixed prompt). So for agents 1/4 the literal strings `{context}` / `{chat_history}` / `{question}` are sent to Groq. Agent 14 (universal template) has no placeholders and works as designed.

### 6.7 `uploaded_files/` current layout
```
uploaded_files/
├── n2x_knowledge.txt                 4,610 B  (shared)
├── sales_special.txt                   783 B  (shared, confidential)
├── pakistan_test_series_records.pdf 51,217 B  (shared, test)
├── agent_1/n2x_knowledge.txt        4,610 B
├── agent_4/sales_special.txt          783 B
└── agent_14/pakistan_test_series_records (1).pdf  51,217 B
```

---

## 7. Configuration (`.env`)

`.env` holds exactly **5 keys** (values are secrets & not reproduced):
- `GROQ_API_KEY`
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `ADMIN_USERNAME` (default fallback `"admin"`)
- `ADMIN_PASSWORD` (default fallback `"change_this_password"`)

`app/config.py` loads them with `python-dotenv` and exposes module-level constants. `config.py`:

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

---

## 8. Source Code (verbatim)

### 8.1 `requirements.txt`
```
fastapi==0.115.0
uvicorn==0.32.0
python-multipart==0.0.12
pypdf==5.1.0
pytesseract==0.3.13
pdf2image==1.17.0
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

### 8.3 `app/main.py`
```python
import os
import json
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from app.db import init_db, get_agent_by_slug
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


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _no_cache_file(path: str, status_code: int = 200):
    return FileResponse(path, status_code=status_code, headers={
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
    })


def _load_template(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


AGENT_CHAT_TEMPLATE = _load_template("static/agent_chat.html")


@app.get("/chat/{slug}")
def agent_chat_page(slug: str):
    """Standalone full-page chat for one agent, locked to that agent (no
    dropdown). Missing slugs get a friendly 404 page."""
    agent = get_agent_by_slug(slug.lower())
    if not agent or AGENT_CHAT_TEMPLATE is None:
        return _no_cache_file("static/agent_404.html", status_code=404)
    payload = {
        "id": agent["id"],
        "name": agent["name"],
        "greeting": agent.get("greeting") or "",
        "slug": agent["slug"],
    }
    html = (
        AGENT_CHAT_TEMPLATE
        .replace("__AGENT_NAME__", _html_escape(agent["name"]))
        .replace("__AGENT_JSON__", json.dumps(payload))
    )
    return HTMLResponse(html, headers={
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

### 8.4 `app/models/schemas.py`
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
    description: str = ""
    greeting: str = ""
    slug: str = ""
    # Advanced: optional full custom prompt. Empty -> auto-built from the
    # universal template + name/description.
    system_prompt: str = ""


class AgentUpdate(BaseModel):
    name: str
    description: str = ""
    greeting: str = ""
    slug: str = ""
    system_prompt: str = ""


class HandoffReply(BaseModel):
    message: str


class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = "admin"


class AdminPasswordChange(BaseModel):
    password: str
```

### 8.5 `app/routes/chat.py`
```python
import re
import logging
import traceback

from fastapi import APIRouter

from app.models.schemas import ChatRequest
from app.services.embeddings import generate_embedding
from app.services.vector_store import search_similar_chunks
from app.services.llm import generate_answer, truncate_chunks
from app.db import (
    save_message,
    get_agent,
    get_session_messages,
    create_or_update_handoff,
    build_system_prompt,
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
        return "Khushi hui! Aur koi sawal ho to zaroor poochiye."
    if words and words <= {"bye", "goodbye", "allahhafiz", "khudahafiz", "ok", "okay"}:
        return "Allah Hafiz! Jab bhi zaroorat ho, hum yahan hain."
    if words and words <= greeting_words or normalized in {"kya haal hai", "how are you", "whats up"}:
        if normalized in {"hi", "hello", "hey", "good morning", "good evening"}:
            return "Hello! Main aapki kaise madad kar sakta hoon?"
        return "Hi! Main theek hoon. Aap kis cheez mein madad chahiye?"
    return None


def _generate_answer_or_fallback(question: str, context: str, system_prompt: str, fallback: str) -> str:
    try:
        return generate_answer(question, context, system_prompt=system_prompt)
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

    # 3. Combine only retrieved chunks into the context, keeping the most
    # relevant (top-scoring) chunks and truncating everything beyond
    # MAX_CONTEXT_CHARS so the request never exceeds the LLM provider's size
    # limit (oversized bodies surface as HTTP 413).
    relevant_chunks = list(relevant_chunks)

    sources_used = 0
    if relevant_chunks:
        selected = truncate_chunks(relevant_chunks)
        if selected:
            context = "\n\n".join(selected)
            sources_used = len(selected)
        else:
            context = NO_RELEVANT_CONTEXT_FOUND
    else:
        context = NO_RELEVANT_CONTEXT_FOUND

    # 4. Build the agent's system prompt: the stored prompt is already the
    # resolved one (the Advanced custom override when present, otherwise the
    # universal template filled with name/description). Fall back to a fresh
    # template build only if nothing is stored.
    system_prompt = DEFAULT_SYSTEM_PROMPT
    if request.agent_id is not None:
        agent = get_agent(request.agent_id)
        if agent:
            system_prompt = agent["system_prompt"] or build_system_prompt(
                agent["name"], agent.get("description") or ""
            )

    # 5. Ask LLM
    answer = _generate_answer_or_fallback(
        request.question, context, system_prompt, RETRIEVAL_UNAVAILABLE_MESSAGE
    )

    was_fallback = 1 if answer == FALLBACK_MESSAGE else 0
    return _reply(answer, sources_used=sources_used, was_fallback=was_fallback)


@router.get("/chat/messages/{session_id}")
async def session_messages(session_id: str):
    """Lightweight public endpoint the widget polls to pick up new
    (e.g. human-agent) assistant messages for its own session."""
    return get_session_messages(session_id)
```

### 8.6 `app/routes/upload.py`
```python
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Request
import shutil
import os

from app.services import pdf_processor
from app.services.embeddings import generate_embeddings_batch
from app.services.auth import ensure_agent_access, get_current_admin, require_admin
from app.services.vector_store import create_collection_if_not_exists, delete_points_by_filename, store_chunks

router = APIRouter()
UPLOAD_DIR = "uploaded_files"
ALLOWED_EXTENSIONS = (".pdf", ".txt")
TEXT_EXTRACTION_MIN_CHARS = 40

NO_TEXT_EXTRACTED_MESSAGE = (
    "Is file se koi text nahi mila - ye scanned/image-based PDF ho sakti hai "
    "jisme sirf images hain. Text version (.txt) bana kar upload karein, ya OCR "
    "enable karne ke liye Tesseract aur Poppler install karein."
)


def agent_upload_dir(agent_id: int) -> str:
    return os.path.join(UPLOAD_DIR, f"agent_{agent_id}")


@router.post("/upload", dependencies=[Depends(require_admin)])
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    agent_id: int | None = Form(None),
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and TXT files are allowed")

    admin_id, role = get_current_admin(request)
    ensure_agent_access(agent_id, admin_id, role)

    upload_dir = agent_upload_dir(agent_id) if agent_id is not None else UPLOAD_DIR
    if agent_id is not None:
        os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Extract text, falling back to OCR for scanned/image-only PDFs. A file
    # that yields nothing (or a PDF that fails to parse at all) gets a clear
    # user-facing error instead of a raw 500.
    text, ocr_used = try_extract_text(file_path, ext)

    # Chunk it
    chunks = [c for c in pdf_processor.chunk_text(text) if c.strip()]

    if not chunks:
        raise HTTPException(status_code=400, detail=NO_TEXT_EXTRACTED_MESSAGE)

    # Generate embeddings
    embeddings = generate_embeddings_batch(chunks)

    # Store in Qdrant, replacing any previously stored points for this file
    create_collection_if_not_exists()
    delete_points_by_filename(file.filename, agent_id)
    store_chunks(chunks, embeddings, file.filename, agent_id)

    return {
        "filename": file.filename,
        "message": "File uploaded and processed successfully",
        "chunks_created": len(chunks),
        "ocr_used": ocr_used,
    }


def extract_text(file_path: str, ext: str) -> str:
    if ext == ".txt":
        with open(file_path, "rb") as f:
            raw = f.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")
    return pdf_processor.extract_text_from_pdf(file_path)


def try_extract_text(file_path: str, ext: str) -> tuple[str, bool]:
    """Return (text, ocr_used).

    For PDFs, plain text extraction is tried first; if it yields too little
    text (a scanned/image-based PDF) or throws, an OCR pass runs. Both failing
    results in an empty string so the caller can report the graceful error."""
    if ext != ".pdf":
        return extract_text(file_path, ext), False
    text = ""
    try:
        text = extract_text(file_path, ext) or ""
    except Exception:
        text = ""
    if len(text.strip()) < TEXT_EXTRACTION_MIN_CHARS:
        ocr_text = pdf_processor.extract_text_from_pdf_ocr(file_path)
        if len(ocr_text.strip()) >= TEXT_EXTRACTION_MIN_CHARS:
            return ocr_text, True
    return text, False
```

### 8.7 `app/routes/admin.py`
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
    get_agent_by_slug,
    list_agents,
    update_agent,
    delete_agent,
    get_pending_handoffs,
    resolve_handoff,
    create_admin_user,
    get_admin_user,
    get_admin_user_by_username,
    list_admin_users,
    delete_admin_user,
    change_admin_password,
    get_session_admin_id,
)
from app.models.schemas import (
    ApiKeyCreate,
    AgentCreate,
    AgentUpdate,
    HandoffReply,
    AdminUserCreate,
    AdminPasswordChange,
)
from app.services.auth import (
    COOKIE_NAME,
    create_session,
    destroy_session,
    ensure_agent_access,
    get_current_admin,
    is_authenticated,
    require_admin,
    require_super_admin,
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
    if not is_authenticated(token):
        return {"authenticated": False, "role": None, "username": None}
    admin_id = get_session_admin_id(token)
    admin = get_admin_user(admin_id) if admin_id is not None else None
    if not admin:
        return {"authenticated": False, "role": None, "username": None}
    return {
        "authenticated": True,
        "role": admin.get("role", "admin"),
        "username": admin["username"],
    }


@router.get("/documents", dependencies=[Depends(require_admin)])
def list_documents(request: Request, agent_id: int | None = None):
    admin_id, role = get_current_admin(request)
    ensure_agent_access(agent_id, admin_id, role)
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
def delete_document(filename: str, request: Request, agent_id: int | None = None):
    if not _safe_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    admin_id, role = get_current_admin(request)
    ensure_agent_access(agent_id, admin_id, role)

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
def handoffs(request: Request):
    admin_id, role = get_current_admin(request)
    return get_pending_handoffs(admin_id, role)


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
def list_agents_public_or_admin(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not is_authenticated(token):
        return [
            {"id": a["id"], "name": a["name"], "greeting": a["greeting"], "slug": a["slug"]}
            for a in list_agents()
        ]
    admin_id, role = get_current_admin(request)
    return list_agents(None if role == "super_admin" else admin_id)


def _get_owned_agent(agent_id: int, admin_id: int | None, role: str | None) -> dict:
    """Fetch an agent, raising 404 when it does not exist and 403 when the
    caller (a regular admin) does not own it."""
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if role != "super_admin" and agent.get("owner_admin_id") != admin_id:
        raise HTTPException(status_code=403, detail="You don't have access to this agent")
    return agent


@router.post("/agents", dependencies=[Depends(require_admin)])
def create_new_agent(req: AgentCreate, request: Request):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Agent name is required")
    admin_id, _ = get_current_admin(request)
    try:
        return create_agent(
            req.name.strip(),
            req.description,
            req.greeting,
            admin_id,
            slug=req.slug or None,
            system_prompt=req.system_prompt or "",
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="An agent with this name already exists")


@router.get("/agents/{agent_id}", dependencies=[Depends(require_admin)])
def get_agent_detail(agent_id: int, request: Request):
    admin_id, role = get_current_admin(request)
    return _get_owned_agent(agent_id, admin_id, role)


@router.put("/agents/{agent_id}", dependencies=[Depends(require_admin)])
def update_existing_agent(agent_id: int, req: AgentUpdate, request: Request):
    admin_id, role = get_current_admin(request)
    _get_owned_agent(agent_id, admin_id, role)
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Agent name is required")
    try:
        ok = update_agent(
            agent_id,
            req.name.strip(),
            req.description,
            req.greeting,
            admin_id=admin_id,
            role=role,
            slug=req.slug or None,
            system_prompt=req.system_prompt or "",
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="An agent with this name already exists")
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return get_agent(agent_id)


@router.delete("/agents/{agent_id}", dependencies=[Depends(require_admin)])
def delete_existing_agent(agent_id: int, request: Request):
    admin_id, role = get_current_admin(request)
    _get_owned_agent(agent_id, admin_id, role)
    delete_points_by_agent(agent_id)
    shutil.rmtree(agent_upload_dir(agent_id), ignore_errors=True)
    if not delete_agent(agent_id, admin_id=admin_id, role=role):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"message": "Agent deleted"}


ADMIN_PASSWORD_MIN_LENGTH = 6


@router.get("/admin/users", dependencies=[Depends(require_super_admin)])
def admin_users(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    current_user_id = get_session_admin_id(token) if token else None
    return {
        "users": list_admin_users(),
        "current_user_id": current_user_id,
    }


VALID_ADMIN_ROLES = ("admin", "super_admin")


@router.post("/admin/users", dependencies=[Depends(require_super_admin)])
def create_new_admin(req: AdminUserCreate):
    role = (req.role or "admin").strip().lower()
    if role not in VALID_ADMIN_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Invalid role. Must be 'admin' or 'super_admin'",
        )
    username = req.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(req.password) < ADMIN_PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {ADMIN_PASSWORD_MIN_LENGTH} characters",
        )
    if get_admin_user_by_username(username):
        raise HTTPException(status_code=400, detail="A user with this username already exists")
    try:
        return create_admin_user(username, req.password, role)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="A user with this username already exists")


@router.delete("/admin/users/{admin_id}", dependencies=[Depends(require_super_admin)])
def delete_existing_admin(admin_id: int, request: Request):
    target = get_admin_user(admin_id)
    if not target:
        raise HTTPException(status_code=404, detail="Admin user not found")
    token = request.cookies.get(COOKIE_NAME)
    current_user_id = get_session_admin_id(token) if token else None
    if current_user_id is not None and current_user_id == admin_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if not delete_admin_user(admin_id):
        if target["role"] == "super_admin":
            raise HTTPException(status_code=400, detail="Cannot delete the last super admin")
        raise HTTPException(status_code=400, detail="Cannot delete the last admin user")
    return {"message": "Admin user deleted"}


@router.post("/admin/users/{admin_id}/change-password", dependencies=[Depends(require_super_admin)])
def change_admin_password_endpoint(admin_id: int, req: AdminPasswordChange):
    if not get_admin_user(admin_id):
        raise HTTPException(status_code=404, detail="Admin user not found")
    if len(req.password) < ADMIN_PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {ADMIN_PASSWORD_MIN_LENGTH} characters",
        )
    change_admin_password(admin_id, req.password)
    return {"message": "Password changed"}
```

### 8.8 `app/services/auth.py`
```python
import secrets

from fastapi import HTTPException, Request

from app.db import (
    admin_session_exists,
    create_admin_session,
    delete_admin_session,
    get_admin_role,
    get_agent,
    get_session_admin_id,
    verify_admin_user,
)

COOKIE_NAME = "n2x_admin"


def verify_credentials(username: str, password: str) -> bool:
    return verify_admin_user(username, password) is not None


def create_session(username: str, password: str) -> str | None:
    user = verify_admin_user(username, password)
    if not user:
        return None
    token = secrets.token_urlsafe(32)
    create_admin_session(token, user["id"])
    return token


def destroy_session(token: str) -> None:
    delete_admin_session(token)


def is_authenticated(token: str | None) -> bool:
    return bool(token) and admin_session_exists(token)


def require_admin(request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not is_authenticated(token):
        raise HTTPException(status_code=401, detail="Not authenticated")


def require_super_admin(request: Request) -> None:
    """Verify the request belongs to an authenticated super admin."""
    token = request.cookies.get(COOKIE_NAME)
    if not is_authenticated(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
    admin_id = get_session_admin_id(token)
    role = get_admin_role(admin_id) if admin_id is not None else None
    if role != "super_admin":
        raise HTTPException(
            status_code=403, detail="Only super admins can manage admin accounts"
        )


def get_current_admin(request: Request) -> tuple[int | None, str | None]:
    """Return (admin_id, role) of the authenticated admin in this request, or
    (None, None) when there is no admin session."""
    token = request.cookies.get(COOKIE_NAME)
    admin_id = get_session_admin_id(token) if token else None
    if admin_id is None:
        return None, None
    return admin_id, get_admin_role(admin_id)


def ensure_agent_access(
    agent_id: int | None, admin_id: int | None, role: str | None
) -> None:
    """Gate agent-scoped documents/knowledge-base access. The shared scope
    (agent_id=None) is open to every admin; a scoped agent is only reachable
    by its owner, or by any super admin."""
    if agent_id is None or role == "super_admin":
        return
    if not get_agent(agent_id, admin_id, role):
        raise HTTPException(
            status_code=403, detail="You don't have access to this agent"
        )
```

### 8.9 `app/services/embeddings.py`
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

### 8.10 `app/services/llm.py`
```python
import time
import logging
from groq import Groq, RateLimitError, APIConnectionError, APITimeoutError, APIStatusError
from app.config import GROQ_API_KEY
from app.db import DEFAULT_SYSTEM_PROMPT

client = Groq(api_key=GROQ_API_KEY)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3

# groq/compound-mini exposes a 131,072-token context window (~500KB of text).
# We deliberately cap the retrieved context far below that: answers are 2-4
# sentences so a handful of chunks is plenty, and staying well under the window
# also keeps the HTTP request body below Groq's entity-size cap (oversized
# bodies surface as HTTP 413 "Request Entity Too Large").
MAX_CONTEXT_CHARS = 16_000


def truncate_chunks(chunks: list[dict], max_chars: int = MAX_CONTEXT_CHARS) -> list[str]:
    """Keep the most relevant chunks for the LLM context, dropping or trimming
    anything beyond ``max_chars``.

    ``chunks`` is a list of ``{"text": str, "score": float}`` dicts. Greedy
    selection sorts highest-scoring chunks first: full chunks are kept while
    they fit, the first chunk that would overflow is sliced to the remaining
    budget, and lower-scoring chunks are dropped entirely.
    """
    if max_chars <= 0:
        return []
    budget = max_chars
    selected: list[str] = []
    for chunk in sorted(chunks, key=lambda c: c.get("score") or 0.0, reverse=True):
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        if len(text) <= budget:
            selected.append(text)
            budget -= len(text)
        else:
            selected.append(text[:budget])
            budget = 0
        if budget <= 0:
            break
    return selected


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
        except APIStatusError as exc:
            # 413 means the prompt body exceeds Groq's entity-size limit.
            # Its only fix is a smaller prompt, which truncation already
            # enforces, so retrying the identical payload is pointless.
            if exc.status_code == 413:
                last_error = exc
                logger.error(
                    "Groq rejected an oversized request (HTTP 413). Context is "
                    "already capped at MAX_CONTEXT_CHARS=%d; check for an "
                    "oversized agent system prompt. Not retrying: %s",
                    MAX_CONTEXT_CHARS,
                    exc,
                )
            raise exc
    raise last_error

def generate_answer(question: str, context: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> str:
    prompt = f"""{system_prompt}

Context:
{context}

Question: {question}

Answer:"""

    response = _create_completion(prompt)

    return response
```

### 8.11 `app/services/pdf_processor.py`
```python
from pypdf import PdfReader
import re

def extract_text_from_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text


def extract_text_from_pdf_ocr(file_path: str) -> str:
    """OCR fallback for scanned/image-only PDFs via pdf2image + pytesseract.

    Returns the recognized text, or "" when the OCR toolchain (the Tesseract
    and Poppler binaries) is not installed or the pages carry no recognizable
    text. Callers must treat "" exactly like an extraction failure — this is
    best-effort and must never crash the upload flow."""
    try:
        from pdf2image import convert_from_path
        import pytesseract

        pages = convert_from_path(file_path)
        try:
            return "\n".join(pytesseract.image_to_string(page) for page in pages)
        finally:
            for page in pages:
                if hasattr(page, "close"):
                    page.close()
    except Exception:
        return ""


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

### 8.12 `app/services/vector_store.py`
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

# Contact/address signals. Queries containing these words always force the
# agent's CONTACT-typed chunks into the retrieval context regardless of the
# vector score, so "contact/baat/office/address/kaha" questions never fail.
CONTACT_QUERY_WORDS = {
    "office", "address", "location", "contact", "kaha", "kahan",
    "baat", "raabta", "rabta", "milne", "milo", "email", "phone",
    "number", "call", "where", "head",
}

_CONTACT_CHUNK_PATTERN = re.compile(
    r"(email|e-?mail|phone|whatsapp|contact|address|office|location|"
    r"head ?office|raabta|plot|street|www\.[a-z0-9-]+|\.com\b|"
    r"\+[\d][\d\s-]{5,}|\b\d{4,}[-.\s]?\d{3,})",
    re.IGNORECASE,
)

_CONTACT_SIGNAL_WORDS = (
    "email", "phone", "whatsapp", "contact", "address", "office",
    "location", "raabta", "plot", "street", "call",
)


def is_contact_query(query_text: str) -> bool:
    """True when a user question looks like a contact/address request."""
    tokens = set(re.findall(r"[a-z]+", (query_text or "").lower()))
    return bool(tokens & CONTACT_QUERY_WORDS)


def is_contact_chunk(text: str) -> bool:
    """True when a knowledge chunk carries contact details (email/phone/
    address/location): such chunks are force-included for contact queries."""
    return bool(_CONTACT_CHUNK_PATTERN.search(text or ""))


def _contact_score(text: str) -> int:
    """Rough relevance of a chunk to contact queries: the number of distinct
    contact signals it mentions."""
    lower = (text or "").lower()
    return sum(1 for word in _CONTACT_SIGNAL_WORDS if word in lower)


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
    ensure_contact_index()

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

CONTACT_INDEX_KEYWORD = "is_contact"

def ensure_contact_index():
    try:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=CONTACT_INDEX_KEYWORD,
            field_schema=PayloadSchemaType.INTEGER,
        )
    except Exception:
        pass

def store_chunks(chunks: list[str], embeddings: list[list[float]], filename: str, agent_id: int | None = None):
    points = []
    for chunk, embedding in zip(chunks, embeddings):
        payload = {
            "text": chunk,
            "filename": filename,
            CONTACT_INDEX_KEYWORD: 1 if is_contact_chunk(chunk) else 0,
        }
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

def _scope_filter(agent_id: int | None) -> Filter:
    """Filter that limits retrieval to the right knowledge scope:
    - a specific agent: that agent's chunks PLUS the shared (agent_id empty) ones
    - no agent (shared chat): only the shared chunks"""
    if agent_id is not None:
        return Filter(
            should=[
                IsEmptyCondition(is_empty=PayloadField(key="agent_id")),
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
            ]
        )
    return Filter(
        must=[IsEmptyCondition(is_empty=PayloadField(key="agent_id"))]
    )


def search_similar_chunks(query_embedding: list[float], top_k: int = 3, agent_id: int | None = None, score_threshold: float = 0.15, query_text: str | None = None) -> tuple[list[dict], bool]:
    """Return matching chunks and whether Qdrant was reachable.

    Each chunk dict carries the chunk ``text`` and its vector ``score`` so
    callers can prioritise the most relevant content when truncating the LLM
    context (a 413 error occurs when the combined context grows too large).

    The embedding model is English-only, so Roman Urdu queries score poorly
    against English sections. ``query_text`` enables two keyword boosts:
    1. a heading keyword boost (query word matches a chunk's heading/content),
    2. a CONTACT boost: when the query asks about contact/address/office/baat,
       contact-typed chunks are force-included regardless of vector score.
    """
    query_filter = _scope_filter(agent_id)
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

    chunks = [
        {"text": result.payload.get("text", ""), "score": float(result.score)}
        for result in results
        if (result.payload or {}).get("text")
    ]

    if query_text:
        # Contact/address queries: force the agent's CONTACT chunks in even when
        # their vector score is low, so "baat/office/address/kaha" never fails.
        if is_contact_query(query_text):
            chunks = _merge_contact_chunks(chunks, query_filter, query_text, top_k)

        heading_match = _heading_keyword_match(query_text, query_filter)
        if heading_match and heading_match not in [c["text"] for c in chunks]:
            top_score = chunks[0]["score"] if chunks else 0.0
            chunks.insert(0, {"text": heading_match, "score": top_score + 1.0})
            chunks = chunks[: top_k + 1]

    return chunks, True


def _merge_contact_chunks(chunks: list[dict], query_filter: Filter, query_text: str, top_k: int) -> list[dict]:
    """Prepend up to two contact-typed chunks for contact/address queries, then
    cap the result at top_k + inserted chunks (deduping against the semantic
    results). A failure here is non-fatal: plain retrieval still proceeds."""
    try:
        contact_filter = Filter(
            must=[FieldCondition(key=CONTACT_INDEX_KEYWORD, match=MatchValue(value=1))]
            + (list(query_filter.must) if query_filter.must else []),
            should=query_filter.should,
        )
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=contact_filter,
            limit=20,
            with_payload=True,
        )
    except Exception:
        logger.exception("Contact chunk fetch failed")
        return chunks

    candidates = [
        (point.payload or {}).get("text", "")
        for point in result[0]
        if (point.payload or {}).get("text")
    ]
    candidates.sort(key=lambda text: _contact_score(text), reverse=True)

    existing = {c["text"] for c in chunks}
    top_score = chunks[0]["score"] if chunks else 0.0
    inserted = 0
    for text in candidates:
        if text in existing:
            continue
        existing.add(text)
        chunks.insert(0, {"text": text, "score": top_score + 1.0})
        inserted += 1
        if inserted >= 2:
            break
    if inserted:
        chunks = chunks[: top_k + inserted]
    return chunks


def _heading_keyword_match(query_text: str, query_filter: Filter | None, exclude_contact: bool = True) -> str | None:
    """Return the first chunk whose heading or leading content matches a
    significant query word.

    A "significant" word is 3+ alphanumeric characters; the match is
    case-insensitive against the chunk's heading and first few content lines
    (headings only were too strict for facts like ``20+ Clients`` that live in
    the body of a section). Without a word-boundary match, "cricket" inside
    "info@cricket.com" would let a contact chunk answer the wrong question, so
    CONTACT chunks are skipped here (the dedicated contact merge handles them)
    unless the query itself is a contact request.
    """
    tokens = {
        token
        for token in re.findall(r"[a-zA-Z0-9]+", query_text.lower())
        if len(token) >= 3
    }
    if not tokens:
        return None
    contact_query = is_contact_query(query_text)
    try:
        # Bounded scan: limit=1000 fetches up to 1000 full payloads in one
        # response, which is a big transfer for a keyword pre-check and can
        # push this call out of the /chat request budget. 100 points are
        # plenty to surface a matching heading section.
        result = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=query_filter,
            limit=100,
            with_payload=True,
        )
        for point in result[0]:
            payload = point.payload or {}
            if exclude_contact and not contact_query and payload.get(CONTACT_INDEX_KEYWORD) == 1:
                continue
            text = payload.get("text", "")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            haystack = "\n".join(lines[:6]).lower()
            if haystack and any(token in haystack for token in tokens):
                return text
    except Exception:
        logger.exception("Heading keyword scan failed")
        return None
    return None
```

### 8.13 `app/db.py`
```python
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
```

### 8.14 `static/widget.js` (verbatim)
```js
(function () {
  "use strict";

  var CONFIG = window.N2XChatConfig || {};
  var API_BASE = CONFIG.apiBase || "";
  var EMBEDDED = CONFIG.mode === "embedded";
  var LOCKED_AGENT =
    window.N2X_CHAT_AGENT && typeof window.N2X_CHAT_AGENT.id === "number" ? window.N2X_CHAT_AGENT : null;

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
    if (EMBEDDED && CONFIG.mount) {
      var host = document.getElementById(CONFIG.mount);
      if (host) {
        host.appendChild(root);
        return;
      }
    }
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
    "#n2x-widget.embedded { position: static; inset: auto; width: 100%; height: 100%; }" +
    "#n2x-widget.embedded #n2x-launcher, #n2x-widget.embedded #n2x-close { display: none; }" +
    "#n2x-widget.embedded #n2x-panel { position: static; right: auto; bottom: auto; width: 100%; height: 100%; max-width: none; max-height: none; border: none; border-radius: 0; box-shadow: none; }" +
    "#n2x-widget.embedded #n2x-panel.hidden { display: flex; }" +
    "#n2x-widget .locked-label { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px; font-weight: 600; }" +
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
    var locked = LOCKED_AGENT;
    if (EMBEDDED && !locked) {
      // Backstop: if the page did not inject the agent, resolve it from the
      // URL slug (e.g. /chat/sales-assistant) against the public agent list.
      var pathMatch = window.location.pathname.match(/^\/chat\/([A-Za-z0-9_-]+)\/?$/);
      if (pathMatch) {
        try {
          var listRes = await fetch(API_BASE + "/agents");
          var list = (await listRes.json()) || [];
          var found = list.filter(function (a) { return a.slug === pathMatch[1]; })[0];
          if (found) {
            locked = { id: found.id, name: found.name, greeting: found.greeting, slug: found.slug };
          }
        } catch (e) {}
      }
    }

    if (locked) {
      var label = document.createElement("span");
      label.className = "locked-label";
      label.textContent = locked.name;
      agentSelect.parentNode.replaceChild(label, agentSelect);
      selectAgent(locked);
      return;
    }

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
    if (!agentSelect.parentNode) return;
    var target = agents.filter(function (a) { return a.id === parseInt(agentSelect.value, 10); })[0];
    if (target) selectAgent(target);
  });

  loadAgents();
  if (EMBEDDED) startPolling();

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

### 8.15 `static/agent_chat.html` (template, verbatim)
```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__AGENT_NAME__ — N2X Chat</title>
<meta name="description" content="Chat with the __AGENT_NAME__ assistant from N2X System." />
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
<script>
  tailwind.config = {
    theme: {
      extend: {
        fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'] },
        colors: { brand: '#00C2B8', brandDark: '#0BA39B', charcoal: '#1A1A1A', slate: '#64748B' },
      },
    },
  };
</script>
<style>
  html, body { height: 100%; }
  body { display: flex; flex-direction: column; overflow: hidden; }
  #n2x-mount { flex: 1; min-height: 0; display: flex; }
</style>
</head>
<body class="bg-slate-100 font-sans text-slate-700 antialiased">

  <header class="bg-charcoal text-white px-6 py-4 flex items-center justify-between gap-4 shadow-lg">
    <div class="flex items-center gap-3 min-w-0">
      <div class="w-9 h-9 shrink-0 flex items-center justify-center rounded-xl bg-gradient-to-br from-brand to-cyan-500 text-white font-black text-xs shadow-lg shadow-cyan-500/20">
        N2
        <span class="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-gradient-to-tr from-teal-400 to-cyan-300 ring-2 ring-charcoal"></span>
      </div>
      <div class="min-w-0">
        <h1 class="text-base font-extrabold tracking-tight truncate">__AGENT_NAME__</h1>
        <p class="text-xs text-slate-400 truncate">N2X System Assistant — apna sawal neeche likho</p>
      </div>
    </div>
    <a href="/" class="shrink-0 text-slate-300 hover:text-brand text-sm font-medium transition-colors">Back to site</a>
  </header>

  <main id="n2x-mount"></main>

  <script>
    window.N2XChatConfig = { apiBase: "", mode: "embedded", mount: "n2x-mount" };
    window.N2X_CHAT_AGENT = __AGENT_JSON__;
  </script>
  <script src="/static/widget.js?v=10"></script>
</body>
</html>
```

### 8.16 `static/agent_404.html` (verbatim)
```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Chatbot Nahi Mila — N2X System</title>
<meta name="robots" content="noindex" />
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { display: flex; align-items: center; justify-content: center; min-height: 100dvh; }
</style>
</head>
<body class="bg-slate-100 text-slate-700">
  <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-10 max-w-md mx-auto text-center">
    <div class="w-14 h-14 mx-auto mb-5 flex items-center justify-center rounded-2xl bg-brand/10 text-brand font-black text-xl">
      N2
    </div>
    <h1 class="text-2xl font-extrabold text-charcoal tracking-tight">Ye chatbot nahi mila</h1>
    <p class="mt-3 text-sm text-slate leading-relaxed">
      Jis agent ka link aap ne khola hai wo exist nahi karta — ho sakta hai ke wo delete ho gaya ho,
      ya link mein typo ho.
    </p>
    <div class="mt-6 flex items-center justify-center gap-3">
      <a href="/" class="rounded-xl bg-brand hover:bg-brandDark text-white font-semibold px-5 py-2.5 text-sm shadow-lg shadow-brand/30 transition-colors">N2X System Home</a>
      <a href="/admin" class="rounded-xl border border-slate-300 text-slate-600 hover:bg-slate-50 px-5 py-2.5 text-sm font-semibold transition-colors">Admin</a>
    </div>
  </div>
</body>
</html>
```

### 8.17 `static/login.html` (verbatim)
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>N2X Admin Login</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: { sans: ['Inter', 'Poppins', 'ui-sans-serif', 'system-ui', 'sans-serif'] },
                    colors: { brand: '#00C2B8', brandDark: '#0BA39B', charcoal: '#1A1A1A', slate: '#64748B' },
                },
            },
        };
    </script>
</head>
<body class="font-sans bg-gradient-to-br from-charcoal via-black to-teal-900 min-h-screen flex items-center justify-center px-4 py-10">
    <!-- subtle grid + glow -->
    <div class="fixed inset-0 opacity-[0.05] pointer-events-none"
         style="background-image: linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px); background-size: 56px 56px;"></div>
    <div class="fixed -top-24 -right-24 w-96 h-96 rounded-full bg-brand/20 blur-3xl pointer-events-none"></div>
    <div class="fixed -bottom-24 -left-24 w-96 h-96 rounded-full bg-cyan-500/20 blur-3xl pointer-events-none"></div>

    <div class="relative w-full max-w-md bg-white rounded-2xl shadow-2xl shadow-black/30 p-8 sm:p-10">
        <!-- Logo -->
        <div class="flex items-center justify-center gap-3 mb-6">
            <div class="w-11 h-11 relative flex items-center justify-center rounded-2xl bg-gradient-to-br from-brand to-cyan-500 text-white font-black text-sm shadow-lg shadow-cyan-500/30">
                N2
                <span class="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-gradient-to-tr from-teal-400 to-cyan-300 ring-2 ring-white"></span>
            </div>
            <span class="text-xl font-extrabold tracking-tight text-charcoal">n2x<span class="text-brand">System</span></span>
        </div>

        <h1 class="text-2xl font-black text-charcoal text-center">Admin Panel</h1>
        <p class="text-sm text-slate text-center mb-8">Aagay barhnay ke liye login karo</p>

        <form id="loginForm">
            <div class="mb-4">
                <label for="username" class="block text-sm font-semibold text-charcoal/80 mb-2">Username</label>
                <input id="username" type="text" autocomplete="username" required
                       class="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 transition" />
            </div>
            <div class="mb-6">
                <label for="password" class="block text-sm font-semibold text-charcoal/80 mb-2">Password</label>
                <input id="password" type="password" autocomplete="current-password" required
                       class="w-full border border-slate-300 rounded-xl px-4 py-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 transition" />
            </div>
            <button id="loginBtn" type="submit"
                    class="w-full bg-brand hover:bg-brandDark disabled:opacity-60 disabled:cursor-not-allowed text-white font-bold rounded-xl py-3 text-sm shadow-lg shadow-brand/30 transition-colors">
                Login
            </button>
            <div id="msg" class="hidden mt-4 rounded-lg bg-red-50 text-red-700 text-sm px-4 py-3"></div>
        </form>

        <a class="block text-center mt-6 text-sm text-slate-500 hover:text-brand transition-colors" href="/">&larr; Waps site par</a>
    </div>

    <script>
        var form = document.getElementById("loginForm");
        var msg = document.getElementById("msg");

        function showError(text) {
            msg.textContent = text;
            msg.classList.remove("hidden");
        }

        form.addEventListener("submit", async function (e) {
            e.preventDefault();
            var username = document.getElementById("username").value.trim();
            var password = document.getElementById("password").value;
            if (!username || !password) {
                showError("Username aur password dono likho.");
                return;
            }
            msg.classList.add("hidden");
            var btn = document.getElementById("loginBtn");
            btn.disabled = true;
            btn.textContent = "Logging in...";
            try {
                var res = await fetch("/admin/login", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ username: username, password: password }),
                });
                var data = await res.json();
                if (!res.ok) throw new Error(data.detail || "Login failed");
                window.location.href = "/admin";
            } catch (err) {
                showError(err.message);
                btn.disabled = false;
                btn.textContent = "Login";
            }
        });
    </script>
</body>
</html>
```

### 8.18 `static/index.html` (abbreviated structural summary)
This is a full **Tailwind marketing landing page** (27,156 bytes) served at `/`. It uses the brand theme (`brand: #00C2B8`, `brandDark: #0BA39B`, `charcoal: #1A1A1A`, `slate: #64748B`) and the Inter font. Structure:
- **Header/nav** (fixed): logo "N2", links to `#home`, `#services`, `#about`, `#careers`, `#contact`, plus a CTA "Button".
- **Hero** (`#home`): headline, subtext, and CTA link to `/portfolio` ("Download Portfolio").
- **Services** (`#services`): "What We Do" — cards for **AI Development, Mobile Apps, Web Development, UI/UX Design, ChatGPT Integrations, Digital Marketing**.
- **About** (`#about`): "About N2X System" section.
- **Careers** (`#careers`): "Drop your CV at info@n2xsystem.com" + portfolio link.
- **Projects** (`#projects`): "N2X Digital Experiences" — project cards incl. "N2X Knowledge Chatbot" and "Premium Product UI".
- **Contact** (`#contact`): link `info@n2xsystem.com`.
- **Footer**: nav links (Home, About Us, Projects, Careers, Contact), Privacy Policy / Terms of Service, social icons (Instagram/LinkedIn/Facebook), and **Admin** link `/admin`.
- **Chat widget** loaded at the end: `<script src="/static/widget.js?v=9"></script>` with inline `N2XChatConfig`.

### 8.19 `static/admin.html` (abbreviated structural summary)
A 7-tab Tailwind admin panel (47,733 bytes). It calls `/admin/check` on load, and adapts to the logged-in role (the **Admins** tab is only shown/used for `super_admin`). Tabs:
1. **Agents** (`#agents`) — "Create Agent" / "Edit Agent" form (name, description, greeting, slug, Advanced System Prompt toggle, initial knowledge file selection) with `#saveAgentBtn` / `#cancelAgentBtn` / `#advancedToggle`; a table of agents each with copy-URL (slug), Edit, Delete. JS: `loadAgents`, `startEditAgent`, `resetAgentForm`, `slugifyName`, `selectCreateKnowledgeFile`. Calls `POST /agents`, `PUT/DELETE /agents/{id}`, `POST /upload` (initial KB), `GET /agents`.
2. **Knowledge Base** (`#kb`) — scope selector (General vs per-agent `?agent_id=`), upload form, uploaded-documents table. JS: `uploadFile`, `loadDocuments`, `DELETE /documents/{filename}?agent_id=`.
3. **Chat History** (`#history`) — `GET /conversations` table of all messages. JS: `loadConversations`.
4. **Needs Attention** (`#handoffs`) — pending handoffs with Reply / Dismiss buttons. JS: `loadHandoffs`; `POST /admin/handoffs/{session_id}/reply`, `POST .../resolve`.
5. **Analytics** (`#analytics`) — period selector (today/week/month/all), metric cards, **SVG bar chart** "Conversations per Day (last 7 days)", and "Top 5 Questions" list. JS: `loadAnalytics`, `renderAnalyticsChart`, `renderTopQuestions`; `GET /admin/analytics?period=`.
6. **API Keys** (`#keys`) — generate (`POST /api-keys` with label), list (`GET /api-keys`), delete (`DELETE /api-keys/{id}`). JS: `genKeyBtn`, `loadKeys`.
7. **Admins** (`#admins`, super admin only) — add new admin (username/password/role), list admin users, change password, delete. JS: `loadAdmins`; `POST /admin/users`, `DELETE /admin/users/{id}`, `POST .../change-password`.

Auth helpers: `api(path, options)` wrapper (adds JSON + error handling), `checkAuth()`, `logoutBtn`.

---

## 9. Knowledge Base Content

### 9.1 `n2x_knowledge.txt` (4,610 bytes, full text)
```
N2X System - Software Development Agency

ABOUT US
N2X System is a full-service software development agency headquartered in Lahore, Pakistan. For over a decade we have partnered with startups, SMEs, and enterprises across the globe to design, build, and scale digital products.

10+ Years of Experience | 20+ Clients | 50+ Projects

MISSION: To deliver world-class software products that empower clients to solve real problems, grow faster, and outperform the competition with code that is clean, secure, and built to last.

VISION: To become the most trusted technology partner in South Asia, recognised for our technical excellence, ethical practices, and the transformative impact of every product we ship.

SERVICES
Web Development: Fast, scalable, SEO-optimized web applications using React, Next.js, Laravel, and PHP.
Mobile Apps: Cross-platform iOS and Android apps built with React Native and Flutter.
UI/UX Design: User-centred design from research and wireframing to polished design systems.
eCommerce: End-to-end multi-vendor storefronts with secure payment gateways and inventory management.
Machine Learning and AI: Custom AI models, NLP chatbots, predictive analytics, and automation pipelines.
Cyber Security: Penetration testing, OWASP-compliant code audits, and real-time threat monitoring.
Product Development: Full-cycle product development from ideation and MVP scoping to launch.
Game Development: 2D and 3D games for mobile, web, and desktop using Unity and Unreal Engine.
Quality Assurance: Manual and automated testing across web, mobile, and API layers.
DevOps and Cloud: Docker, Kubernetes, CI/CD pipelines, and AWS/GCP infrastructure management.

PROJECTS

Project 1: CarSharePK - Ridesharing Platform
Pakistan smart car-sharing platform enabling commuters to share rides across the country. Features include real-time ride matching, in-app payments, GPS tracking, Urdu/English bilingual UI, and dedicated driver and passenger portals.
Website: www.carsharepk.com
Technology: Laravel, React Native, MySQL, Google Maps API

Project 2: TrueTrucker - Fleet Management
Modern fleet management SaaS for the US trucking industry. Features OCR-powered document processing, live GPS tracking, driver coordination, revenue analytics, and subscription billing.
Website: www.truetrucker.app
Technology: React, Node.js, PostgreSQL, AWS, OCR AI

Project 3: HMS - Hotel Management
Luxury hotel management platform powering boutique residences across Pakistan. Guests can browse suite availability, make secure online bookings, and order in-suite dining 24/7.
Website: https://assalarestauranthotel.com
Technology: Laravel, Vue.js, MySQL, Stripe, Next.js

Project 4: Digital Tajer - Marketplace
Pakistan multi-vendor marketplace connecting verified sellers and buyers across electronics, fashion, home goods, and industrial supplies.
Website: https://digitaltajer.com
Technology: Laravel, React JS, MySQL, Payment Gateway, Stripe

Project 5: N2X CRM System
Internal CRM and task management platform for managing client projects, team workflows, and business operations.
Website: crm.n2xsystem.com
Technology: PHP, MySQL, Bootstrap, REST API

Project 6: Jabulani Group of Companies
Corporate website for Jabulani Group, a leading South African construction supply company.
Website: jabulanigroupofcompanies.co.za
Technology: React, Node.js, MySQL, AWS

Project 7: Hospital Management System
Comprehensive hospital management platform for patient records, appointments, staff scheduling, billing, and pharmacy management.
Website: https://hospital.n2xsystem.com
Technology: Laravel, React, MySQL, REST API

Project 8: Garage Management System
Modern garage and auto-workshop management system for tracking vehicle service jobs, customer records, spare parts inventory, and invoicing.
Website: https://garage.n2xsystem.com
Technology: Laravel, React, MySQL, REST API

WHY CHOOSE N2X SYSTEM
Decade of Expertise: 10+ years delivering enterprise-grade software across Pakistan and globally.
Global Client Portfolio: Trusted by 20+ clients across logistics, hospitality, eCommerce, and mobility.
Agile Delivery: Weekly sprint updates, always on schedule.
Security First: OWASP-compliant code, penetration tested before launch.
Full-Cycle Development: From wireframes to deployment, one team end to end.
Dedicated Support: Post-launch care, SLA-backed uptime, direct line to engineers.

CONTACT
Website: www.n2xsystem.com
Email: info@n2xsystem.com
Phone: +92 323 452 9766
Address: Plot C 12, Street 195, DHA Phase 1, Lahore 54000
```

### 9.2 `sales_special.txt` (783 bytes, full text — **strictly confidential pricing**)
```
N2X System - Internal Pricing Sheet (Strictly Confidential)

1. MVP (Minimum Viable Product) Development:
   - Fixed Price: $5,000 (up to 4 weeks delivery)
   - Includes: Basic UI, 1 core feature, deployment on cloud.

2. Standard Web Application (React/Laravel):
   - Starting from: $12,000
   - Includes: Custom UI, 3-5 features, database setup, admin panel.

3. Mobile App (React Native/Flutter):
   - Starting from: $10,000 (iOS + Android both included).
   - Add-ons: Push notifications ($1,000), In-app payments ($2,000).

4. Hourly Consulting Rate:
   - $75/hour for senior engineers.

5. Special Discount Policy:
   - 20% off for startups (first project only).
   - 10% off for returning clients.

Sales Team Contact for Negotiations: sales@n2xsystem.com
```

*Note:* `sales_special.txt` is loaded as shared knowledge (and an agent-scoped copy for agent 4). Because it is **retrievable** by the chatbot, its pricing is effectively exposed to users.

---

## 10. Supporting Scripts (`scripts/`)

### 10.1 `reindex_n2x_knowledge.py`
Re-indexes `uploaded_files/n2x_knowledge.txt` (shared, `agent_id=None`) and any `agent_*/n2x_knowledge.txt` copies using the section-aware `chunk_text`; prints each chunk, then embeds + deletes + re-stores in Qdrant. Run from repo root:
```
.\venv\Scripts\python.exe scripts\reindex_n2x_knowledge.py
```

### 10.2 `qdrant_knowledge_base.py`
Inspect (inventory of filenames + chunk counts, optional `--full-text`) or **wipe** (`--wipe --confirm-wipe`) the `knowledge_base` collection. Run:
```
.\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py [--full-text]
.\venv\Scripts\python.exe scripts\qdrant_knowledge_base.py --wipe --confirm-wipe
```

### 10.3 `debug_retrieval.py`
Diagnostic that prints raw Qdrant top-10 results (no `score_threshold`) for three hard-coded Roman-Urdu queries (services, Hospital Management features, "N2X kitne saal se kaam kar raha hai?"), plus embedding dimension. Sets `HF_HUB_OFFLINE=1` to skip the Hugging Face metadata check. Run:
```
.\venv\Scripts\python.exe scripts\debug_retrieval.py
```

---

## 11. Security & Design Review

### What's good
- **PBKDF2-HMAC-SHA256** password hashing (100k iterations, random salt) with constant-time `hmac.compare_digest` comparison — a big improvement over any plaintext.
- **Role-based access control** — `super_admin` vs `admin`; ownership scoping on agents, documents, and handoffs; guardrails against deleting the last admin / last super admin / self.
- HTTP-only, `samesite=lax`, 7-day session cookie; session token from `secrets.token_urlsafe(32)`.
- Migration safety (`_ensure_column` + idempotent backfills) so old DBs upgrade cleanly.
- Graceful fallbacks everywhere: OCR fallback, LLM retries (rate-limit aware, no pointless retry on daily quota / 413), Qdrant-unavailable message, friendly 404 page.

### Issues / things to note
1. **Known placeholder bug (documented in §6.6):** agents 1 & 4 store custom prompts containing `{context}`, `{chat_history}`, `{question}` that `llm.py::generate_answer` never substitutes — those literal strings are sent to Groq. Agent 14 (universal template) is unaffected.
2. **`/chat/messages/{session_id}` is unauthenticated and public** — anyone who knows (or guesses) a `session_id` can read that conversation's full history. Session ids are unguessable random strings, but there is no auth.
3. **CORS wide open** (`allow_origins=["*"]`); combined with the cookie-based admin auth this is fine for the cookie (it's not sent cross-origin without credentials), but API keys / documents endpoints assume same-origin.
4. **`sales_special.txt` (confidential pricing) is retrievable** by any user via the chatbot — an intended feature placement but a confidentiality consideration.
5. **No rate limiting** on `/chat` or `/admin/login` (brute force / abuse possible).
6. `GET /portfolio` returns 404 because `uploaded_files/N2X-System-Portfolio.pdf` does not currently exist.
7. Passwords have a minimum length (`ADMIN_PASSWORD_MIN_LENGTH = 6`) but no other complexity requirement is enforced.
8. `allow_credentials` is not set on CORS (only `allow_origins/methods/headers`), so the admin cookie is not cross-origin readable.

---

## 12. How to Run

1. Install deps (recommended venv):
   ```
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Create `.env` with: `GROQ_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY` (and optional `ADMIN_USERNAME` / `ADMIN_PASSWORD`; defaults `admin` / `change_this_password`).
3. Ensure Qdrant is reachable at `QDRANT_URL`.
4. (Optional) Pre-seed the KB by uploading documents via `/upload` or using `scripts/reindex_n2x_knowledge.py`.
5. Run:
   ```
   .\venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```
   or double-click `.start.bat` (activates venv, opens `http://127.0.0.1:8000`, runs uvicorn).
6. Open `http://127.0.0.1:8000/` for the landing page + widget; `/admin` for the admin panel (login with an admin user); `/chat/{slug}` for a locked agent page.

---

## 13. Summary

The N2X Knowledge Chatbot is a production-style RAG chatbot with a full admin suite. This report documents commit `577c56c` in exhaustive detail: multi-admin roles and agent ownership, per-agent locked chat pages via slugs, PBKDF2 password hashing, OCR fallback for scanned PDFs, contact/heading retrieval boosts, LLM-context truncation, human-handoff + analytics, the unified universal system-prompt template, and the full current runtime DB state (3 agents, 3 admin users, 392 messages, 18 handoffs, 2 API keys, 21 sessions). All backend source is included verbatim, along with the frontend widget and key static pages, plus the knowledge-base content and supporting scripts — so another AI can reproduce or extend the system without inspecting the repository.