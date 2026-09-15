"""User directory: tokens and linked accounts belong to listed people; members serve themselves."""

import httpx
import pytest

from bizplay_mcp.auth import PortalTokenVerifier
from portal.app import app as portal_app


def _client():
    return httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app))


async def _login(c, email, password):
    r = await c.post("/api/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return r.json()["user"]


@pytest.fixture
async def admin(monkeypatch):
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "false")
    async with _client() as c:
        await _login(c, "admin@bizplay.co.kr", "admin1234")
        yield c


@pytest.fixture
async def minji():
    async with _client() as c:
        user = await _login(c, "minji@bizplay.co.kr", "minji1234")
        yield c, user


async def test_directory_is_seeded_and_drives_token_claims(admin):
    users = {u["id"]: u for u in (await admin.get("/api/users")).json()["items"]}
    assert users["emp001"]["name"] == "Kim Minji" and users["emp001"]["groups"] == ["finance"] and users["emp001"]["can_sign_in"]
    assert users["mgr001"]["role"] == "manager" and not users["mgr001"]["can_sign_in"]
    assert "password" not in users["emp001"]

    # Only the user is picked; role, company and groups come from the directory.
    r = await admin.post("/api/tokens", json={"label": "Minji's Claude", "user_id": "emp001"})
    assert r.status_code == 201, r.text
    rec = r.json()["record"]
    assert rec["role"] == "employee" and rec["groups"] == ["finance"] and rec["user_name"] == "Kim Minji"
    claims = (await PortalTokenVerifier().verify_token(r.json()["token"])).claims
    assert claims["groups"] == ["finance"]
    assert (await admin.get("/api/tokens")).json()["items"][0]["user_name"] == "Kim Minji"

    # Unknown id without a role: refused. With a role: added to the directory as they go.
    assert (await admin.post("/api/tokens", json={"label": "x", "user_id": "ghost"})).status_code == 400
    r = await admin.post("/api/tokens", json={"label": "y", "user_id": "Emp003", "role": "manager", "name": "Choi Yuna", "groups": "hr"})
    assert r.status_code == 201 and r.json()["record"]["sub"] == "emp003"
    added = next(u for u in (await admin.get("/api/users")).json()["items"] if u["id"] == "emp003")
    assert added["name"] == "Choi Yuna" and added["role"] == "manager" and added["groups"] == ["hr"] and added["active_tokens"] == 1


async def test_admin_manages_the_directory(admin):
    r = await admin.post("/api/users", json={"id": "emp010", "name": "Han Sora", "email": "sora@bizplay.co.kr", "role": "employee", "groups": "finance, hr", "password": "sora1234"})
    assert r.status_code == 201 and r.json()["groups"] == ["finance", "hr"] and r.json()["can_sign_in"]
    assert (await admin.post("/api/users", json={"id": "emp010", "name": "dup"})).status_code == 409
    assert (await admin.post("/api/users", json={"id": "emp011", "name": "x", "email": "sora@bizplay.co.kr"})).status_code == 409, "email must be unique"
    assert (await admin.post("/api/users", json={"id": "emp012", "name": "x", "password": "123"})).status_code == 400, "short password"
    r = await admin.patch("/api/users/emp010", json={"role": "manager", "groups": "finance"})
    assert r.status_code == 200 and r.json()["role"] == "manager" and r.json()["groups"] == ["finance"]

    # The new member can sign in; removing them ends their session and revokes their tokens.
    async with _client() as c:
        user = await _login(c, "sora@bizplay.co.kr", "sora1234")
        assert user["role"] == "member" and user["user_id"] == "emp010" and user["is_admin"] is False
        tok = (await c.post("/api/tokens", json={"label": "mine"})).json()["token"]
        assert (await PortalTokenVerifier().verify_token(tok)).claims["role"] == "manager"
        assert (await admin.delete("/api/users/emp010")).status_code == 200
        assert await PortalTokenVerifier().verify_token(tok) is None
        assert (await c.get("/api/me")).status_code == 401
    assert (await admin.delete("/api/users/emp010")).status_code == 404


async def test_member_sees_and_touches_only_their_own(admin, minji):
    c, user = minji
    assert user["name"] == "Kim Minji" and user["user_id"] == "emp001" and user["groups"] == ["finance"]
    me = (await c.get("/api/me")).json()
    assert me["is_admin"] is False and me["user_role"] == "employee"

    # Admin-only routes are refused outright.
    for method, path in (("GET", "/api/users"), ("GET", "/api/overview"), ("GET", "/api/audit"), ("GET", "/api/security"),
                         ("POST", "/api/gateways"), ("PATCH", "/api/registry/bizplay")):
        r = await c.request(method, path, json={} if method != "GET" else None)
        assert r.status_code == 403, (method, path, r.status_code)

    # Tokens: whatever user_id a member sends, the token is theirs; they list only their own.
    junho_tok = (await admin.post("/api/tokens", json={"label": "Junho", "user_id": "emp002"})).json()["record"]
    r = await c.post("/api/tokens", json={"label": "Minji's laptop", "user_id": "emp002", "role": "manager"})
    assert r.status_code == 201 and r.json()["record"]["sub"] == "emp001" and r.json()["record"]["role"] == "employee"
    mine = (await c.get("/api/tokens")).json()["items"]
    assert [t["sub"] for t in mine] == ["emp001"]
    assert (await c.post(f"/api/tokens/{junho_tok['id']}/revoke")).status_code == 403
    assert (await c.post(f"/api/tokens/{mine[0]['id']}/revoke")).status_code == 200

    # Registry: published backends only, no drafts.
    draft = (await admin.post("/api/registry", json={"name": "Draft", "base_url": "http://x.test", "auth_mode": "open",
                                                     "spec": {"openapi": "3.0.3", "info": {"title": "d", "version": "1"}, "paths": {}}})).json()
    ids = {p["id"] for p in (await c.get("/api/registry")).json()["items"]}
    assert draft["id"] not in ids and "bizplay" in ids

    # Linked accounts: a member cannot disconnect someone else.
    assert (await c.delete("/api/registry/bizplay/connections/emp002")).status_code == 403
