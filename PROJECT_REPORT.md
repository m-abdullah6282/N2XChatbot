# N2X Knowledge Chatbot — Full Project Report

This report is a complete, self-contained description of the `knowledge-chatbot` project. It is written so any AI model or developer can understand the entire codebase without reading the original files. All source code is included verbatim.

---

## 1. Project Overview

**Name:** N2X Knowledge Chatbot (git repo title: `N2XChatbot`)

**Purpose:** A retrieval-augmented generation (RAG) chatbot for **N2X System**, a software development agency in Lahore, Pakistan. Visitors of the N2X website can chat with an AI assistant that answers questions about the company (services, projects, contact info) using both an uploaded knowledge base and general knowledge.

**Key capabilities:**
- Chat widget (embeddable in any page) that talks to a FastAPI backend.
- Upload PDF/TXT documents; they are chunked, embedded, and stored in a Qdrant vector database.
- On each question, the backend embeds the query, searches Qdrant for the 3 most similar text chunks, and sends them as context to a Groq-hosted LLM (Llama 3.3 70B) which writes the final answer.
- Admin panel with login, document upload/delete, chat history viewer, and API-key management.

---

## 2. Tech Stack

| Layer          | Technology                                             |
|----------------|--------------------------------------------------------|
| Web framework  | FastAPI 0.115 + Uvicorn 0.32 (ASGI server)             |
| Data validation| Pydantic 2.9                                           |
| LLM (inference)| Groq API — model `llama-3.3-70b-versatile`             |
| Embeddings     | `sentence-transformers` 3.2.1 — model `all-MiniLM-L6-v2` (384-dim vectors) |
| Vector DB      | Qdrant (cloud) via `qdrant-client` 1.12, cosine distance |
| PDF parsing    | `pypdf` 5.1                                             |
| Relational DB  | SQLite (local file `chatbot.db`)                       |
| Config         | `.env` file via `python-dotenv`                        |
| Frontend       | Plain HTML/CSS/JS (no framework), served as static files |

**Note:** The embedding model is downloaded locally and runs on the same machine as the server (requires the model weights, ~90 MB). Qdrant and Groq are external services accessed over the network.

---

## 3. Directory Structure

```
knowledge-chatbot/
├── .env                    # Secrets (GROQ_API_KEY, QDRANT_URL, QDRANT_API_KEY, ADMIN_USERNAME, ADMIN_PASSWORD)
├── .gitignore
├── README.md               # Only contains the line: "# N2XChatbot"
├── requirements.txt
├── start.bat               # Empty file
├── .start.bat              # Launcher: activates venv, opens browser, runs uvicorn
├── chatbot.db              # SQLite database (runtime)
├── n2x_knowledge.txt       # Company knowledge base (also copied into uploaded_files/)
├── uploaded_files/         # Stored user uploads (PDF/TXT)
│   ├── N2X-System-Portfolio.pdf
│   └── n2x_knowledge.txt
├── venv/                   # Python virtual environment
├── app/
│   ├── __init__.py         # empty
│   ├── config.py           # Loads env vars
│   ├── db.py               # SQLite helpers
│   ├── main.py             # FastAPI app, middleware, page routes
│   ├── models/
│   │   ├── __init__.py     # empty
│   │   └── schemas.py      # Pydantic request models
│   ├── routes/
│   │   ├── __init__.py     # empty
│   │   ├── admin.py        # Admin/API-key/document endpoints
│   │   ├── chat.py         # /chat endpoint
│   │   └── upload.py       # /upload endpoint
│   └── services/
│       ├── __init__.py     # empty
│       ├── auth.py         # Login/session/auth dependency
│       ├── embeddings.py   # SentenceTransformer wrapper
│       ├── llm.py          # Groq prompt + call
│       ├── pdf_processor.py# PDF text extraction + chunking
│       └── vector_store.py # Qdrant operations
└── static/
    ├── index.html          # Empty page that loads the chat widget
    ├── widget.js           # Chat widget (floating launcher + panel)
    ├── admin.html          # Admin panel UI
    └── login.html          # Admin login UI
```

