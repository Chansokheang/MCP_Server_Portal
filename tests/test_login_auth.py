"""Login-endpoint auth: the gateway signs in with a username and password, as a service account or per user."""

import time

import httpx
import httpx2
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from bizplay_mcp import login_auth, policy_store
from bizplay_mcp.registry_gateway import build_registry_gateway
from portal.app import app as portal_app


class LoginApi:
    """An API with its own POST /login: returns a token nested in the JSON, accepts it as a bearer."""

    def __init__(self, header="Authorization", scheme="Bearer"):
        self.users = {"svc": "svc-pw", "minji": "minji-pw", "junho": "junho-pw"}
        self.logins = 0
        self.tokens: dict[str, str] = {}
        self.header, self.scheme = header, scheme
        self.app = Starlette(routes=[Route("/login", self.login, methods=["POST"]), Route("/whoami", self.whoami)])

    async def login(self, request: Request):
        body = await request.json()
        if self.users.get(body.get("username")) != body.get("password"):
            return JSONResponse({"message": "bad credentials"}, status_code=401)
        self.logins += 1
        token = f"tok-{body['username']}-{self.logins}"
        self.tokens[token] = body["username"]
        return JSONResponse({"data": {"accessToken": token, "expiresIn": 3600}})

    async def whoami(self, request: Request):
        presented = request.headers.get(self.header, "")
        if self.scheme:
            presented = presented.removeprefix(self.scheme + " ")
        user = self.tokens.get(presented)
        return JSONResponse({"user": user}) if user else JSONResponse({"error": "no"}, status_code=401)


SPEC = {"openapi": "3.0.3", "info": {"title": "Login API", "version": "1"},
        "paths": {"/whoami": {"get": {"operationId": "whoami", "responses": {"200": {"description": "ok"}}}}}}


@pytest.fixture
def api(monkeypatch):
    backend = LoginApi()
    monkeypatch.setattr(login_auth, "http_client_factory", lambda **kw: httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), **kw))
    return backend


def gateway(api):
    return build_registry_gateway(transport_factory=lambda p: httpx2.ASGITransport(app=api.app))


async def _login(c, email, password):
    r = await c.post("/api/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"


@pytest.fixture
async def admin(monkeypatch):
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "false")
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        await _login(c, "admin@bizplay.co.kr", "admin1234")
        yield c


@pytest.fixture
def as_user(monkeypatch):
    def _set(user: str) -> None:
        monkeypatch.setenv("BIZPLAY_USER_ID", user)
        monkeypatch.delenv("BIZPLAY_COMPANY", raising=False)
    return _set


LOGIN = {"url": "http://api.test/login", "body": '{"username": "{username}", "password": "{password}"}',
         "token_path": "data.accessToken", "expires_path": "data.expiresIn"}


async def test_service_account_signs_in_once_and_again_when_needed(admin, api, as_user):
    r = await admin.post("/api/registry", json={"name": "Login API", "base_url": "http://api.test", "spec": SPEC, "auth_mode": "login",
                                                "login": LOGIN, "login_username": "svc", "login_password": "svc-pw"})
    assert r.status_code == 201, r.text
    p = r.json()
    pid = p["id"]
    assert p["login_ready"] and not p["per_user"] and p["service_account"]["username"] == "svc" and p["service_account"]["has_password"]
    assert (await admin.post(f"/api/registry/{pid}/publish")).status_code == 200

    as_user("emp001")
    async with Client(gateway(api)) as c:
        assert (await c.call_tool(f"login_api_whoami", {})).structured_content["user"] == "svc"
        assert (await c.call_tool(f"login_api_whoami", {})).structured_content["user"] == "svc"
    assert api.logins == 1, "signed in once; the token is cached"
    cached = policy_store.load()["credentials"][f"cred_{pid}_service"]["cached"]
    assert cached["access_token"] == "tok-svc-1" and cached["expires_at"] > time.time() + 3000

    # Expired cache: signs in again before the call.
    state = policy_store.load()
    state["credentials"][f"cred_{pid}_service"]["cached"]["expires_at"] = time.time() - 1
    policy_store.save(state)
    async with Client(gateway(api)) as c:
        assert (await c.call_tool(f"login_api_whoami", {})).structured_content["user"] == "svc"
    assert api.logins == 2

    # The backend revokes the token: the 401 clears the cache, the next call signs in again.
    api.tokens.clear()
    async with Client(gateway(api)) as c:
        with pytest.raises(ToolError):
            await c.call_tool(f"login_api_whoami", {})
        assert (await c.call_tool(f"login_api_whoami", {})).structured_content["user"] == "svc"
    assert api.logins == 3

    # A wrong password is reported as a sign-in failure, not a gateway fault.
    state = policy_store.load()
    state["credentials"][f"cred_{pid}_service"].update(secret="nope", cached={})
    policy_store.save(state)
    async with Client(gateway(api)) as c:
        with pytest.raises(ToolError, match="sign-in failed"):
            await c.call_tool(f"login_api_whoami", {})


