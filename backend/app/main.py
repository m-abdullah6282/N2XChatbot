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

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_APP_DIR)
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
PAGES_DIR = os.path.join(FRONTEND_DIR, "pages")
JS_DIR = os.path.join(FRONTEND_DIR, "js")
UPLOADED_FILES_DIR = os.path.join(BASE_DIR, "uploaded_files")

PORTFOLIO_PATH = os.path.join(UPLOADED_FILES_DIR, "N2X-System-Portfolio.pdf")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

os.makedirs(UPLOADED_FILES_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Schema init (Postgres).
#
# Runs at import time so every worker/process has tables + seeds before the
# first request. Wrapped so a bad DATABASE_URL surfaces as ONE clear error
# instead of a psycopg stack trace — fail fast on Render rather than boot
# into a broken state.
# ---------------------------------------------------------------------------
try:
    init_db()
except Exception as exc:
    logger.error(
        "init_db() failed — the app cannot start. Check DATABASE_URL "
        "(backend/.env for local dev, or the deployment environment on Render). "
        "Original error: %s: %s",
        type(exc).__name__,
        exc,
    )
    raise

app = FastAPI(title="Knowledge Base Chatbot")

# ---------------------------------------------------------------------------
# CORS.
#
# Default is wide-open ("*") to preserve existing behaviour, but this can be
# locked down with CORS_ORIGINS (comma-separated) — e.g.
#   CORS_ORIGINS=https://app.example.com,https://admin.example.com
# ---------------------------------------------------------------------------
_cors_raw = os.getenv("CORS_ORIGINS", "*").strip()
CORS_ORIGINS = ["*"] if _cors_raw in ("", "*") else [o.strip() for o in _cors_raw.split(",") if o.strip()]
if CORS_ORIGINS == ["*"]:
    logger.warning(
        "CORS is wide-open (allow_origins=['*']). Set CORS_ORIGINS to your "
        "real origins before production."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(chat.router)
app.include_router(admin.router)

app.mount("/static", StaticFiles(directory=JS_DIR), name="static")


@app.on_event("startup")
def _preload_models():
    # 1. Groq key auto-reset loop (independent, background).
    _start_key_reset_timer()

    # 2. Warn if the bootstrap admin password is still the known default.
    from app.config import ADMIN_PASSWORD
    if ADMIN_PASSWORD == "change_this_password":
        logger.warning(
            "ADMIN_PASSWORD is still the default 'change_this_password' - "
            "set ADMIN_USERNAME / ADMIN_PASSWORD in the environment."
        )

    # 3. Confirm the Postgres pool actually connects before accepting traffic.
    #    (init_db() already ran at import — this is a belt-and-braces check
    #     that also logs a clear "DB ready" line for the deploy logs.)
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
        logger.info("Postgres connection verified at startup.")
    except Exception:
        logger.exception(
            "Postgres is unreachable at startup — check DATABASE_URL and the "
            "database service on Render."
        )
        raise

    # 4. Warm up embeddings + Qdrant in the background so the port binds
    #    immediately (Render health check) while the ~90MB model download
    #    happens off-thread. Without this the FIRST chat paid the download
    #    cost and could time out.
    threading.Thread(target=_warm_up, daemon=True, name="warm-up").start()


# Import here (not at module top) so the DB context manager is available
# inside _preload_models without a circular import worry.
from app.db import get_conn  # noqa: E402


def _warm_up():
    try:
        from app.services import embeddings

        embeddings.preload()
    except Exception:
        logger.exception("Embedding model preload failed (will retry on first chat)")
    try:
        from app.services.vector_store import create_collection_if_not_exists

        create_collection_if_not_exists()
        logger.info("Qdrant collection ready.")
    except Exception:
        logger.exception("Qdrant is unreachable at startup - check QDRANT_URL / API key / cluster status")


_KEY_RESET_INTERVAL = 24 * 60 * 60


def _start_key_reset_timer():
    from app.services.llm import _reset_exhausted_keys

    def _reset_loop():
        while True:
            threading.Event().wait(_KEY_RESET_INTERVAL)
            _reset_exhausted_keys()
            logger.info("Exhausted Groq API keys reset (24h cycle).")

    t = threading.Thread(target=_reset_loop, daemon=True, name="key-reset")
    t.start()
    logger.info("Groq API key auto-reset background task started (every 24h).")


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    logger.exception(
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
    # Escape "<" so an agent name/greeting containing "</script>" cannot break
    # out of the inline <script> block (stored XSS).
    safe_json = json.dumps(payload).replace("<", "\\u003c")
    html = (
        AGENT_CHAT_TEMPLATE
        .replace("__AGENT_NAME__", _html_escape(agent["name"]))
        .replace("__AGENT_JSON__", safe_json)
    )
    return HTMLResponse(html, headers={
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
    })


@app.get("/healthz")
def healthz():
    """Cheap liveness probe for Render's health check (no external calls)."""
    return {"status": "ok"}


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