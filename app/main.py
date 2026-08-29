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