async def test_per_user_sign_in(admin, api, as_user):
    r = await admin.post("/api/registry", json={"name": "Login API", "base_url": "http://api.test", "spec": SPEC, "auth_mode": "login",
                                                "login": {**LOGIN, "per_user": True}})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["per_user"] and (await admin.post(f"/api/registry/{pid}/publish")).status_code == 200, "no service account needed"

    # Wrong password is refused at connect time, so nothing bad is stored.
    bad = await admin.post(f"/api/registry/{pid}/login/connect", json={"user_id": "emp001", "username": "minji", "password": "wrong"})
    assert bad.status_code == 400 and "refused" in bad.json()["error"]
    ok = await admin.post(f"/api/registry/{pid}/login/connect", json={"user_id": "emp001", "username": "minji", "password": "minji-pw"})
    assert ok.status_code == 201 and ok.json()["kind"] == "login" and ok.json()["username"] == "minji" and ok.json()["user_name"] == "Kim Minji"

    # A member connects themselves; the user_id they send is ignored.
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as junho:
        await _login(junho, "junho@bizplay.co.kr", "junho1234")
        r = await junho.post(f"/api/registry/{pid}/login/connect", json={"user_id": "emp001", "username": "junho", "password": "junho-pw"})
        assert r.status_code == 201 and r.json()["user_id"] == "emp002"
        assert [c["user_id"] for c in (await junho.get(f"/api/registry/{pid}/connections")).json()["items"]] == ["emp002"]
    assert [c["user_id"] for c in (await admin.get(f"/api/registry/{pid}/connections")).json()["items"]] == ["emp001", "emp002"]

    as_user("emp001")
    async with Client(gateway(api)) as c:
        assert (await c.call_tool("login_api_whoami", {})).structured_content["user"] == "minji"
    as_user("emp002")
    async with Client(gateway(api)) as c:
        assert (await c.call_tool("login_api_whoami", {})).structured_content["user"] == "junho"
    as_user("mgr001")
    async with Client(gateway(api)) as c:
        with pytest.raises(ToolError, match="Account not connected"):
            await c.call_tool("login_api_whoami", {})

    # Disconnect drops the stored credentials at once.
    assert (await admin.delete(f"/api/registry/{pid}/connections/emp001")).status_code == 200
    as_user("emp001")
    async with Client(gateway(api)) as c:
        with pytest.raises(ToolError, match="Account not connected"):
            await c.call_tool("login_api_whoami", {})


async def test_custom_header_and_config_validation(admin, monkeypatch, as_user):
    backend = LoginApi(header="X-Auth-Token", scheme="")
    monkeypatch.setattr(login_auth, "http_client_factory", lambda **kw: httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), **kw))
    r = await admin.post("/api/registry", json={"name": "Keyed API", "base_url": "http://api.test", "spec": SPEC, "auth_mode": "login",
                                                "login": {**LOGIN, "header": "X-Auth-Token", "scheme": ""}, "login_username": "svc", "login_password": "svc-pw"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    await admin.post(f"/api/registry/{pid}/publish")
    as_user("emp001")
    async with Client(gateway(backend)) as c:
        assert (await c.call_tool("keyed_api_whoami", {})).structured_content["user"] == "svc"

    # Publishing needs a login URL and a service account (unless per user).
    r = await admin.post("/api/registry", json={"name": "Half", "base_url": "http://api.test", "spec": SPEC, "auth_mode": "login", "login": {"url": "http://api.test/login"}})
    assert r.status_code == 201
    assert (await admin.post(f"/api/registry/{r.json()['id']}/publish")).status_code == 409
    bad = await admin.post("/api/registry", json={"name": "Bad", "base_url": "http://api.test", "spec": SPEC, "auth_mode": "login", "login": {**LOGIN, "body": "not json {username}"}})
    assert bad.status_code == 400 and "JSON" in bad.json()["error"]
    # Security page never exposes the cached token or the password.
    sec = (await admin.get("/api/security")).json()
    cred = next(c for c in sec["credentials"] if c["provider_id"] == pid)
    assert "cached" not in cred and cred["secret"] != "svc-pw" and cred["username"] == "svc" and cred["type"] == "login"
