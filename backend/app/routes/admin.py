import os
import re
import shutil
import sqlite3
from urllib.parse import quote as urllib_parse_quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import WHATSAPP_BUSINESS_NUMBER
from app.db import (
    get_conversations,
    get_conversations_for_admin,
    get_conversations_summary,
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
    resolve_api_key,
    create_agent,
    get_agent,
    get_agent_by_slug,
    list_agents,
    update_agent,
    delete_agent,
    get_pending_handoffs,
    get_handoff,
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
    list_all_plans,
    get_plan,
    get_plan_by_name,
    update_plan,
    create_subscription,
    set_subscription_status,
    set_payment_status,
    get_payment,
    get_admin_activity_overview,
)
from app.models.schemas import (
    ApiKeyCreate,
    AgentCreate,
    AgentUpdate,
    PlanUpdate,
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
# Absolute path to <repo>/backend/uploaded_files (CWD-independent).
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "uploaded_files",
)
ALLOWED_EXTENSIONS = (".pdf", ".txt")


class LoginRequest(BaseModel):
    username: str
    password: str


def _safe_filename(filename: str) -> bool:
    if os.path.basename(filename) != filename:
        return False
    return filename.lower().endswith(ALLOWED_EXTENSIONS)


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _validate_color(color: str | None) -> str:
    """Validate a hex color (#RRGGBB). Returns a normalized lowercase hex, or
    the default when None/empty. Raises 400 on an invalid value."""
    if color is None or str(color).strip() == "":
        return "#2563EB"
    value = str(color).strip()
    if not _HEX_COLOR_RE.match(value):
        raise HTTPException(
            status_code=400, detail="Color must be a valid hex code like #2563EB"
        )
    return value.lower()


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
def conversations(request: Request, session_id: str | None = None):
    """Conversation messages scoped by role:
    - Super admin: every conversation across all admins/agents.
    - Normal admin: only conversations on agents they own.
    Cross-admin access is blocked at the query level, never by hiding rows.
    An optional session_id narrows the feed to a single conversation so the
    admin UI can expand a history row into its full thread."""
    admin_id, role = get_current_admin(request)
    rows = get_conversations() if role == "super_admin" else get_conversations_for_admin(admin_id)
    if session_id:
        rows = [r for r in rows if r["session_id"] == session_id]
    return rows


@router.get("/admin/live-chats", dependencies=[Depends(require_admin)])
def live_chats(request: Request):
    """Live chat monitoring summaries. The mechanism is efficient polling of
    the persisted conversation table (there is no WebSocket/SSE infra in this
    project), refreshed on demand. Super admin sees all admins/agents; a normal
    admin sees only their own agents' chats."""
    admin_id, role = get_current_admin(request)
    return {
        "chats": get_conversations_summary(admin_id, role),
        "mechanism": "polling",
    }


@router.get("/chat-history", dependencies=[Depends(require_admin)])
def chat_history(request: Request):
    """Chat history summaries for the history tab, showing agent + conversation
    + last message. Same role scoping as /conversations."""
    admin_id, role = get_current_admin(request)
    return get_conversations_summary(admin_id, role)


@router.get("/admin/handoffs", dependencies=[Depends(require_admin)])
def handoffs(request: Request):
    admin_id, role = get_current_admin(request)
    return get_pending_handoffs(admin_id, role)


@router.post("/admin/handoffs/{session_id}/reply", dependencies=[Depends(require_admin)])
def reply_to_handoff(session_id: str, req: HandoffReply):
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    handoff = get_handoff(session_id)
    agent_id = handoff["agent_id"] if handoff else None
    save_message(session_id, "assistant", message, was_fallback=0, agent_id=agent_id)
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
def create_key(req: ApiKeyCreate, request: Request):
    admin_id, role = get_current_admin(request)
    if req.agent_id is None:
        raise HTTPException(status_code=400, detail="agent_id is required: every API key must be bound to an agent")
    agent = get_agent(req.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if role != "super_admin" and agent.get("owner_admin_id") != admin_id:
        raise HTTPException(status_code=403, detail="You don't have access to this agent")
    agent_id = agent["id"]
    owner_admin_id = admin_id if role != "super_admin" else (agent.get("owner_admin_id") or admin_id)
    api_key = create_api_key(req.label, admin_id=owner_admin_id, agent_id=agent_id)
    return {"api_key": api_key, "label": req.label, "agent_id": agent_id, "message": "API key created"}


@router.get("/api-keys", dependencies=[Depends(require_admin)])
def list_keys(request: Request, agent_id: int | None = None):
    admin_id, role = get_current_admin(request)
    return list_api_keys(admin_id=admin_id, role=role, agent_id=agent_id)


@router.delete("/api-keys/{key_id}", dependencies=[Depends(require_admin)])
def delete_key(key_id: int, request: Request):
    admin_id, role = get_current_admin(request)
    if not delete_api_key(key_id, admin_id=admin_id, role=role):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"message": "API key deleted"}


