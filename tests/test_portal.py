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


async def test_ui_is_served_with_revalidation(portal):
    """A deploy should not need a hard reload to take effect."""
    for path in ("/", "/static/app.js"):
        r = await portal.get(path)
        assert r.status_code == 200
        assert "no-cache" in r.headers.get("cache-control", "")


async def test_config_reports_project_dir_and_urls(admin, monkeypatch):
    monkeypatch.setenv("BIZPLAY_PROJECT_DIR", "/srv/bizplay-mcp")
    c = (await admin.get("/api/config")).json()
    assert c["project_dir"] == "/srv/bizplay-mcp"
    assert c["gateway_url"].endswith("/mcp") and c["registry_url"].endswith("/mcp")
    # Falls back to the host the portal was opened on, not 127.0.0.1.
    assert "portal.test" in c["registry_url"]


async def test_new_api_starts_with_writes_off(admin):
    """A fresh registration must not hand agents delete tools by default."""
    pid = (await admin.post("/api/registry", json={"name": "Fresh API", "base_url": "http://f.test",
                                                   "spec": SPEC, "auth_mode": "open"})).json()["id"]
    tools = (await admin.get(f"/api/registry/{pid}/tools")).json()["items"]
    assert all(t["enabled"] for t in tools if t["kind"] == "read")
    assert not any(t["enabled"] for t in tools if t["kind"] == "write")


async def test_remembered_public_endpoint_survives_deleting_every_api(admin, monkeypatch):
    """Setting the public address once must outlive the APIs that used it."""
    monkeypatch.setenv("BIZPLAY_PUBLIC_REGISTRY_URL", "http://127.0.0.1:9014/mcp")
    first = (await admin.post("/api/registry", json={"name": "Tunnel User", "base_url": "http://a.test",
                                                     "spec": SPEC, "auth_mode": "open"})).json()["id"]
    await admin.patch(f"/api/registry/{first}", json={"mcp_url": "https://demo.trycloudflare.com/mcp"})
    assert (await admin.get("/api/security")).json()["settings"]["public_mcp_url"] == "https://demo.trycloudflare.com/mcp"

    await admin.delete(f"/api/registry/{first}")  # every spec-backed API is gone
    again = await admin.post("/api/registry", json={"name": "After Wipe", "base_url": "http://b.test",
                                                    "spec": SPEC, "auth_mode": "open"})
    assert again.json()["mcp_url"] == "https://demo.trycloudflare.com/mcp"


async def test_any_endpoint_the_caller_gives_is_used_as_is(admin):
    """No guessing: whatever endpoint is supplied is stored, http or https, any path."""
    for url in ("https://mcp.example.com/mcp", "http://10.0.0.5:9014/mcp",
                "https://gw.example.com/tenants/acme/mcp"):
        r = await admin.post("/api/registry", json={"name": f"API {url}", "base_url": "http://x.test",
                                                    "spec": SPEC, "auth_mode": "open", "mcp_url": url})
        assert r.json()["mcp_url"] == url
    bad = await admin.post("/api/registry", json={"name": "Bad URL", "base_url": "http://x.test",
                                                  "spec": SPEC, "auth_mode": "open", "mcp_url": "not-a-url"})
    assert bad.status_code == 400


async def test_base_url_with_duplicate_path_prefix_is_trimmed(admin):
    """https://host/api/v1 plus a spec whose paths start with /api/v1 would 404 on every call."""
    r = await admin.post("/api/registry", json={"name": "Prefixed API", "base_url": "https://host.test/api/v1",
                                                "spec": SPEC, "auth_mode": "open"})
    assert r.json()["base_url"] == "https://host.test"
    assert "/api/v1" in r.json()["note"]


async def test_edit_connection(admin):
    pid = (await admin.post("/api/registry", json={"name": "Editable", "base_url": "http://old.test",
                                                   "spec": SPEC, "auth_mode": "bearer"})).json()["id"]
    r = await admin.patch(f"/api/registry/{pid}", json={
        "base_url": "https://new.test/api/v1", "auth_mode": "open",
        "mcp_url": "http://203.0.113.10:9011/mcp", "name": "Renamed"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Renamed" and body["auth_mode"] == "open"
    assert body["base_url"] == "https://new.test", "the duplicated path prefix is trimmed on edit too"
    assert body["mcp_url"] == "http://203.0.113.10:9011/mcp"
    # Open mode may now be published without a service token.
    assert (await admin.post(f"/api/registry/{pid}/publish")).status_code == 200
    assert (await admin.patch(f"/api/registry/{pid}", json={"auth_mode": "network"})).status_code == 400


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


async def test_configured_localhost_url_is_rewritten_to_the_browsing_host(admin, monkeypatch):
    """A deployment that left the URL at 127.0.0.1 would hand agents a dead address."""
    monkeypatch.setenv("BIZPLAY_PUBLIC_REGISTRY_URL", "http://127.0.0.1:9014/mcp")
    r = await admin.post("/api/registry", json={"name": "Hosted API", "base_url": "http://x.test",
                                                "spec": SPEC, "auth_mode": "open"})
    assert r.json()["mcp_url"] == "http://portal.test:9014/mcp", "port kept, host corrected"
    # Reached on the server itself, the configured value stands.
    assert policy_store.public_url("registry", "127.0.0.1") == "http://127.0.0.1:9014/mcp"


async def test_overview_and_audit(admin):
    ov = (await admin.get("/api/overview")).json()
    assert ov["providers"] >= 1 and 0 <= ov["score"] <= 100
    assert (await admin.get("/api/audit?limit=5")).status_code == 200
