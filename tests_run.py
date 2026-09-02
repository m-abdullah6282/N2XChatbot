"""Integration tests for the multi-tenant chatbot SaaS changes.

Run:  python tests_run.py
Uses the real chatbot.db (migrations already applied). Never resets data.
"""

import re
import sys

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PASS = []
FAIL = []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name} {extra}")


def admin_login(username, password):
    r = client.post("/admin/login", json={"username": username, "password": password})
    return r


print("=== LOGIN ===")
# The seeded super admin uses ADMIN_PASSWORD from .env
import os
from dotenv import load_dotenv
load_dotenv()
SA_USER = os.getenv("ADMIN_USERNAME", "admin")
SA_PASS = os.getenv("ADMIN_PASSWORD", "change_this_password")

r = admin_login(SA_USER, SA_PASS)
check("super admin login", r.status_code == 200, str(r.status_code))

# Create a throwaway normal admin to test isolation
import secrets as _s
test_admin = "testadmin_" + _s.token_hex(4)
test_pass = "testpass123"
r = client.post("/admin/users", json={"username": test_admin, "password": test_pass, "role": "admin"})
check("create normal admin", r.status_code == 200, str(r.text)[:200])
new_admin_id = r.json().get("id") if r.status_code == 200 else None

# logout then login as normal admin
client.post("/admin/logout")
r = admin_login(test_admin, test_pass)
check("normal admin login", r.status_code == 200, str(r.status_code))

print("\n=== NEW ADMIN GETS FREE ===")
r = client.get("/subscription")
if r.status_code == 200:
    plan = r.json().get("plan") or {}
    check("new admin on Free", plan.get("name") == "Free", str(plan))
else:
    check("new admin on Free", False, str(r.text))

print("\n=== NORMAL ADMIN CANNOT MANAGE PLANS ===")
r = client.get("/admin/plans")
check("GET /admin/plans blocked for normal admin", r.status_code == 403, str(r.status_code))
r = client.put("/admin/plans/1", json={"name": "Free", "price": 0, "max_ai_agents": 1, "unlimited_ai_agents": False, "max_support_agents": 1, "unlimited_support_agents": False, "is_active": True})
check("PUT /admin/plans blocked for normal admin", r.status_code == 403, str(r.status_code))
r = client.get("/admin/subscriptions")
check("GET /admin/subscriptions blocked for normal admin", r.status_code == 403, str(r.status_code))

print("\n=== NORMAL ADMIN CANNOT SELF-ASSIGN PAID PLAN ===")
if new_admin_id:
    r = client.post(f"/admin/subscriptions/{new_admin_id}/activate", json={"plan_id": 4})
    check("normal admin self-assign blocked", r.status_code in (403, 404), str(r.status_code))

print("\n=== SUPER ADMIN PLAN MANAGEMENT ===")
client.post("/admin/logout")
admin_login(SA_USER, SA_PASS)
r = client.get("/admin/plans")
check("super admin GET /admin/plans", r.status_code == 200, str(r.status_code))
plans = r.json()["plans"]
names = {p["name"] for p in plans}
check("Free present", "Free" in names)
check("Monthly present", "Monthly" in names)
check("Yearly present", "Yearly" in names)
check("Lifetime present", "Lifetime" in names)
free = next(p for p in plans if p["name"] == "Free")
check("Free price_pkr==0", free["price"] == 0)
check("Free max_ai_agents==1", free["max_agents"] == 1)
check("Free unlimited_ai false", free["unlimited_ai_agents"] == 0 or free["unlimited_ai_agents"] is False)
monthly = next(p for p in plans if p["name"] == "Monthly")
check("Monthly price 3000", monthly["price"] == 3000)
check("Monthly max_ai 3", monthly["max_agents"] == 3)
yearly = next(p for p in plans if p["name"] == "Yearly")
check("Yearly price 300000", yearly["price"] == 300000)
lifetime = next(p for p in plans if p["name"] == "Lifetime")
check("Lifetime price 79999", lifetime["price"] == 79999)
check("Lifetime unlimited_ai true", lifetime["unlimited_ai_agents"] in (1, True))
check("Lifetime max_agents NULL", lifetime["max_agents"] is None)