@router.get("/agents")
def list_agents_public_or_admin(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not is_authenticated(token):
        return [
            {
                "id": a["id"], "name": a["name"], "greeting": a["greeting"],
                "slug": a["slug"], "primary_color": a.get("primary_color") or "#2563EB",
            }
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
            primary_color=_validate_color(req.primary_color),
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
            primary_color=_validate_color(req.primary_color),
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

    # Optional plan selection supplied by the UI. The current business flow
    # does NOT let a Super Admin assign a paid plan at creation time, so the
    # plan_id is validated (never blindly trusted) but does not change the
    # subscription assignment: a new admin always receives the active Free
    # plan. Paid plans are purchased later by the admin through their own
    # /payments/initiate flow, which only ever creates pending subscriptions.
    selected_plan = None
    if req.plan_id is not None:
        selected_plan = get_plan(req.plan_id)
        if not selected_plan or not selected_plan.get("is_active"):
            raise HTTPException(
                status_code=404, detail="Plan not found or inactive"
            )
        # Only the default Free plan may be assigned in this flow. Any other
        # selection is rejected so we never create an unintended paid
        # subscription from a frontend selection.
        if selected_plan["name"] != "Free":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Paid plans cannot be assigned at admin creation. "
                    "New admins receive the Free plan; paid plans are "
                    "activated by the admin through their own billing flow."
                ),
            )

    try:
        admin = create_admin_user(username, req.password, role)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="A user with this username already exists")

    # Augment the response (non-breaking) with the active subscription + plan
    # so the UI/tests can confirm the default assignment.
    try:
        sub = get_current_subscription(admin["id"])
        plan = get_plan(sub["plan_id"]) if sub else None
        admin["subscription"] = {
            "status": sub["status"] if sub else None,
            "plan_id": sub["plan_id"] if sub else None,
            "plan_name": plan["name"] if plan else None,
        }
    except Exception:
        pass
    return admin


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
        "whatsapp": {
            "number": WHATSAPP_BUSINESS_NUMBER,
        },
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


@router.get("/upgrade/whatsapp", dependencies=[Depends(require_admin)])
def upgrade_whatsapp(request: Request):
    """Return the prefilled WhatsApp upgrade link for the current admin.

    Upgrade is a manual contact flow: the admin clicks a link that opens
    WhatsApp to the company's business number with a prefilled message (admin
    name, email, current plan, request). NO subscription is changed or
    activated by this endpoint or by opening the link — payment/verification
    happens entirely outside the system and a Super Admin manually assigns the
    plan later."""
    admin_id, role = get_current_admin(request)
    if role == "super_admin":
        raise HTTPException(status_code=400, detail="Super admins do not upgrade")
    admin = get_admin_user(admin_id)
    sub = get_current_subscription(admin_id)
    plan = get_plan(sub["plan_id"]) if sub else None
    if not WHATSAPP_BUSINESS_NUMBER:
        return {
            "whatsapp_number": None,
            "wa_link": None,
            "message": "WhatsApp upgrade is not configured yet. Please contact support.",
        }
    plan_name = (plan or {}).get("name") or "Free"
    user_name = (admin or {}).get("username") or "Admin"
    email = (admin or {}).get("username") or "n/a"
    text = (
        f"Hi, I would like to upgrade my N2X subscription.\n"
        f"Name: {user_name}\n"
        f"Email: {email}\n"
        f"Current plan: {plan_name}\n"
        f"Request: Please upgrade my plan. Thank you."
    )
    wa_number = WHATSAPP_BUSINESS_NUMBER.lstrip("+").replace(" ", "")
    link = f"https://wa.me/{wa_number}?text={urllib_parse_quote(text)}"
    return {
        "whatsapp_number": WHATSAPP_BUSINESS_NUMBER,
        "wa_link": link,
        "message": text,
        "plan": plan,
        "current_admin": user_name,
    }


