"""Per-user OAuth: the gateway links each user's account on a backend and sends that user's token."""

import base64
import hashlib
import time
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.providers.proxy import ProxyClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from bizplay_mcp import oauth, policy_store
from bizplay_mcp.registry_gateway import build_registry_gateway
from portal import app as portal_module
from portal.app import app as portal_app

# --- a mock authorization server (one per backend in real life) -----------------------------
AS = "http://auth.test"


class AuthServer:
    """Issues codes bound to a PKCE challenge, trades them for tokens, refreshes them."""

    def __init__(self) -> None:
        self.codes: dict[str, tuple[str, str]] = {}   # code -> (user, challenge)
        self.issued = 0
        self.refreshed = 0

    def issue_code(self, authorization_url: str, user: str) -> tuple[str, str]:
        """What the user's browser would do: sign in at the auth server, get a code back."""
        q = parse_qs(urlsplit(authorization_url).query)
        assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["dyn-client"]
        code = f"code-{user}-{len(self.codes)}"
        self.codes[code] = (user, q["code_challenge"][0])
        return code, q["state"][0]

    async def metadata(self, request: Request):
        return JSONResponse({"issuer": AS, "authorization_endpoint": f"{AS}/authorize", "token_endpoint": f"{AS}/token",
                             "registration_endpoint": f"{AS}/register", "scopes_supported": ["tasks:read"]})

    async def register(self, request: Request):
        body = await request.json()
        assert body["redirect_uris"] == ["http://portal.test/oauth/callback"]
        return JSONResponse({"client_id": "dyn-client", "client_secret": "dyn-secret"}, status_code=201)

    async def token(self, request: Request):
        form = dict((await request.form()).items())
        assert form["client_id"] == "dyn-client" and form["client_secret"] == "dyn-secret"
        if form["grant_type"] == "authorization_code":
            user, challenge = self.codes.pop(form["code"])
            expected = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
            if expected != challenge:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
        elif form["grant_type"] == "refresh_token":
            user = form["refresh_token"].split(":")[1]
            self.refreshed += 1
        else:
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        self.issued += 1
        return JSONResponse({"access_token": f"at:{user}:{self.issued}", "refresh_token": f"rt:{user}", "token_type": "Bearer",
                             "expires_in": 3600, "scope": "tasks:read"})


# --- a backend that only answers with the user's own token ------------------------------------
async def items(request: Request):
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not token.startswith("at:"):
        return JSONResponse({"error": "sign in"}, status_code=401)
    return JSONResponse({"owner": token.split(":")[1], "token": token, "items": ["invoice-1"]})


protected_api = Starlette(routes=[Route("/items", items)])
SPEC = {"openapi": "3.0.3", "info": {"title": "Items", "version": "1"},
        "paths": {"/items": {"get": {"operationId": "listItems", "responses": {"200": {"description": "ok"}}}}}}


@pytest.fixture
def auth_server(monkeypatch):
    server = AuthServer()
    asgi = Starlette(routes=[Route("/.well-known/oauth-authorization-server", server.metadata),
                             Route("/register", server.register, methods=["POST"]),
                             Route("/token", server.token, methods=["POST"])])
    monkeypatch.setattr(oauth, "http_client_factory",
                        lambda **kw: httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi), **kw))
    return server


@pytest.fixture
async def admin(auth_server):
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        r = await c.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


