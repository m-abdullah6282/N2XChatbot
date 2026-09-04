"""Central subscription & plan-limit logic.

All plan/subscription/limit decisions live here so routes never copy-paste
business rules. The service is the single place that reads plan limits from
the database (plans are NOT hard-coded into business logic).

- Super admins are NOT limited by a normal-admin subscription (they manage the
  platform and are not a paying subscriber in the same sense).
- Normal admins must have an active subscription; their plan limits are read
  from the plans table.
"""

import sqlite3
from typing import Optional

from app.db import (
    get_current_subscription,
    get_plan,
    count_documents_for_admin,
    list_agents,
)

ACTIVE_SUBSCRIPTION_STATUSES = ("active",)


class SubscriptionError(Exception):
    """Raised when an action is blocked by a subscription or plan limit."""

    def __init__(self, message: str, code: str = "subscription_error"):
        super().__init__(message)
        self.code = code


def _current_plan_and_subscription(admin_id: int):
    sub = get_current_subscription(admin_id)
    plan = get_plan(sub["plan_id"]) if sub else None
    return sub, plan


def get_admin_plan(admin_id: int) -> Optional[dict]:
    _, plan = _current_plan_and_subscription(admin_id)
    return plan


def is_subscription_active(admin_id: int) -> bool:
    sub = get_current_subscription(admin_id)
    return bool(sub and sub.get("status") in ACTIVE_SUBSCRIPTION_STATUSES)


def _require_active_subscription(admin_id: int, role: str):
    """Normal admins must have an active subscription to use their quota."""
    if role == "super_admin":
        return
    if not is_subscription_active(admin_id):
        raise SubscriptionError(
            "No active subscription. A paid subscription is required.",
            code="no_active_subscription",
        )


def can_create_agent(admin_id: int, role: str = "admin") -> bool:
    """Whether a normal admin is within their agent count limit."""
    if role == "super_admin":
        return True
    _require_active_subscription(admin_id, role)
    _sub, plan = _current_plan_and_subscription(admin_id)
    if not plan:
        return False
    if plan.get("unlimited_ai_agents") or plan.get("max_agents") is None:
        return True
    return len(list_agents(admin_id=admin_id)) < plan["max_agents"]


def enforce_agent_limit(admin_id: int, role: str = "admin") -> None:
    """Raise SubscriptionError when a normal admin is at/over their max_agents."""
    if role == "super_admin":
        return
    _require_active_subscription(admin_id, role)
    _sub, plan = _current_plan_and_subscription(admin_id)
    if not plan:
        raise SubscriptionError("No plan assigned.", code="no_plan")
    if plan.get("unlimited_ai_agents") or plan.get("max_agents") is None:
        return
    max_agents = int(plan["max_agents"])
    if len(list_agents(admin_id=admin_id)) >= max_agents:
        raise SubscriptionError(
            f"Agent limit reached ({max_agents}). Upgrade your plan to add more agents.",
            code="agent_limit_reached",
        )


def enforce_support_agent_limit(admin_id: int, role: str = "admin") -> None:
    """Runtime enforcement for the Support Agent limit.

    The Support Agent feature does NOT exist in this project yet (there is no
    support_agents table or creation flow). The plan fields
    UNLIMITED_SUPPORT_AGENTS / MAX_SUPPORT_AGENTS are stored and configurable by
    the Super Admin, but there is no support-agent object to count. This function
    is a documented placeholder: it currently allows the action ALWAYS, so that
    when a real Support Agent feature is added, the enforcing call can be wired
    in here without changing route logic. It never invented a fake support
    system."""
    if role == "super_admin":
        return
    _require_active_subscription(admin_id, role)
    _sub, plan = _current_plan_and_subscription(admin_id)
    if not plan:
        raise SubscriptionError("No plan assigned.", code="no_plan")
    if plan.get("unlimited_support_agents") or plan.get("max_support_agents") is None:
        return
    # When a real support-agent store exists, replace this with a count check:
    #   if count_support_agents(admin_id) >= int(plan["max_support_agents"]): raise
    return


def can_upload_document(admin_id: int, role: str = "admin") -> bool:
    """Whether a normal admin is within their document count limit."""
    if role == "super_admin":
        return True
    _require_active_subscription(admin_id, role)
    _sub, plan = _current_plan_and_subscription(admin_id)
    if not plan:
        return False
    if plan.get("max_documents") is None:
        return True
    return count_documents_for_admin(admin_id) < plan["max_documents"]


def enforce_document_limit(admin_id: int, role: str = "admin") -> None:
    """Raise SubscriptionError when a normal admin is at/over max_documents."""
    if role == "super_admin":
        return
    _require_active_subscription(admin_id, role)
    _sub, plan = _current_plan_and_subscription(admin_id)
    if not plan:
        raise SubscriptionError("No plan assigned.", code="no_plan")
    max_documents = plan.get("max_documents")
    if max_documents is None:
        return
    if count_documents_for_admin(admin_id) >= max_documents:
        raise SubscriptionError(
            f"Document limit reached ({max_documents}). Upgrade your plan to upload more documents.",
            code="document_limit_reached",
        )


def can_send_message(admin_id: int, period_start: str, period_end: str, role: str = "admin") -> bool:
    """Whether a normal admin is within their per-period message budget.

    NOTE: Foundation for message-limit enforcement. Not yet wired into the
    /chat hot-path so the existing chat pipeline is not risked. A 'None'
    max_messages_per_period means unlimited."""
    if role == "super_admin":
        return True
    _require_active_subscription(admin_id, role)
    _sub, plan = _current_plan_and_subscription(admin_id)
    if not plan:
        return False
    max_msgs = plan.get("max_messages_per_period")
    if max_msgs is None:
        return True
    from app.db import get_usage_for_period
    return get_usage_for_period(admin_id, period_start, period_end) < max_msgs
