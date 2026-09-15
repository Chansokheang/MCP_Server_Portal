"""One gateway address, different services per caller: entitlement by access group or company."""

import httpx
import httpx2
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from bizplay_mcp import policy_store
from bizplay_mcp.auth import PortalTokenVerifier
from bizplay_mcp.registry_gateway import build_registry_gateway
from portal.app import app as portal_app

api = Starlette(routes=[Route("/ping", lambda r: JSONResponse({"ok": True}))])


def spec(title):
    return {"openapi": "3.0.3", "info": {"title": title, "version": "1"},
            "paths": {"/ping": {"get": {"operationId": "ping", "responses": {"200": {"description": "ok"}}}}}}


@pytest.fixture
async def admin():
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        r = await c.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


@pytest.fixture
async def three_services(admin):
    """finance-only, hr-only, and one for everyone."""
    ids = {}
    for name, access in (("Finance", {"mode": "groups", "groups": "finance"}),
                         ("HR", {"mode": "groups", "groups": ["hr"]}),
                         ("Public", {"mode": "everyone"})):
        r = await admin.post("/api/registry", json={"name": name, "base_url": "http://x.test", "spec": spec(name), "auth_mode": "open"})
        pid = r.json()["id"]
        assert (await admin.patch(f"/api/registry/{pid}", json={"access": access})).status_code == 200
        await admin.post(f"/api/registry/{pid}/publish")
        ids[name] = pid
    return ids


def gateway():
    return build_registry_gateway(transport_factory=lambda p: httpx2.ASGITransport(app=api))


@pytest.fixture
def as_groups(monkeypatch):
    def _set(groups: str) -> None:
        monkeypatch.setenv("BIZPLAY_GROUPS", groups)
    return _set


async def visible(c):
    return {t.name for t in await c.list_tools() if t.name.endswith("_ping")}


async def test_same_address_different_services_per_caller(three_services, as_groups):
    as_groups("finance")                      # user A
    async with Client(gateway()) as c:
        assert await visible(c) == {"finance_ping", "public_ping"}
    as_groups("finance,hr")                   # user B
    async with Client(gateway()) as c:
        assert await visible(c) == {"finance_ping", "hr_ping", "public_ping"}
    as_groups("")                             # nobody special
    async with Client(gateway()) as c:
        assert await visible(c) == {"public_ping"}
        with pytest.raises(ToolError, match="limited to access group"):
            await c.call_tool("hr_ping", {})


async def test_company_entitlement(admin, three_services, monkeypatch):
    await admin.patch(f"/api/registry/{three_services['Public']}", json={"access": {"mode": "companies", "companies": "1078836129"}})
    monkeypatch.setenv("BIZPLAY_COMPANY", "2200000000")
    async with Client(gateway()) as c:
        assert "public_ping" not in await visible(c)
    monkeypatch.setenv("BIZPLAY_COMPANY", "1078836129")
    async with Client(gateway()) as c:
        assert "public_ping" in await visible(c)


async def test_tokens_carry_groups_and_the_verifier_exposes_them(admin):
    r = await admin.post("/api/tokens", json={"label": "B", "user_id": "emp002", "role": "employee", "groups": "hr, finance"})
    assert r.status_code == 201 and r.json()["record"]["groups"] == ["finance", "hr"]
    verified = await PortalTokenVerifier().verify_token(r.json()["token"])
    assert verified.claims["groups"] == ["finance", "hr"]
    assert (await admin.get("/api/groups")).json()["items"] == ["finance", "hr"]


async def test_entitlement_validation(admin, three_services):
    bad = await admin.patch(f"/api/registry/{three_services['HR']}", json={"access": {"mode": "groups", "groups": ""}})
    assert bad.status_code == 400
    bad = await admin.patch(f"/api/registry/{three_services['HR']}", json={"access": {"mode": "vip"}})
    assert bad.status_code == 400