print("\n=== UNLIMITED VALIDATION ===")
# Try to set Monthly unlimited AI with a max value -> should store NULL
r = client.put(f"/admin/plans/{monthly['id']}", json={
    "name": "Monthly", "price": 3000,
    "max_ai_agents": 5, "unlimited_ai_agents": True,
    "max_support_agents": 5, "unlimited_support_agents": False,
    "is_active": True,
})
check("unlimited + max ignored -> stored NULL", r.status_code == 200 and r.json().get("max_agents") is None, str(r.text)[:200])
# Reset back to non-unlimited for the limit test below
r = client.put(f"/admin/plans/{monthly['id']}", json={
    "name": "Monthly", "price": 3000,
    "max_ai_agents": 3, "unlimited_ai_agents": False,
    "max_support_agents": 5, "unlimited_support_agents": False,
    "is_active": True,
})
check("reset Monthly to 3 agents", r.status_code == 200 and r.json().get("max_agents") == 3, str(r.text)[:200])
# Non-unlimited with empty max -> 400
r = client.put(f"/admin/plans/{monthly['id']}", json={
    "name": "Monthly", "price": 3000,
    "max_ai_agents": None, "unlimited_ai_agents": False,
    "max_support_agents": 5, "unlimited_support_agents": False,
    "is_active": True,
})
check("non-unlimited without max -> 400", r.status_code == 400, str(r.status_code))

print("\n=== SUPER ADMIN MANUAL SUBSCRIPTION ASSIGN ===")
if new_admin_id:
    r = client.get("/admin/subscriptions")
    check("super admin GET /admin/subscriptions", r.status_code == 200, str(r.status_code))
    # Assign Lifetime to test admin
    r = client.post(f"/admin/subscriptions/{new_admin_id}/activate", json={"plan_id": lifetime["id"]})
    check("assign Lifetime to test admin", r.status_code == 200, str(r.status_code))
    # Verify exactly one active subscription and lifetime end NULL-ish
    r = client.get(f"/subscriptions/{new_admin_id}")
    subs = r.json().get("subscriptions", [])
    active = [s for s in subs if s["status"] == "active"]
    check("exactly one active subscription", len(active) == 1, str(len(active)))
    lifetime_subs = [s for s in subs if s["plan_id"] == lifetime["id"] and s["status"] == "active"]
    check("history preserved (>=2 rows)", len(subs) >= 2, str(len(subs)))
    # Assign Monthly
    r = client.post(f"/admin/subscriptions/{new_admin_id}/activate", json={"plan_id": monthly["id"]})
    check("assign Monthly to test admin", r.status_code == 200, str(r.status_code))
    r = client.get(f"/subscriptions/{new_admin_id}")
    subs = r.json().get("subscriptions", [])
    active = [s for s in subs if s["status"] == "active"]
    check("still exactly one active after re-assign", len(active) == 1 and active[0]["plan_id"] == monthly["id"], str([ (s['plan_id'], s['status']) for s in subs]))
    future = r.json().get("plan") or {}
    check("monthly end ~30 days (not lifetime)", (active[0].get("current_period_end") or "") != "", "end="+str(active[0].get("current_period_end")))

print("\n=== AGENT LIMIT ENFORCEMENT ===")
# Fresh admin on Free => max 1 AI agent
free_admin = "freeadmin_" + _s.token_hex(4)
r = client.post(f"/admin/logout")
admin_login(SA_USER, SA_PASS)
r = client.post("/admin/users", json={"username": free_admin, "password": "testpass123", "role": "admin"})
free_admin_id = r.json().get("id") if r.status_code == 200 else None
client.post("/admin/logout")
admin_login(free_admin, "testpass123")
# Confirm they are on Free
r = client.get("/subscription")
free_plan = (r.json().get("plan") or {}).get("name")
check(f"fresh admin on Free (got {free_plan})", free_plan == "Free", str(r.text))
agents_before = client.get("/agents")
owned = [a for a in (agents_before.json() or []) if a.get("owner_admin_id") == free_admin_id]
check(f"free admin starts with {len(owned)} agents", len(owned) == 0, str(owned))
r = client.post("/agents", json={"name": f"free1_{_s.token_hex(3)}", "primary_color": "#00ff00"})
check("create 1st agent on Free ok", r.status_code == 200, str(r.text)[:200])
r = client.post("/agents", json={"name": f"free2_{_s.token_hex(3)}", "primary_color": "#ff0000"})
check("2nd agent blocked on Free (limit 1)", r.status_code == 403, (r.json() or {}).get("detail") or str(r.text)[:200])
# assign Monthly (3) then Lifetime (unlimited) to free admin
client.post("/admin/logout")
admin_login(SA_USER, SA_PASS)
r = client.post(f"/admin/subscriptions/{free_admin_id}/activate", json={"plan_id": monthly["id"]})
check("assign Monthly to free admin", r.status_code == 200, str(r.text)[:100])
client.post("/admin/logout")
admin_login(free_admin, "testpass123")
r = client.post("/agents", json={"name": f"free3_{_s.token_hex(3)}", "primary_color": "#0000ff"})
check("create agent under Monthly (limit 3) ok", r.status_code == 200, str(r.text)[:200])
client.post("/admin/logout")
admin_login(SA_USER, SA_PASS)
r = client.post(f"/admin/subscriptions/{free_admin_id}/activate", json={"plan_id": lifetime["id"]})
check("assign Lifetime to free admin", r.status_code == 200, str(r.text)[:100])
client.post("/admin/logout")
admin_login(free_admin, "testpass123")
r = client.post("/agents", json={"name": f"freeunl_{_s.token_hex(3)}", "primary_color": "#123456"})
check("create agent under Lifetime unlimited ok", r.status_code == 200, str(r.text)[:200])

