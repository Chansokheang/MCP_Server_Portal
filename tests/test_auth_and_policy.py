"""Bearer enforcement on the Bizplay API, gateway token verification, and portal policy."""

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from bizplay_mcp import policy_store
from bizplay_mcp.auth import PortalTokenVerifier
from bizplay_mcp.server import mcp
from legacy_bizplay_api.app import app as legacy_app


# --- every Bizplay endpoint requires a bearer token ---------------------------
async def _legacy(headers=None):
    async with httpx.AsyncClient(base_url="http://legacy.test", transport=httpx.ASGITransport(app=legacy_app)) as c:
        return await c.get("/api/v1/users/emp001", headers=headers or {})


async def test_legacy_api_rejects_missing_token():
    r = await _legacy()
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")


async def test_legacy_api_rejects_wrong_token():
    assert (await _legacy({"Authorization": "Bearer nope"})).status_code == 401


async def test_legacy_api_accepts_service_token():
    r = await _legacy({"Authorization": "Bearer demo-service-token"})
    assert r.status_code == 200 and r.json()["user_id"] == "emp001"


async def test_legacy_health_is_public():
    async with httpx.AsyncClient(base_url="http://legacy.test", transport=httpx.ASGITransport(app=legacy_app)) as c:
        assert (await c.get("/health")).status_code == 200


# --- gateway verifies portal-issued agent tokens -------------------------------
async def test_agent_token_requirement_can_be_switched_off(monkeypatch):
    """Demo mode: no token on the gateway. Identity then comes from the environment."""
    from bizplay_mcp import auth

    assert auth.agent_token_required() is True
    assert auth.gateway_auth() is not None

    state = policy_store.load()
    state["security"]["require_gateway_bearer"] = False
    policy_store.save(state)
    assert auth.agent_token_required() is False
    assert auth.gateway_auth() is None, "no verifier means anonymous HTTP callers are accepted"

    # The environment variable wins over the portal switch, in both directions.
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "true")
    assert auth.agent_token_required() is True
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "off")
    assert auth.agent_token_required() is False


async def test_gateway_token_verifier():
    state = policy_store.load()
    token, record = policy_store.issue_agent_token(state, label="t", user_id="emp001", role="employee",
                                                   company="Demo", agent="Claude Desktop", ttl_days=1, created_by="test")
    policy_store.save(state)
    verifier = PortalTokenVerifier()
    access = await verifier.verify_token(token)
    assert access is not None and access.subject == "emp001" and access.claims["role"] == "employee"
    assert await verifier.verify_token("bz_forged") is None

    state = policy_store.load()
    state["agent_tokens"][record["id"]]["revoked"] = True
    policy_store.save(state)
    assert await verifier.verify_token(token) is None, "revoked tokens must stop working immediately"


# --- portal tool policy is enforced by the gateway ---------------------------------
async def call(name, args=None):
    async with Client(mcp) as client:
        return (await client.call_tool(name, args or {})).data


async def test_disabled_tool_is_refused():
    state = policy_store.load()
    state["providers"]["bizplay"]["tools"]["get_card_balance"]["enabled"] = False
    policy_store.save(state)
    with pytest.raises(ToolError, match="disabled by the provider admin"):
        await call("get_card_balance", {"month": "2026-09"})


async def test_role_removed_from_tool_is_refused():
    state = policy_store.load()
    state["providers"]["bizplay"]["tools"]["draft_expense_report"]["roles"] = ["manager"]
    policy_store.save(state)
    with pytest.raises(ToolError, match="role 'employee' is not allowed"):
        await call("draft_expense_report", {"title": "x", "txn_ids": ["txn-0001"]})
    # Read tools untouched by the change still work.
    assert (await call("get_card_balance", {"month": "2026-09"}))["cards"]
