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
    list_subscriptions,
    list_payments,
    create_payment,
    list_plans,
    get_plan,
    create_subscription,
    set_subscription_status,
    set_payment_status,
    get_payment,
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
from app.services.subscription_service import (
    enforce_agent_limit,
    enforce_document_limit,
    get_current_subscription,
    SubscriptionError,
)
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
    admin_id, role = get_current_admin(request)
    # Enforce the owner's plan agent-limit. Super admins are not limited by a
    # normal-admin subscription, so the service skips the check for them.
    if role != "super_admin":
        try:
            enforce_agent_limit(admin_id, role)
        except SubscriptionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
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


# ---------------------------------------------------------------------------
# Subscription & payment views (subscription foundation)
# ---------------------------------------------------------------------------

def _scope_admin_id(current_admin_id: int, role: str) -> int | None:
    """Return None for super_admin (see all) or the current admin id for a
    normal admin (see only their own subscription/payments)."""
    if role == "super_admin":
        return None
    return current_admin_id


@router.get("/subscription", dependencies=[Depends(require_admin)])
def my_subscription(request: Request):
    """A normal admin's own current subscription; super admin returns all
    subscriptions. A normal admin can never see another admin's records."""
    admin_id, role = get_current_admin(request)
    if role == "super_admin":
        return {"subscriptions": list_subscriptions()}
    sub = get_current_subscription(admin_id)
    plan = get_plan(sub["plan_id"]) if sub else None
    return {
        "subscription": sub,
        "plan": plan,
    }


@router.get("/subscriptions/{admin_id}", dependencies=[Depends(require_admin)])
def subscription_for_admin(admin_id: int, request: Request):
    """View one admin's subscription history. Super admin may view any admin;
    a normal admin may only view their own."""
    current_admin_id, role = get_current_admin(request)
    if role == "super_admin":
        target = admin_id
    else:
        if admin_id != current_admin_id:
            raise HTTPException(status_code=403, detail="You don't have access to this subscription")
        target = current_admin_id
    subs = list_subscriptions(target)
    plan = None
    current = get_current_subscription(target)
    if current:
        plan = get_plan(current["plan_id"])
    return {"subscriptions": subs, "plan": plan}


@router.get("/payments", dependencies=[Depends(require_admin)])
def payments_view(request: Request):
    """Super admin sees all payments; a normal admin sees only their own."""
    admin_id, role = get_current_admin(request)
    return list_payments(_scope_admin_id(admin_id, role))


@router.get("/payments/{payment_id}", dependencies=[Depends(require_admin)])
def payment_view(payment_id: int, request: Request):
    admin_id, role = get_current_admin(request)
    obj = get_payment(payment_id, admin_id=admin_id, role=role)
    if not obj:
        raise HTTPException(status_code=404, detail="Payment not found")
    return obj


@router.get("/plans", dependencies=[Depends(require_admin)])
def plans_view():
    return {"plans": list_plans(only_active=True)}


@router.post("/payments/initiate", dependencies=[Depends(require_admin)])
def initiate_payment(request: Request, payload: dict | None = None):
    """Foundation-only endpoint: create a pending subscription + payment for
    the caller's chosen plan + provider. It NEVER activates the subscription.

    This is a deliberately minimal scaffold. Real provider integration will:
      1. resolve the pending payment into the provider,
      2. receive a provider callback/webhook,
      3. verify server-side,
      4. then and only then mark payment success and activate the subscription.
    Until that is implemented, callers should use 'manual'/stub providers and
    the subscription stays 'pending'."""
    if payload is None:
        payload = {}
    admin_id, _role = get_current_admin(request)
    plan_id = payload.get("plan_id")
    provider = (payload.get("provider") or "manual").lower()
    if not plan_id:
        raise HTTPException(status_code=400, detail="plan_id is required")
    plan = get_plan(plan_id)
    if not plan or not plan.get("is_active"):
        raise HTTPException(status_code=404, detail="Plan not found or inactive")
    if provider not in ("easypaisa", "jazzcash", "manual"):
        raise HTTPException(status_code=400, detail="Unsupported payment provider")

    # Create a pending subscription and a pending payment. No activation.
    subscription_id = create_subscription(admin_id, plan_id, status="pending")
    payment = create_payment(
        admin_id=admin_id,
        subscription_id=subscription_id,
        provider=provider,
        amount=float(plan["price"] or 0),
        currency=plan["currency"],
        transaction_id=f"txn_{subscription_id}_{plan_id}",
    )
    return {
        "message": "Payment initiated (pending). Subscription will activate only after backend verification.",
        "subscription_id": subscription_id,
        "payment": payment,
    }