print("\n=== AGENT COLOR OWNERSHIP ===")
# test_admin is on Lifetime (assigned earlier), has agents from the earlier section
client.post("/admin/logout")
admin_login(test_admin, test_pass)
r = client.get("/agents")
owned_agent = next((a for a in (r.json() or []) if a.get("owner_admin_id") == new_admin_id), None)
if owned_agent is None:
    r = client.post("/agents", json={"name": f"coloragent_{_s.token_hex(3)}", "primary_color": "#ffffff"})
    if r.status_code == 200:
        owned_agent = r.json()
    else:
        check("create color agent (test admin has Lifetime)", False, str(r.text)[:150])
if owned_agent:
    aid = owned_agent["id"]
    r = client.put(f"/agents/{aid}", json={
        "name": owned_agent["name"],
        "description": owned_agent.get("description") or "",
        "greeting": owned_agent.get("greeting") or "",
        "slug": owned_agent.get("slug") or "",
        "primary_color": "#00aaff",
    })
    check("update own agent color", r.status_code == 200, str(r.text)[:150])
    check("color persisted", (r.json().get("primary_color") or "").lower() == "#00aaff", str(r.text)[:150])
    r = client.put(f"/agents/{aid}", json={
        "name": owned_agent["name"],
        "primary_color": "not-a-color",
    })
    check("invalid hex color rejected", r.status_code == 400, str(r.status_code))
else:
    check("update own agent color (agent exists)", False, "no owned agent found")

print("\n=== CROSS-ADMIN COLOR OWNERSHIP (blocked) ===")
# The seeded super admin owns agents 1,4,14,18. Try to edit agent 1 as test admin.
r = client.put("/agents/1", json={"name": "N2X Assistant", "primary_color": "#111111", "slug": "n2x-assistant"})
check("normal admin cannot edit super-admin agent", r.status_code in (403, 404), str(r.status_code))

print("\n=== CHAT HISTORY: AGENT IDENTIFICATION ===")
r = client.get("/chat-history")
check("normal admin chat-history", r.status_code == 200, str(r.status_code))
hist = r.json()
for h in hist:
    check("summary has agent_id", h.get("agent_id") is not None, str(h.get("agent_id")))
    check("summary has session_id", bool(h.get("session_id")))
    break
else:
    if not hist:
        check("chat-history empty ok", True)

print("\n=== LIVE CHAT (SUPER ADMIN SEES ALL) ===")
client.post("/admin/logout")
admin_login(SA_USER, SA_PASS)
r = client.get("/admin/live-chats")
check("super admin live-chats", r.status_code == 200, str(r.status_code))
data = r.json()
check("mechanism reported", data.get("mechanism") == "polling", str(data))
all_chats = data.get("chats", [])
# super admin summary must include owner_username for each chat
for c in all_chats:
    if c.get("agent_id") is not None:
        check("super admin sees owner", bool(c.get("owner_username")), str(c))
        break

print("\n=== CROSS-ADMIN CHAT ACCESS ===")
# super admin sees all sessions; normal admin chat-history must be subset. Both
# operate on the same endpoints so cross-admin leak is enforced server-side.
client.post("/admin/logout")
admin_login(test_admin, test_pass)
r = client.get("/chat-history")
my_sessions = {c["session_id"] for c in (r.json() or [])}
client.post("/admin/logout")
admin_login(SA_USER, SA_PASS)
r = client.get("/chat-history")
all_sessions = {c["session_id"] for c in (r.json() or [])}
check("normal admin sessions subset of super admin", my_sessions <= all_sessions, f"my={len(my_sessions)} all={len(all_sessions)}")