@pytest.fixture
async def items_api(admin):
    """A REST backend in OAuth mode, endpoints discovered and client registered, published."""
    r = await admin.post("/api/registry", json={"name": "Items API", "base_url": "http://items.test", "spec": SPEC, "auth_mode": "oauth"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert (await admin.post(f"/api/registry/{pid}/publish")).status_code == 409, "not until the OAuth endpoints are known"
    d = await admin.post(f"/api/registry/{pid}/oauth/discover", json={"url": AS})
    assert d.status_code == 200, d.text
    assert d.json()["registered_client"] and d.json()["oauth"]["client_id"] == "dyn-client" and not d.json()["oauth"].get("client_secret")
    assert (await admin.post(f"/api/registry/{pid}/publish")).status_code == 200
    return pid


async def link(admin, auth_server, pid, user):
    """Run the whole flow as the portal and browser would."""
    start = (await admin.post(f"/api/registry/{pid}/oauth/start", json={"user_id": user})).json()
    assert start["authorization_url"].startswith(f"{AS}/authorize?") and "code_challenge=" in start["authorization_url"]
    code, nonce = auth_server.issue_code(start["authorization_url"], user)
    r = await admin.get("/oauth/callback", params={"code": code, "state": nonce}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/#provider?p={pid}&connected={user}"), r.headers.get("location")


@pytest.fixture
def as_user(monkeypatch):
    def _set(user: str) -> None:
        monkeypatch.setenv("BIZPLAY_USER_ID", user)
        monkeypatch.delenv("BIZPLAY_COMPANY", raising=False)
    return _set


def gateway(mcp_factory=None):
    return build_registry_gateway(transport_factory=lambda p: httpx2.ASGITransport(app=protected_api),
                                  mcp_client_factory=mcp_factory)


async def test_user_links_account_and_gateway_sends_that_users_token(admin, auth_server, items_api, as_user):
    await link(admin, auth_server, items_api, "emp001")
    listed = (await admin.get(f"/api/registry/{items_api}/connections")).json()["items"]
    assert [c["user_id"] for c in listed] == ["emp001"] and listed[0]["can_refresh"]

    as_user("emp001")
    async with Client(gateway()) as c:
        r = await c.call_tool("items_api_listItems", {})
    assert r.structured_content["owner"] == "emp001" and r.structured_content["token"] == "at:emp001:1"

    as_user("emp002")
    async with Client(gateway()) as c:
        with pytest.raises(ToolError, match="emp002.*has not connected a Items API account"):
            await c.call_tool("items_api_listItems", {})


async def test_two_users_two_tokens(admin, auth_server, items_api, as_user):
    await link(admin, auth_server, items_api, "emp001")
    await link(admin, auth_server, items_api, "emp002")
    gw = gateway()
    for user in ("emp001", "emp002"):
        as_user(user)
        async with Client(gw) as c:
            assert (await c.call_tool("items_api_listItems", {})).structured_content["owner"] == user


async def test_expired_token_is_refreshed_silently(admin, auth_server, items_api, as_user):
    await link(admin, auth_server, items_api, "emp001")
    state = policy_store.load()
    state["user_connections"]["emp001"][items_api]["expires_at"] = time.time() - 1
    policy_store.save(state)

    as_user("emp001")
    async with Client(gateway()) as c:
        r = await c.call_tool("items_api_listItems", {})
    assert r.structured_content["token"] == "at:emp001:2" and auth_server.refreshed == 1
    stored = policy_store.load()["user_connections"]["emp001"][items_api]
    assert stored["access_token"] == "at:emp001:2" and stored["expires_at"] > time.time() + 3000 and stored["refreshed_at"]


async def test_disconnect_revokes_access_at_once(admin, auth_server, items_api, as_user):
    await link(admin, auth_server, items_api, "emp001")
    assert (await admin.delete(f"/api/registry/{items_api}/connections/emp001")).status_code == 200
    assert (await admin.delete(f"/api/registry/{items_api}/connections/emp001")).status_code == 404
    as_user("emp001")
    async with Client(gateway()) as c:
        with pytest.raises(ToolError, match="Account not connected"):
            await c.call_tool("items_api_listItems", {})


async def test_bad_or_replayed_callbacks_are_refused(admin, auth_server, items_api):
    start = (await admin.post(f"/api/registry/{items_api}/oauth/start", json={"user_id": "emp001"})).json()
    code, nonce = auth_server.issue_code(start["authorization_url"], "emp001")
    r = await admin.get("/oauth/callback", params={"code": code, "state": "forged"}, follow_redirects=False)
    assert "unknown or expired" in unquote(r.headers["location"])
    await admin.get("/oauth/callback", params={"code": code, "state": nonce}, follow_redirects=False)
    again = await admin.get("/oauth/callback", params={"code": code, "state": nonce}, follow_redirects=False)
    assert "oauth_error=" in again.headers["location"], "a nonce is single use"
    denied = await admin.get("/oauth/callback", params={"error": "access_denied", "error_description": "user said no"}, follow_redirects=False)
    assert "user said no" in unquote(denied.headers["location"])


async def test_connection_test_reports_oauth_state(admin, auth_server, items_api, monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr("portal.app.httpx.AsyncClient",
                        lambda *a, **k: real(*a, **{**k, "transport": httpx.ASGITransport(app=protected_api)}))
    checks = {x["check"]: x for x in (await admin.post(f"/api/registry/{items_api}/test")).json()["results"]}
    assert checks["Protected endpoint rejects missing token"]["ok"] and checks["OAuth configuration"]["ok"]


# --- an MCP backend in OAuth mode: tools appear once someone has linked an account ----------------
tasks = FastMCP("Tasks")


@tasks.tool(annotations={"readOnlyHint": True})
def list_tasks() -> list[str]:
    return ["close the books"]


async def test_mcp_backend_in_oauth_mode(admin, auth_server, as_user, monkeypatch):
    seen: list[dict] = []

    def portal_client(url, headers):
        seen.append(dict(headers))
        return Client(tasks)

    monkeypatch.setattr(portal_module, "mcp_client", portal_client)
    r = await admin.post("/api/registry", json={"name": "Tasks", "kind": "mcp", "base_url": "http://tasks.test/mcp", "auth_mode": "oauth"})
    assert r.status_code == 201 and r.json()["tool_count"] == 0 and "connect an account" in r.json()["note"].lower()
    pid = r.json()["id"]
    assert (await admin.post(f"/api/registry/{pid}/refresh-tools", json={})).status_code == 409, "no token to list with yet"

    await admin.post(f"/api/registry/{pid}/oauth/discover", json={"url": AS})
    await admin.post(f"/api/registry/{pid}/publish")
    await link(admin, auth_server, pid, "emp001")
    listed = next(p for p in (await admin.get("/api/registry")).json()["items"] if p["id"] == pid)
    assert listed["tool_count"] == 1 and seen[-1]["Authorization"] == "Bearer at:emp001:1", "linking loads the tool list at once"
    refreshed = (await admin.post(f"/api/registry/{pid}/refresh-tools", json={"user_id": "emp001"})).json()
    assert refreshed["tool_count"] == 1

    gateway_headers: list[dict] = []

    def factory(provider, headers):
        gateway_headers.append(headers)
        return ProxyClient(tasks)

    as_user("emp001")
    async with Client(gateway(factory)) as c:
        assert "tasks_list_tasks" in {t.name for t in await c.list_tools()}
        assert (await c.call_tool("tasks_list_tasks", {})).structured_content["result"] == ["close the books"]
    assert gateway_headers[-1] == {"Authorization": "Bearer at:emp001:1"}, "the caller's own token reaches the backend"

    as_user("emp002")
    async with Client(gateway(factory)) as c:
        with pytest.raises(ToolError, match="Account not connected"):
            await c.call_tool("tasks_list_tasks", {})


async def test_mcp_backend_tools_survive_an_expired_token(admin, auth_server, as_user, monkeypatch):
    """After a restart or an idle hour every stored token may be expired; listing must refresh one, not go empty."""
    monkeypatch.setattr(portal_module, "mcp_client", lambda url, headers: Client(tasks))
    pid = (await admin.post("/api/registry", json={"name": "Tasks", "kind": "mcp", "base_url": "http://tasks.test/mcp", "auth_mode": "oauth"})).json()["id"]
    await admin.post(f"/api/registry/{pid}/oauth/discover", json={"url": AS})
    await admin.post(f"/api/registry/{pid}/publish")
    await link(admin, auth_server, pid, "emp001")
    state = policy_store.load()
    state["user_connections"]["emp001"][pid]["expires_at"] = time.time() - 1
    policy_store.save(state)

    headers: list[dict] = []

    def factory(provider, h):
        headers.append(h)
        return ProxyClient(tasks)

    # A bare listing by someone with no linked account (a new connector handshake, say).
    as_user("emp002")
    async with Client(gateway(factory)) as c:
        assert "tasks_list_tasks" in {t.name for t in await c.list_tools()}
    assert auth_server.refreshed == 1 and headers[-1] == {"Authorization": "Bearer at:emp001:2"}, "listed with a refreshed token"
    assert policy_store.load()["user_connections"]["emp001"][pid]["access_token"] == "at:emp001:2", "and the refresh was kept"

    # The auth server going away does not break the gateway: listing goes ahead without a fresh token
    # (this mock backend is open; a real one would answer 401 and list nothing until the server is back).
    def dead(request):
        raise httpx.ConnectError("connection refused", request=request)
    monkeypatch.setattr(oauth, "http_client_factory", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(dead), **kw))
    state = policy_store.load()
    state["user_connections"]["emp001"][pid]["expires_at"] = time.time() - 1
    policy_store.save(state)
    async with Client(gateway(factory)) as c:
        names = {t.name for t in await c.list_tools()}
    assert names and auth_server.refreshed == 1 and "Authorization" not in headers[-1], "no refresh possible, gateway still up"


async def test_auth_server_down_during_refresh_reads_as_that(admin, auth_server, items_api, as_user, monkeypatch):
    await link(admin, auth_server, items_api, "emp001")
    state = policy_store.load()
    state["user_connections"]["emp001"][items_api]["expires_at"] = time.time() - 1
    policy_store.save(state)

    def dead(request):
        raise httpx.ConnectError("connection refused", request=request)
    monkeypatch.setattr(oauth, "http_client_factory", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(dead), **kw))
    as_user("emp001")
    async with Client(gateway()) as c:
        with pytest.raises(ToolError, match="auth server unreachable"):
            await c.call_tool("items_api_listItems", {})
