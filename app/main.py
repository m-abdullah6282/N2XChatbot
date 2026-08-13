import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from app.db import init_db
from app.routes import upload, chat, admin
from app.services.auth import COOKIE_NAME, is_authenticated

PORTFOLIO_PATH = "uploaded_files/N2X-System-Portfolio.pdf"

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