---

## 4. Data Flow

### 4.1 Document ingestion (admin uploads a file)

```
Admin uploads PDF/TXT  ->  /upload (protected by admin cookie)
   -> file saved to uploaded_files/
   -> text extracted (pypdf for PDF, decode for TXT)
   -> text split into chunks (500 chars, 50 overlap)
   -> each chunk embedded (all-MiniLM-L6-v2 -> 384-dim vector)
   -> Qdrant collection "knowledge_base" ensured
   -> old points with same filename deleted
   -> new points upserted (payload: text + filename)
```

### 4.2 Chat (user asks a question)

```
User sends question (+ session_id)  ->  POST /chat
   -> question saved to SQLite messages table (role="user")
   -> question embedded
   -> top-3 chunks retrieved from Qdrant by cosine similarity
   -> chunks joined as "context"
   -> prompt built (company persona, language rule, context, question)
   -> Groq LLM returns answer
   -> answer saved to SQLite messages table (role="assistant")
   -> {question, answer, sources_used} returned to widget
```

### 4.3 Auth (admin login)

```
POST /admin/login  ->  verify username/password vs env vars (hmac.compare_digest)
   -> generate 32-byte url-safe token
   -> store token in SQLite admin_sessions
   -> set httpOnly cookie "n2x_admin" (7-day max age)
All protected routes use Depends(require_admin) which checks the cookie
against the admin_sessions table. Logout deletes the row + cookie.
```

---

## 5. API Endpoints

### Pages (no auth)
| Method | Path      | Description |
|--------|-----------|-------------|
| GET    | `/`        | Serves `static/index.html` (no-cache) |
| GET    | `/admin`   | Serves admin panel if authenticated, else redirect to `/login` |
| GET    | `/login`   | Serves login page, redirects to `/admin` if already authed |
| GET    | `/static/*`| Static files mount |

### Chat
| Method | Path   | Auth | Description |
|--------|--------|------|-------------|
| POST   | `/chat` | None | Body `{question, session_id?}` → `{question, answer, sources_used}` |

### Admin / Auth
| Method | Path                 | Auth (cookie) | Description |
|--------|----------------------|---------------|-------------|
| POST   | `/admin/login`       | – | Body `{username, password}` → sets cookie, `{message}`; 401 on bad creds |
| POST   | `/admin/logout`      | – | Destroys session row + clears cookie |
| GET    | `/admin/check`       | – | `{authenticated: bool}` |
| POST   | `/upload`            | required | Multipart file (PDF/TXT) → embeds into vector DB |
| GET    | `/documents`         | required | List `{filename, size}` of stored files |
| DELETE | `/documents/{filename}` | required | Delete file + its Qdrant points |
| GET    | `/conversations`     | required | All messages ordered by id |
| POST   | `/api-keys`          | required | Body `{label}` → returns new API key |
| GET    | `/api-keys`          | required | List API keys |
| DELETE | `/api-keys/{id}`     | required | Delete API key |

**Note:** There is currently **no endpoint that uses API keys** to authenticate `/chat`. API keys are created/stored but never validated anywhere — they appear to be intended for future programmatic access.

---

## 6. Database Schema (SQLite `chatbot.db`)

Created by `init_db()` on startup.

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
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
```

DB path is computed as `<project root>/chatbot.db`.

---

## 7. Configuration (`.env`)

| Variable         | Description                          | Default if missing |
|------------------|--------------------------------------|--------------------|
| `GROQ_API_KEY`   | API key for Groq LLM                 | (none — app fails at import) |
| `QDRANT_URL`     | Qdrant cloud URL                     | (none)             |
| `QDRANT_API_KEY` | Qdrant cloud API key                 | (none)             |
| `ADMIN_USERNAME` | Admin login username                 | `admin`            |
| `ADMIN_PASSWORD` | Admin login password                 | `change_this_password` |

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
```