@router.post("/admin/subscriptions/{admin_id}/activate", dependencies=[Depends(require_super_admin)])
def admin_activate_subscription(admin_id: int, request: Request, payload: dict | None = None):
    """Super Admin manually activates a plan for an admin.

    This is the ONLY place a paid/plan subscription is activated (payment and
    verification happen outside the system; the super admin does it manually).

    Behaviour:
    - deactivates any previously effective 'active' subscription for the admin
      so only ONE active subscription controls limits;
    - preserves full subscription history (past rows are never deleted);
    - Lifetime never expires (end=NULL);
    - Monthly/Yearly set appropriate start/end dates;
    - Free uses existing defaults.

    Normal admins are blocked (403) by require_super_admin and cannot
    self-assign plans."""
    if payload is None:
        payload = {}
    plan_id = payload.get("plan_id")
    if not plan_id:
        raise HTTPException(status_code=400, detail="plan_id is required")
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if not plan.get("is_active"):
        raise HTTPException(status_code=400, detail="Plan is not active")
    if not get_admin_user(admin_id):
        raise HTTPException(status_code=404, detail="Admin user not found")

    # Deactivate any currently-effective active subscription so at most one
    # active subscription controls limits at a time.
    from app.db import get_current_subscription as _gcs
    current = _gcs(admin_id)
    if current and current.get("status") == "active":
        set_subscription_status(current["id"], "past")

    billing = plan.get("billing_interval") or "monthly"
    if billing == "lifetime":
        start, end = "datetime('now')", "datetime('now', '+1000 years')"
    elif billing == "yearly":
        start, end = "datetime('now')", "datetime('now', '+1 year')"
    else:  # monthly / free
        start, end = "datetime('now')", "datetime('now', '+30 days')"

    sub_id = create_subscription(
        admin_id, plan_id, status="active", current_period_start=start, current_period_end=end
    )
    return {"message": "Subscription activated", "subscription_id": sub_id, "plan": plan}


@router.get("/admin/subscriptions", dependencies=[Depends(require_super_admin)])
def admin_subscriptions(request: Request):
    """Super Admin dashboard view: every admin with their current plan, status,
    start/expiry dates, so subscriptions can be managed."""
    admins = list_admin_users()
    result = []
    for a in admins:
        current = get_current_subscription(a["id"])
        plan = get_plan(current["plan_id"]) if current else None
        result.append(
            {
                "admin_id": a["id"],
                "username": a["username"],
                "role": a["role"],
                "plan_id": (plan or {}).get("id"),
                "plan_name": (plan or {}).get("name"),
                "status": (current or {}).get("status"),
                "start_date": (current or {}).get("current_period_start"),
                "expiry_date": (current or {}).get("current_period_end"),
                "subscription_id": (current or {}).get("id"),
            }
        )
    return {"subscriptions": result, "plans": list_plans(only_active=True)}


@router.get("/admin/activity", dependencies=[Depends(require_super_admin)])
def admin_activity_overview():
    """Super Admin dashboard: per-admin activity overview with agent count,
    conversations, messages, handoffs, documents, and last activity time."""
    return {"admins": get_admin_activity_overview()}


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


@router.get("/admin/plans", dependencies=[Depends(require_super_admin)])
def admin_plans_view():
    """Super Admin plan-management list (includes inactive plans + the
    editable new fields). Normal admins get a 403 from require_super_admin."""
    return {"plans": list_all_plans()}


@router.put("/admin/plans/{plan_id}", dependencies=[Depends(require_super_admin)])
def admin_plan_update(plan_id: int, req: PlanUpdate, request: Request):
    """Super Admin updates a plan's configurable fields.

    Unlimited checkbox behavior:
    - unchecked -> max_* must be a positive integer, DB stores the integer.
    - checked   -> the corresponding max_* is stored as NULL (unlimited).

    Normal admins are blocked by require_super_admin."""
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Plan name is required")
    if name != plan["name"]:
        exists = get_plan_by_name(name)
        if exists and exists["id"] != plan_id:
            raise HTTPException(status_code=400, detail="A plan with this name already exists")

    fields: dict = {"name": name, "price": float(req.price or 0)}
    fields["unlimited_ai_agents"] = req.unlimited_ai_agents
    if req.unlimited_ai_agents:
        fields["max_agents"] = None
    else:
        if req.max_ai_agents is None or int(req.max_ai_agents) <= 0:
            raise HTTPException(
                status_code=400,
                detail="max_ai_agents must be a positive integer when unlimited is off",
            )
        fields["max_agents"] = int(req.max_ai_agents)

    fields["unlimited_support_agents"] = req.unlimited_support_agents
    if req.unlimited_support_agents:
        fields["max_support_agents"] = None
    else:
        if req.max_support_agents is None or int(req.max_support_agents) <= 0:
            raise HTTPException(
                status_code=400,
                detail="max_support_agents must be a positive integer when unlimited is off",
            )
        fields["max_support_agents"] = int(req.max_support_agents)

    fields["is_active"] = 1 if req.is_active else 0

    fields["unlimited_documents"] = req.unlimited_documents
    if req.unlimited_documents:
        fields["max_documents"] = None
    elif req.max_documents is not None:
        fields["max_documents"] = int(req.max_documents)

    fields["unlimited_messages"] = req.unlimited_messages
    if req.unlimited_messages:
        fields["max_messages_per_period"] = None
    elif req.max_messages_per_period is not None:
        fields["max_messages_per_period"] = int(req.max_messages_per_period)

    if not update_plan(plan_id, fields):
        raise HTTPException(status_code=404, detail="Plan not found")
    return get_plan(plan_id)


@router.get("/admin/plans/{plan_id}", dependencies=[Depends(require_super_admin)])
def admin_plan_get(plan_id: int, request: Request):
    plan = get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


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
