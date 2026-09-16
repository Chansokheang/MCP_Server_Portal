"""The gateway as an OAuth 2.1 authorization server: an MCP client signs in instead of pasting a token."""

import asyncio
import base64
import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from bizplay_mcp import policy_store
from bizplay_mcp.registry_gateway import build_registry_gateway
from portal import gateway_oauth
from portal.app import app as portal_app, create_app

api = Starlette(routes=[Route("/ping", lambda r: JSONResponse({"ok": True}))])
SPEC = {"openapi": "3.0.3", "info": {"title": "Ping", "version": "1"},
        "paths": {"/ping": {"get": {"operationId": "ping", "responses": {"200": {"description": "ok"}}}}}}
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture
async def admin(monkeypatch):
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "false")
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        r = await c.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


@pytest.fixture
async def anon():
    """A client with no portal session: what an MCP client is."""
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        yield c


@pytest.fixture
async def served():
    gw = build_registry_gateway(transport_factory=lambda p: httpx2.ASGITransport(app=api))
    server = uvicorn.Server(uvicorn.Config(create_app(gw), host="127.0.0.1", port=0, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    server.should_exit = True
    await task


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def test_discovery_and_registration(admin, anon):
    meta = (await anon.get("/.well-known/oauth-authorization-server")).json()
    assert meta["issuer"] == "http://portal.test" and meta["authorization_endpoint"] == "http://portal.test/authorize"
    assert meta["token_endpoint"] == "http://portal.test/token" and meta["registration_endpoint"] == "http://portal.test/register"
    assert "S256" in meta["code_challenge_methods_supported"] and "refresh_token" in meta["grant_types_supported"]

    # The public address set on the Security page becomes the issuer, so tunnels and nginx work.
    assert (await admin.put("/api/security", json={"public_mcp_url": "https://mcp.example.com/mcp"})).status_code == 200
    meta = (await anon.get("/.well-known/oauth-authorization-server")).json()
    assert meta["issuer"] == "https://mcp.example.com" and meta["token_endpoint"] == "https://mcp.example.com/token"
    await admin.put("/api/security", json={"public_mcp_url": ""})

    pr = (await anon.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert pr["resource"] == "http://portal.test/mcp" and pr["authorization_servers"] == ["http://portal.test"]
    assert (await anon.get("/.well-known/oauth-protected-resource/mcp/nope")).status_code == 404

    r = await anon.post("/register", json={"client_name": "Claude", "redirect_uris": [REDIRECT]})
    assert r.status_code == 201, r.text
    assert r.json()["client_id"].startswith("mcpc_") and r.json()["token_endpoint_auth_method"] == "none"
    assert (await anon.post("/register", json={"client_name": "x", "redirect_uris": ["http://evil.example/cb"]})).status_code == 400, "plain http only for localhost"
    assert (await anon.post("/register", json={"client_name": "x"})).status_code == 400


async def test_sign_in_flow_issues_a_token_bound_to_the_employee(admin, anon, served):
    pid = (await admin.post("/api/registry", json={"name": "Ping", "base_url": "http://x.test", "spec": SPEC, "auth_mode": "open"})).json()["id"]
    await admin.post(f"/api/registry/{pid}/publish")
    await admin.post("/api/gateways", json={"name": "Finance", "providers": [pid]})
    await admin.put("/api/endpoints/finance/settings", json={"require_token": True, "access": {"mode": "everyone"}})

    # 1. Without a token, the gateway says where to sign in.
    async with httpx.AsyncClient() as http:
        r = await http.post(f"{served}/mcp/finance", json={})
        assert r.status_code == 401
        assert f'resource_metadata="{served}/.well-known/oauth-protected-resource/mcp/finance"' in r.headers["www-authenticate"]
        pr = (await http.get(f"{served}/.well-known/oauth-protected-resource/mcp/finance")).json()
        assert pr["resource"] == f"{served}/mcp/finance" and pr["resource_name"] == "Finance"

    # 2. The client registers itself and sends the user to /authorize.
    client = (await anon.post("/register", json={"client_name": "Claude", "redirect_uris": [REDIRECT]})).json()
    verifier, challenge = pkce()
    q = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": REDIRECT, "state": "xyz",
         "code_challenge": challenge, "code_challenge_method": "S256", "resource": f"{served}/mcp/finance", "scope": "mcp"}
    r = await anon.get("/authorize", params=q)
    assert r.status_code == 200 and "Claude" in r.text and "Finance" in r.text and 'name="password"' in r.text
    assert (await anon.get("/authorize", params={**q, "client_id": "mcpc_nope"})).status_code == 400, "unknown client: no redirect"
    assert (await anon.get("/authorize", params={**q, "redirect_uri": "https://evil.example/cb"})).status_code == 400
    r = await anon.get("/authorize", params={**q, "code_challenge": ""}, follow_redirects=False)
    assert r.status_code == 303 and "error=invalid_request" in r.headers["location"] and "state=xyz" in r.headers["location"]

    # 3. Wrong password, an admin account, and cancel are all refused; an employee gets a code.
    r = await anon.post("/authorize", data={**q, "decision": "allow", "email": "minji@bizplay.co.kr", "password": "wrong"})
    assert r.status_code == 401 and "Invalid email or password" in r.text
    r = await anon.post("/authorize", data={**q, "decision": "allow", "email": "admin@bizplay.co.kr", "password": "admin1234"})
    assert r.status_code == 401 and "employee account" in r.text
    r = await anon.post("/authorize", data={**q, "decision": "deny"}, follow_redirects=False)
    assert r.status_code == 303 and "error=access_denied" in r.headers["location"]
    r = await anon.post("/authorize", data={**q, "decision": "allow", "email": "minji@bizplay.co.kr", "password": "minji1234"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(REDIRECT + "?"), r.text[:200]
    back = parse_qs(urlsplit(r.headers["location"]).query)
    assert back["state"] == ["xyz"]
    code = back["code"][0]

    # 4. The token endpoint checks PKCE, then issues an agent token for Minji.
    bad = await anon.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": client["client_id"], "redirect_uri": REDIRECT, "code_verifier": "nope"})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    assert (await anon.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": client["client_id"], "redirect_uri": REDIRECT, "code_verifier": verifier})).status_code == 400, "a failed exchange burns the code"
    r = await anon.post("/authorize", data={**q, "decision": "allow", "email": "minji@bizplay.co.kr", "password": "minji1234"}, follow_redirects=False)
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    tok = await anon.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": client["client_id"], "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    tok = tok.json()
    assert tok["token_type"] == "Bearer" and tok["access_token"].startswith("bz_") and tok["refresh_token"].startswith("rt_") and tok["expires_in"] == 3600
    listed = (await admin.get("/api/tokens")).json()["items"][0]
    assert listed["sub"] == "emp001" and listed["agent"] == "Claude" and listed["groups"] == ["finance"] and listed["via"] == "oauth"
    assert "refresh_token" not in listed and "token" not in listed

    # 5. The token works on the gateway, as Minji.
    async with Client(StreamableHttpTransport(f"{served}/mcp/finance", auth=tok["access_token"])) as c:
        names = {t.name for t in await c.list_tools()}
        assert f"{pid}_ping" in names
        assert (await c.call_tool(f"{pid}_ping", {})).structured_content["ok"] is True

    # 6. Refresh rotates the pair; the old access token stops working; a revoked token cannot refresh.
    new = await anon.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": client["client_id"]})
    assert new.status_code == 200 and new.json()["access_token"] != tok["access_token"]
    assert (await anon.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": client["client_id"]})).status_code == 400
    async with httpx.AsyncClient() as http:
        assert (await http.post(f"{served}/mcp/finance", json={}, headers={"Authorization": f"Bearer {tok['access_token']}"})).status_code == 401
    current = next(t for t in (await admin.get("/api/tokens")).json()["items"] if not t["revoked"] and t["sub"] == "emp001" and t["via"] == "oauth")
    assert (await admin.post(f"/api/tokens/{current['id']}/revoke")).status_code == 200
    assert (await anon.post("/token", data={"grant_type": "refresh_token", "refresh_token": new.json()["refresh_token"], "client_id": client["client_id"]})).status_code == 400


async def test_client_identified_by_metadata_document(admin, anon, monkeypatch):
    """claude.ai's 'published identity': the client id is the URL of a JSON document, no registration."""
    CID = "https://claude.ai/.well-known/mcp-client.json"
    doc = {"client_id": CID, "client_name": "Claude (published)", "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none"}
    fetched = []

    def handler(request):
        fetched.append(str(request.url))
        return httpx.Response(200, json=doc) if str(request.url) == CID else httpx.Response(404)
    monkeypatch.setattr(gateway_oauth, "http_client_factory", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
    assert (await anon.get("/.well-known/oauth-authorization-server")).json()["client_id_metadata_document_supported"] is True

    verifier, challenge = pkce()
    q = {"response_type": "code", "client_id": CID, "redirect_uri": REDIRECT, "code_challenge": challenge, "code_challenge_method": "S256", "resource": "", "state": "s"}
    r = await anon.get("/authorize", params=q)
    assert r.status_code == 200 and "Claude (published)" in r.text
    r = await anon.post("/authorize", data={**q, "decision": "allow", "email": "minji@bizplay.co.kr", "password": "minji1234"}, follow_redirects=False)
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    tok = await anon.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": CID, "redirect_uri": REDIRECT, "code_verifier": verifier})
    assert tok.status_code == 200, tok.text
    assert policy_store.find_agent_token(policy_store.load(), tok.json()["access_token"])["agent"] == "Claude (published)"
    assert len(fetched) == 1, "the document is cached for a while"
    # A document that does not vouch for the id is refused.
    assert (await anon.get("/authorize", params={**q, "client_id": "https://claude.ai/other.json"})).status_code == 400

    # The sign-in log tells the story, newest first, and lists the client.
    log = (await admin.get("/api/auth-log")).json()
    assert log["items"][0]["kind"] == "authorize" and log["items"][0]["status"] == 400, "the refused document, newest"
    issued = next(e for e in log["items"] if e["kind"] == "token")
    assert issued["status"] == 200 and issued["user"] == "emp001" and issued["client"] == "Claude (published)"
    assert any(c["client_id"] == CID and c["cimd"] for c in log["clients"])


async def test_gateway_logs_refusals_and_answers_preflight(admin, served):
    pid = (await admin.post("/api/registry", json={"name": "Ping", "base_url": "http://x.test", "spec": SPEC, "auth_mode": "open"})).json()["id"]
    await admin.post(f"/api/registry/{pid}/publish")
    await admin.post("/api/gateways", json={"name": "Locked", "providers": [pid]})
    await admin.put("/api/endpoints/locked/settings", json={"require_token": True, "access": {"mode": "everyone"}})
    async with httpx.AsyncClient() as http:
        r = await http.options(f"{served}/mcp/locked", headers={"Origin": "https://claude.ai"})
        assert r.status_code == 204 and "authorization" in r.headers["access-control-allow-headers"].lower()
        assert (await http.post(f"{served}/mcp/locked", json={}, headers={"User-Agent": "probe/1"})).status_code == 401
        assert (await http.post(f"{served}/mcp/locked", json={}, headers={"Authorization": "Bearer nope"})).status_code == 401
    items = (await admin.get("/api/auth-log")).json()["items"]
    assert items[0]["kind"] == "gateway" and items[0]["status"] == 401 and "not a valid agent token" in items[0]["detail"]
    assert items[1]["path"] == "/mcp/locked" and items[1]["agent"] == "probe/1" and "challenge sent" in items[1]["detail"]


async def test_expired_access_token_is_refused_until_refreshed(admin, anon):
    client = (await anon.post("/register", json={"client_name": "Test", "redirect_uris": [REDIRECT]})).json()
    verifier, challenge = pkce()
    q = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": REDIRECT, "code_challenge": challenge, "code_challenge_method": "S256", "resource": ""}
    r = await anon.post("/authorize", data={**q, "decision": "allow", "email": "junho@bizplay.co.kr", "password": "junho1234"}, follow_redirects=False)
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    tok = (await anon.post("/token", data={"grant_type": "authorization_code", "code": code, "client_id": client["client_id"], "code_verifier": verifier})).json()
    state = policy_store.load()
    rec = next(t for t in state["agent_tokens"].values() if t.get("refresh_token") == tok["refresh_token"])
    rec["expires_at"] = time.time() - 1
    policy_store.save(state)
    assert policy_store.find_agent_token(policy_store.load(), tok["access_token"]) is None, "expired access token"
    new = (await anon.post("/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": client["client_id"]})).json()
    assert policy_store.find_agent_token(policy_store.load(), new["access_token"])["sub"] == "emp002"