### 8.5 `app/main.py`
```python
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from app.db import init_db
from app.routes import upload, chat, admin
from app.services.auth import COOKIE_NAME, is_authenticated

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
```

### 8.6 `app/models/schemas.py`
```python
from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None


class ApiKeyCreate(BaseModel):
    label: str
```

### 8.7 `app/routes/chat.py`
```python
from fastapi import APIRouter

from app.models.schemas import ChatRequest
from app.services.embeddings import generate_embedding
from app.services.vector_store import search_similar_chunks
from app.services.llm import generate_answer
from app.db import save_message

router = APIRouter()


@router.post("/chat")
async def chat(request: ChatRequest):
    if request.session_id:
        save_message(request.session_id, "user", request.question)

    # 1. Embed the question
    query_embedding = generate_embedding(request.question)

    # 2. Search Qdrant for relevant chunks
    relevant_chunks = search_similar_chunks(query_embedding, top_k=3)

    # 3. Combine chunks into context
    context = "\n\n".join(relevant_chunks)

    # 4. Ask LLM
    answer = generate_answer(request.question, context)

    if request.session_id:
        save_message(request.session_id, "assistant", answer)

    return {
        "question": request.question,
        "answer": answer,
        "sources_used": len(relevant_chunks)
    }
```

### 8.8 `app/routes/upload.py`
```python
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
import shutil
import os

from app.services.pdf_processor import extract_text_from_pdf, chunk_text
from app.services.embeddings import generate_embeddings_batch
from app.services.auth import require_admin
from app.services.vector_store import create_collection_if_not_exists, delete_points_by_filename, store_chunks

router = APIRouter()
UPLOAD_DIR = "uploaded_files"
ALLOWED_EXTENSIONS = (".pdf", ".txt")


@router.post("/upload", dependencies=[Depends(require_admin)])
async def upload_pdf(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and TXT files are allowed")

    file_path = os.path.join(UPLOAD_DIR, file.filename)
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
    delete_points_by_filename(file.filename)
    store_chunks(chunks, embeddings, file.filename)

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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.db import (
    get_conversations,
    create_api_key,
    list_api_keys,
    delete_api_key,
)
from app.models.schemas import ApiKeyCreate
from app.services.auth import (
    COOKIE_NAME,
    create_session,
    destroy_session,
    is_authenticated,
    require_admin,
)
from app.services.vector_store import delete_points_by_filename

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
def list_documents():
    files = []
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(path) and name.lower().endswith(ALLOWED_EXTENSIONS):
            files.append({"filename": name, "size": os.path.getsize(path)})
    return files


@router.delete("/documents/{filename}", dependencies=[Depends(require_admin)])
def delete_document(filename: str):
    if not _safe_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(path):
        os.remove(path)

    delete_points_by_filename(filename)
    return {"filename": filename, "message": "Document deleted"}


@router.get("/conversations", dependencies=[Depends(require_admin)])
def conversations():
    return get_conversations()


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

model = SentenceTransformer("all-MiniLM-L6-v2")

def generate_embedding(text: str) -> list[float]:
    embedding = model.encode(text)
    return embedding.tolist()

def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    embeddings = model.encode(texts)
    return embeddings.tolist()
```

### 8.12 `app/services/llm.py`
```python
from groq import Groq
from app.config import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)
COMPANY_NAME = "N2X System"
def generate_answer(question: str, context: str) -> str:
    prompt = f"""You are {COMPANY_NAME}'s friendly chat assistant. Follow these rules:

1. Reply in the SAME language the user writes in. If the user writes in Roman Urdu/Hindi, reply in Roman Urdu/Hindi. If they write in English, reply in English.
2. Be friendly, warm and conversational. Greet naturally.
3. Use emojis naturally in your replies to make the chat feel lively. 😊
4. Answer using the context below whenever it is relevant. You can also use general knowledge about {COMPANY_NAME} as a software development agency (services, projects, contact info).
5. If you genuinely cannot help, politely say so in the user's language and suggest asking about N2X System's services or projects.
6. Keep answers short and to the point (2-4 sentences max).

Context:
{context}

Question: {question}

Answer:"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    return response.choices[0].message.content
```

