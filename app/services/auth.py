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