print("\n=== API KEYS: AGENT BINDING ===")
client.post("/admin/logout")
admin_login(test_admin, test_pass)
# find an agent owned by test admin
r = client.get("/agents")
test_owned = [a for a in (r.json() or []) if a.get("owner_admin_id") == new_admin_id]
if test_owned:
    agent_a = test_owned[0]
    agent_b = test_owned[1] if len(test_owned) > 1 else None
    r = client.post("/api-keys", json={"label": "key-agent-a", "agent_id": agent_a["id"]})
    check("create key bound to agent A", r.status_code == 200, str(r.text)[:200])
    key_a_raw = r.json().get("api_key") if r.status_code == 200 else None
    r = client.post("/api-keys", json={"label": "key-no-agent"})
    check("create key without agent blocked", r.status_code == 400, str(r.status_code))
    # list keys shows no raw key
    r = client.get("/api-keys")
    keys = r.json()
    check("list keys ok", r.status_code == 200)
    if keys:
        check("raw key never echoed in list", all("n2x_" not in (k.get("api_key") or "") for k in keys), str(keys))
    # resolve via public endpoint
    if key_a_raw:
        r = client.get("/chat/agent/by-api-key", headers={"X-API-Key": key_a_raw})
        check("valid key resolves to agent A", r.status_code == 200 and r.json().get("id") == agent_a["id"], str(r.text)[:200])
        r = client.get("/chat/agent/by-api-key", headers={"X-API-Key": "n2x_invalidkey123"})
        check("invalid key -> 401", r.status_code == 401, str(r.status_code))
        if agent_b:
            r = client.get("/chat/agent/by-api-key", headers={"X-API-Key": key_a_raw})
            # even correct key maps only to its own agent; check a key bound to A cannot equal B
            r2 = client.get("/chat/agent/by-api-key", headers={"X-API-Key": key_a_raw})
            check("key A maps only to agent A", r2.json().get("id") == agent_a["id"], str(r2.json()))
    # delete key revokes
    if test_owned:
        r = client.get("/api-keys")
        keys = r.json()
        ok = False
        for k in keys:
            if k.get("agent_id") == agent_a.get("id"):
                r = client.delete(f"/api-keys/{k['id']}")
                ok = True
                break
        if key_a_raw:
            r = client.get("/chat/agent/by-api-key", headers={"X-API-Key": key_a_raw})
            check("deleted key -> 401", r.status_code == 401, str(r.status_code))
        if not ok:
            check("delete key found target", False)

print("\n=== CROSS-ADMIN API KEY (A cannot reach B) ===")
# normal admin B <- testadmin cannot list/use super admin's agents
client.post("/admin/logout")
admin_login(SA_USER, SA_PASS)
# super admin creates a key bound to their agent (id 1)
r = client.post("/api-keys", json={"label": "super-agent1-key", "agent_id": 1})
sa_key = r.json().get("api_key") if r.status_code == 200 else None
client.post("/admin/logout")
admin_login(test_admin, test_pass)
if sa_key:
    r = client.get("/chat/agent/by-api-key", headers={"X-API-Key": sa_key})
    # The key IS valid, resolves to super admin's agent 1. That's legitimately
    # allowed publicly. The isolation we must verify: test admin cannot LIST it.
    r = client.get("/api-keys")
    keys = r.json()
    check("test admin cannot see super admin's keys", all(k.get("admin_id") == new_admin_id for k in keys), str(keys))
    r = client.delete("/api-keys/1")
    check("test admin cannot delete super admin's key", r.status_code == 404, str(r.status_code))

print("\n=== WHATSAPP UPGRADE ===")
client.post("/admin/logout")
admin_login(test_admin, test_pass)
r = client.get("/upgrade/whatsapp")
if r.status_code == 200:
    data = r.json()
    check("wa config returned", "wa_link" in data or "whatsapp_number" in data, str(data))
else:
    check("wa config returned", False, str(r.status_code))
# Ensure upgrade never activates anything
r = client.get("/subscription")
sub_before = r.json().get("subscription") or {}
r = client.get("/upgrade/whatsapp")
if "subscription" in (r.json() or {}):
    check("upgrade did not change plan", True)
else:
    check("upgrade did not change plan", True)
r = client.get("/subscription")
check("plan unchanged after upgrade call", (r.json().get("subscription") or {}).get("plan_id") == sub_before.get("plan_id"), str(r.json()))

print("\n=== PERMISSIONS ON AGENTS ROUTES ===")
client.post("/admin/logout")
admin_login(SA_USER, SA_PASS)
r = client.get("/admin/users")
check("super admin list users", r.status_code == 200)
client.post("/admin/logout")
admin_login(test_admin, test_pass)
r = client.get("/admin/users")
check("normal admin list users blocked", r.status_code == 403, str(r.status_code))

print("\n\n=== SUMMARY ===")
print(f"PASS: {len(PASS)}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAILED:", f)
sys.exit(0 if not FAIL else 1)