### 8.13 `app/services/pdf_processor.py`
```python
from pypdf import PdfReader

def extract_text_from_pdf(file_path: str) -> str:
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap

    return chunks
```

### 8.14 `app/services/vector_store.py`
```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter, FieldCondition,
    MatchValue, FilterSelector, PayloadSchemaType,
)
import uuid
from app.config import QDRANT_URL, QDRANT_API_KEY

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

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

def ensure_filename_index():
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="filename",
        field_schema=PayloadSchemaType.KEYWORD,
    )

def store_chunks(chunks: list[str], embeddings: list[list[float]], filename: str):
    points = []
    for chunk, embedding in zip(chunks, embeddings):
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={"text": chunk, "filename": filename}
        )
        points.append(point)

    client.upsert(collection_name=COLLECTION_NAME, points=points)

def delete_points_by_filename(filename: str):
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(
                must=[FieldCondition(key="filename", match=MatchValue(value=filename))]
            )
        ),
    )

def search_similar_chunks(query_embedding: list[float], top_k: int = 3) -> list[str]:
    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        limit=top_k
    )
    return [result.payload["text"] for result in results]
```

### 8.15 `static/index.html`
```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<title>N2X Chat Assistant</title>
<script src="/static/widget.js"></script>
</head>
<body>
</body>
</html>
```

