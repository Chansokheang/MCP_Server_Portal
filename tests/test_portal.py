"""Portal API: session bearer, registry, access control, tokens, security."""

import json
from pathlib import Path

import httpx
import pytest

from bizplay_mcp import policy_store
from bizplay_mcp.auth import PortalTokenVerifier
from portal.app import app as portal_app

SPEC = json.loads((Path(__file__).resolve().parents[1] / "openapi" / "bizplay-existing-api.json").read_text("utf-8"))


@pytest.fixture
async def portal():
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        yield c


@pytest.fixture
async def admin(portal):
    r = await portal.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
    assert r.status_code == 200
    portal.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return portal


async def test_portal_api_requires_session_bearer(portal):
    assert (await portal.get("/api/registry")).status_code == 401
    assert (await portal.get("/api/registry", headers={"Authorization": "Bearer bogus"})).status_code == 401
    bad = await portal.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "wrong"})
    assert bad.status_code == 401


async def test_registry_lists_bizplay_published(admin):
    items = (await admin.get("/api/registry")).json()["items"]
    biz = next(p for p in items if p["id"] == "bizplay")
    assert biz["status"] == "published" and biz["auth_mode"] == "bearer" and biz["tool_count"] == 8


async def test_register_publish_delete_provider(admin):
    r = await admin.post("/api/registry", json={"name": "HR API", "base_url": "http://hr.test",
                                                "spec": SPEC, "service_token": "hr-secret"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["status"] == "draft" and r.json()["tool_count"] == 10
    tools = (await admin.get(f"/api/registry/{pid}/tools")).json()["items"]
    write = next(t for t in tools if t["name"] == "decide_expense_report")
    assert write["kind"] == "write" and write["confirm"] is True
    assert (await admin.post(f"/api/registry/{pid}/publish")).json()["status"] == "published"
    assert (await admin.delete(f"/api/registry/{pid}")).status_code == 200
    assert (await admin.delete("/api/registry/bizplay")).status_code == 409


async def test_publish_requires_service_token(admin):
    r = await admin.post("/api/registry", json={"name": "Open API", "base_url": "http://x.test", "spec": SPEC})
    pid = r.json()["id"]
    assert (await admin.post(f"/api/registry/{pid}/publish")).status_code == 409


async def test_access_control_update_reaches_gateway_policy(admin):
    r = await admin.put("/api/registry/bizplay/tools/decide_approval", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    allowed, reason = policy_store.check_tool_access(policy_store.load(), "bizplay", "decide_approval", "manager")
    assert not allowed and "disabled" in reason


async def test_issue_and_revoke_agent_token(admin):
    r = await admin.post("/api/tokens", json={"label": "Minji Claude", "user_id": "emp001", "role": "employee",
                                              "agent": "Claude Desktop", "ttl_days": 7})
    assert r.status_code == 201
    token, record = r.json()["token"], r.json()["record"]
    assert token.startswith("bz_") and "token" not in record
    assert (await PortalTokenVerifier().verify_token(token)).subject == "emp001"

    listed = (await admin.get("/api/tokens")).json()["items"]
    assert listed[0]["id"] == record["id"] and "token" not in listed[0]

    assert (await admin.post(f"/api/tokens/{record['id']}/revoke")).json()["revoked"] is True
    assert await PortalTokenVerifier().verify_token(token) is None
    bad = await admin.post("/api/tokens", json={"label": "x", "user_id": "emp001", "role": "root"})
    assert bad.status_code == 400


async def test_security_page_and_rotation(admin):
    sec = (await admin.get("/api/security")).json()
    assert sec["credentials"][0]["secret"] != "demo-service-token", "secrets must be masked"
    assert any(c["id"] == "upstream_bearer" and c["ok"] for c in sec["checklist"])
    r = await admin.post("/api/credentials/cred_bizplay_service/rotate", json={})
    assert r.status_code == 200 and r.json()["secret"].startswith("svc_")
    assert policy_store.load()["credentials"]["cred_bizplay_service"]["secret"] == r.json()["secret"]


async def test_connection_test_probes_bearer_enforcement(admin, monkeypatch):
    """The portal's connection test must prove /api/* answers 401 without a token."""
    from legacy_bizplay_api.app import app as legacy_app

    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.ASGITransport(app=legacy_app)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("portal.app.httpx.AsyncClient", fake_client)
    r = await admin.post("/api/registry/bizplay/test")
    assert r.status_code == 200, r.text
    checks = {x["check"]: x for x in r.json()["results"]}
    assert checks["API reachable"]["status"] == 200
    assert checks["Protected endpoint rejects missing token"]["status"] == 401
    assert checks["Protected endpoint accepts service token"]["status"] == 200
    assert r.json()["ok"] is True


async def test_connection_test_without_service_token_reports_clearly(admin, monkeypatch):
    from legacy_bizplay_api.app import app as legacy_app

    real_client = httpx.AsyncClient
    monkeypatch.setattr("portal.app.httpx.AsyncClient",
                        lambda *a, **k: real_client(*a, **{**k, "transport": httpx.ASGITransport(app=legacy_app)}))
    pid = (await admin.post("/api/registry", json={"name": "No Token API", "base_url": "http://x.test", "spec": SPEC})).json()["id"]
    r = await admin.post(f"/api/registry/{pid}/test")
    assert r.status_code == 200
    token_check = next(x for x in r.json()["results"] if x["check"] == "Protected endpoint accepts service token")
    assert token_check["ok"] is False and "no service token" in token_check["error"]
    assert r.json()["ok"] is False


async def test_public_url_follows_the_published_port(admin, monkeypatch):
    """Agents get the published address, not the container's internal port."""
    monkeypatch.setenv("BIZPLAY_PUBLIC_REGISTRY_URL", "http://mcp.example.com:9011/mcp")
    monkeypatch.setenv("BIZPLAY_PUBLIC_GATEWAY_URL", "http://mcp.example.com:9010/mcp")
    r = await admin.post("/api/registry", json={"name": "Ported API", "base_url": "http://x.test",
                                                "spec": SPEC, "auth_mode": "open"})
    assert r.json()["mcp_url"] == "http://mcp.example.com:9011/mcp"
    assert policy_store.public_url("curated") == "http://mcp.example.com:9010/mcp"

    monkeypatch.delenv("BIZPLAY_PUBLIC_REGISTRY_URL")
    assert policy_store.public_url("registry") == "http://127.0.0.1:8002/mcp"


async def test_overview_and_audit(admin):
    ov = (await admin.get("/api/overview")).json()
    assert ov["providers"] >= 1 and 0 <= ov["score"] <= 100
    assert (await admin.get("/api/audit?limit=5")).status_code == 200
