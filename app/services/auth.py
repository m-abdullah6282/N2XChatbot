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