### 8.16 `static/widget.js` (chat widget)
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
    "#n2x-widget { position: fixed; bottom: 20px; right: 20px; z-index: 999999; font-size: 14px; }" +
    "#n2x-launcher { width: 60px; height: 60px; border-radius: 50%; border: none; cursor: pointer; background: #2563eb; color: #fff; box-shadow: 0 4px 16px rgba(37, 99, 235, 0.4); display: flex; align-items: center; justify-content: center; transition: transform 0.15s ease; }" +
    "#n2x-launcher:hover { transform: scale(1.08); }" +
    "#n2x-panel { position: fixed; bottom: 92px; right: 20px; width: 360px; max-width: calc(100vw - 40px); height: 520px; max-height: calc(100vh - 120px); background: #fff; border-radius: 14px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25); display: flex; flex-direction: column; overflow: hidden; border: 1px solid #e5e7eb; }" +
    "#n2x-panel.hidden { display: none; }" +
    "#n2x-header { background: #2563eb; color: #fff; padding: 14px 16px; display: flex; align-items: center; gap: 10px; }" +
    "#n2x-header .dot { width: 9px; height: 9px; border-radius: 50%; background: #34d399; }" +
    "#n2x-header .title { font-weight: 600; flex: 1; }" +
    "#n2x-close { background: none; border: none; color: #fff; font-size: 20px; cursor: pointer; line-height: 1; }" +
    "#n2x-messages { flex: 1; overflow-y: auto; padding: 16px; background: #f9fafb; display: flex; flex-direction: column; gap: 10px; }" +
    "#n2x-messages .msg { max-width: 80%; padding: 10px 12px; border-radius: 12px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }" +
    "#n2x-messages .msg.user { align-self: flex-end; background: #2563eb; color: #fff; border-bottom-right-radius: 3px; }" +
    "#n2x-messages .msg.bot { align-self: flex-start; background: #fff; color: #111; border: 1px solid #e5e7eb; border-bottom-left-radius: 3px; }" +
    "#n2x-messages .msg.typing { color: #6b7280; font-style: italic; }" +
    "#n2x-input-row { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e5e7eb; background: #fff; }" +
    "#n2x-input { flex: 1; border: 1px solid #d1d5db; border-radius: 8px; padding: 10px 12px; font-size: 14px; outline: none; }" +
    "#n2x-input:focus { border-color: #2563eb; }" +
    "#n2x-send { background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 0 18px; font-size: 14px; font-weight: 600; cursor: pointer; }" +
    "#n2x-send:hover { background: #1d4ed8; }" +
    "@media (max-width: 480px) { #n2x-panel { right: 10px; bottom: 80px; width: calc(100vw - 20px); } }";

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
    '    <span class="title">N2X Chat Assistant</span>' +
    '    <button id="n2x-close" aria-label="Close chat">&times;</button>' +
    "  </div>" +
    '  <div id="n2x-messages"><div class="msg bot">Hello! Main aapki kaise madad kar sakta hoon?</div></div>' +
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

  function openPanel() {
    panel.classList.remove("hidden");
    inputEl.focus();
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function closePanel() {
    panel.classList.add("hidden");
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

    try {
      var res = await fetch(API_BASE + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, session_id: sessionId }),
      });
      var data = await res.json();
      typingEl.classList.remove("typing");
      typingEl.textContent = data.answer || "Koi answer nahi mila.";
    } catch (err) {
      typingEl.classList.remove("typing");
      typingEl.textContent = "Error: server se connect nahi ho paya.";
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  sendBtn.addEventListener("click", sendQuestion);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") sendQuestion();
  });
})();
```

**How to embed:** any page can include `<script src="/static/widget.js"></script>` and optionally set `window.N2XChatConfig = { apiBase: "https://your-server" }` before the script. The session id is stored in `localStorage` under `n2x_session_id` and sent with every chat message to group conversations.

### 8.17 `static/login.html` (abbreviated summary)
- Centered login card, fields: username + password.
- On submit: `POST /admin/login` with JSON body; on success redirects to `/admin`; on failure shows error message (UI text is in Roman Urdu).
- Link "Waps site par" (back to site) → `/`.

### 8.18 `static/admin.html` (abbreviated summary)
- Header with "Back to site" and "Logout" buttons; logout calls `POST /admin/logout` then redirects to `/login`.
- On load calls `GET /admin/check`; if not authenticated, redirects to `/login`.
- Three tabs:
  1. **Knowledge Base**: drag-and-drop or click-to-select PDF/TXT upload → `POST /upload`. Lists uploaded docs (`GET /documents`) with size and a Delete button (`DELETE /documents/{filename}`).
  2. **Chat History**: groups `GET /conversations` rows by `session_id`, renders each message with role label (User:/Bot:) and timestamp.
  3. **API Keys**: create key with a client label (`POST /api-keys`), shows the generated key; lists existing keys (`GET /api-keys`) with delete buttons (`DELETE /api-keys/{id}`).
- The `api()` helper redirects to `/login` on HTTP 401.
- UI copy is a mix of English and Roman Urdu.

---

## 9. Knowledge Base Content (`n2x_knowledge.txt`)

This is the primary knowledge document about the company:

- **About:** N2X System, full-service software agency in Lahore, Pakistan. 10+ years, 20+ clients, 50+ projects. Mission and vision statements.
- **Services (10):** Web Development (React, Next.js, Laravel, PHP), Mobile Apps (React Native, Flutter), UI/UX Design, eCommerce, Machine Learning & AI, Cyber Security, Product Development, Game Development (Unity, Unreal), Quality Assurance, DevOps & Cloud (Docker, K8s, CI/CD, AWS/GCP).
- **Projects (8):**
  1. CarSharePK — ridesharing (Laravel, React Native, MySQL, Google Maps)
  2. TrueTrucker — fleet management SaaS (React, Node.js, PostgreSQL, AWS, OCR AI)
  3. HMS — hotel management (Laravel, Vue.js, MySQL, Stripe, Next.js)
  4. Digital Tajer — multi-vendor marketplace (Laravel, React, MySQL, Stripe)
  5. N2X CRM System (PHP, MySQL, Bootstrap, REST API)
  6. Jabulani Group of Companies — corporate site (React, Node.js, MySQL, AWS)
  7. Hospital Management System (Laravel, React, MySQL, REST API)
  8. Garage Management System (Laravel, React, MySQL, REST API)
- **Why choose:** decade of expertise, global portfolio, agile delivery, security first, full-cycle dev, dedicated support.
- **Contact:** www.n2xsystem.com · info@n2xsystem.com · +92 323 452 9766 · Plot C 12, Street 195, DHA Phase 1, Lahore 54000.

A duplicate copy of this file is present in `uploaded_files/`, and a `N2X-System-Portfolio.pdf` (7.7 MB) is also uploaded.

---

## 10. Security & Design Review

### What's good
- Credential comparison uses `hmac.compare_digest` (timing-attack resistant).
- Session tokens are `secrets.token_urlsafe(32)` — cryptographically random.
- Auth cookie is `httpOnly` and `SameSite=Lax` with 7-day expiry; sessions stored server-side (can be revoked).
- Upload extension whitelist and `_safe_filename` guard against path traversal on document delete.
- SQL uses parameterized queries everywhere (SQL-injection safe).
- PDF/TXT-only upload prevents arbitrary file execution.

### Issues / things to note
1. **API keys are unused.** They are generated/stored/listed/deleted but never checked anywhere — `/chat` has no authentication at all. Likely intended for a future programmatic API.
2. **Secrets are checked into the working tree.** `.env` is git-ignored (good), but `ADMIN_PASSWORD` defaults to `change_this_password` if unset (bad default).
3. **CORS is wide open** (`allow_origins=["*"]`) — the chat endpoint is intentionally public, but combined with `/chat` being unauthenticated, the widget can be embedded anywhere.
4. **No rate limiting** on `/chat` — a public endpoint with paid LLM calls (Groq). Abuse could rack up cost.
5. **Upload filename collisions:** `file.filename` is used directly to write to `uploaded_files/`. If an admin uploads two different files with the same name, the second overwrites the first (and replaces its vector points). Not a security hole behind auth, but worth knowing.
6. **No file size limit** on uploads.
7. **Session token stored in plaintext** in SQLite — acceptable for this scope, but a hash would be better practice.
8. **`delete_points_by_filename` is called on upload path even before the collection may exist** — the order in upload.py calls `create_collection_if_not_exists()` before deleting, so it is safe as written.
9. **The `embedding model` download at import time:** `SentenceTransformer("all-MiniLM-L6-v2")` runs at module import, so the server takes time to start on first run and needs network to download weights.
10. **No source attribution to the user:** the response includes `sources_used` (count) but not the actual source filenames.
11. **`start.bat` is empty**; the real launcher is `.start.bat` (hidden file). `README.md` contains only `# N2XChatbot`.
12. **Chunking is naive:** fixed 500-char slices with 50-char overlap, no sentence-boundary awareness.

---

## 11. How to Run

```bat
cd /d D:\N2X\knowledge-chatbot
venv\Scripts\activate
uvicorn app.main:app --reload
```
Then open http://127.0.0.1:8000 (or use `.start.bat` which does this automatically and opens the browser).

**Preconditions:**
- Python venv with `pip install -r requirements.txt`.
- `.env` populated with valid `GROQ_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, and admin credentials.
- Qdrant cloud instance reachable; the embedding model will download on first run.

---

## 12. Summary

This is a compact, well-structured RAG chatbot. The FastAPI backend cleanly separates routes, services, and models. The retrieval pipeline (embed → search → prompt → LLM) is straightforward and easy to extend. Main outstanding work: wiring the API-key system into `/chat`, adding rate limiting, and tightening CORS/upload-size defaults before production.
