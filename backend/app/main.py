import os
import json
import logging
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from app.db import init_db, get_agent_by_slug
from app.routes import upload, chat, admin
from app.services.auth import COOKIE_NAME, is_authenticated

# ---------------------------------------------------------------------------
# Filesystem layout (absolute, CWD-independent)
#
#   <repo>/
#     backend/            <- BASE_DIR (parent of the app package)
#       app/              <- this file lives in app/
#       uploaded_files/
#     frontend/           <- FRONTEND_DIR
#       pages/            <- all served HTML
#       css/
#       js/               <- widget.js (served at /static/widget.js)
# ---------------------------------------------------------------------------
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_APP_DIR)
# PROJECT_ROOT = os.path.dirname(BASE_DIR)
# FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
PAGES_DIR = os.path.join(FRONTEND_DIR, "pages")
JS_DIR = os.path.join(FRONTEND_DIR, "js")
UPLOADED_FILES_DIR = os.path.join(BASE_DIR, "uploaded_files")

PORTFOLIO_PATH = os.path.join(UPLOADED_FILES_DIR, "N2X-System-Portfolio.pdf")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

os.makedirs(UPLOADED_FILES_DIR, exist_ok=True)

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

# The public embed URL is https://<host>/static/widget.js — keep that path
# stable for every site that already embeds the widget. widget.js now lives in
# frontend/js/, so /static is mounted there.
app.mount("/static", StaticFiles(directory=JS_DIR), name="static")


@app.on_event("startup")
def _preload_models():
    """Pre-load the embedding model at startup so the first /chat request is
    not slow (a slow first embed can make the frontend time out and show the
    "server se connect nahi ho paya" network error)."""
    try:
        from app.services.embeddings import _get_model

        _get_model()
        logging.getLogger(__name__).info("Embedding model preloaded")
    except Exception:
        logging.getLogger(__name__).exception(
            "Embedding model failed to preload; will retry lazily on first request"
        )

    # Background thread: reset exhausted Groq API keys every 24 hours so they
    # become usable again without requiring a server restart.
    _start_key_reset_timer()


_KEY_RESET_INTERVAL = 24 * 60 * 60  # 24 hours in seconds


def _start_key_reset_timer():
    """Schedule a periodic reset of exhausted Groq API keys."""
    from app.services.llm import _reset_exhausted_keys

    def _reset_loop():
        while True:
            threading.Event().wait(_KEY_RESET_INTERVAL)
            _reset_exhausted_keys()
            logging.getLogger(__name__).info(
                "Exhausted Groq API keys reset (24h cycle)."
            )

    t = threading.Thread(target=_reset_loop, daemon=True, name="key-reset")
    t.start()
    logging.getLogger(__name__).info(
        "Groq API key auto-reset background task started (every 24h)."
    )


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """Never let an unhandled exception escape as a non-JSON response.

    The chat widget only does ``res.json()``; any HTML error page (500/503
    from a crashing model or an upstream outage) makes ``json()`` throw and
    the UI shows a misleading connection error while the server actually
    responded. Always answer with structured JSON instead."""
    logging.getLogger(__name__).exception(
        "Unhandled exception on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "answer": (
                "Mujhe filhal jawaab dene mein dikkat aa rahi hai. "
                "Thodi der baad dobara try karein ya hamari team se "
                "info@n2xsystem.com par rabta karein."
            ),
            "sources_used": 0,
            "message_id": None,
            "user_message_id": None,
        },
    )


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


AGENT_CHAT_TEMPLATE = _load_template(os.path.join(PAGES_DIR, "agent_chat.html"))


@app.get("/chat/{slug}")
def agent_chat_page(slug: str):
    """Standalone full-page chat for one agent, locked to that agent (no
    dropdown). Missing slugs get a friendly 404 page."""
    agent = get_agent_by_slug(slug.lower())
    if not agent or AGENT_CHAT_TEMPLATE is None:
        return _no_cache_file(
            os.path.join(PAGES_DIR, "agent_404.html"), status_code=404
        )
    payload = {
        "id": agent["id"],
        "name": agent["name"],
        "greeting": agent.get("greeting") or "",
        "slug": agent["slug"],
        "primary_color": agent.get("primary_color") or "#2563EB",
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
    return _no_cache_file(os.path.join(PAGES_DIR, "index.html"))


@app.get("/admin")
def admin_page(request: Request):
    if not is_authenticated(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse(url="/login", status_code=302)
    return _no_cache_file(os.path.join(PAGES_DIR, "admin.html"))


@app.get("/login")
def login_page(request: Request):
    if is_authenticated(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse(url="/admin", status_code=302)
    return _no_cache_file(os.path.join(PAGES_DIR, "login.html"))


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
