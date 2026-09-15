"""Named gateways: a chosen set of backends on their own URL, next to /mcp and /mcp/<backend>."""

import asyncio

import httpx
import httpx2
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from bizplay_mcp.registry_gateway import build_registry_gateway
from portal.app import app as portal_app, create_app

api = Starlette(routes=[Route("/ping", lambda r: JSONResponse({"ok": True}))])


def spec(title):
    return {"openapi": "3.0.3", "info": {"title": title, "version": "1"},
            "paths": {"/ping": {"get": {"operationId": "ping", "responses": {"200": {"description": "ok"}}}}}}


@pytest.fixture
async def admin(monkeypatch):
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "false")
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        r = await c.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


@pytest.fixture
async def services(admin):
    ids = []
    for name in ("Alpha", "Beta", "Gamma"):
        r = await admin.post("/api/registry", json={"name": name, "base_url": "http://x.test", "spec": spec(name), "auth_mode": "open"})
        await admin.post(f"/api/registry/{r.json()['id']}/publish")
        ids.append(r.json()["id"])
    return ids


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


async def names(url):
    async with Client(StreamableHttpTransport(url)) as c:
        return {t.name for t in await c.list_tools() if t.name.endswith("_ping")}


async def test_named_gateway_serves_only_its_backends(admin, services, served):
    alpha, beta, gamma = services
    r = await admin.post("/api/gateways", json={"name": "Finance Suite", "providers": [alpha, beta]})
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["id"] == "finance-suite" and g["url"].endswith("/mcp/finance-suite") and [b["id"] for b in g["backends"]] == [alpha, beta]

    assert await names(f"{served}/mcp") == {"alpha_ping", "beta_ping", "gamma_ping"}, "the shared endpoint is unchanged"
    assert await names(f"{served}/mcp/finance-suite") == {"alpha_ping", "beta_ping"}, "prefixed, but only the chosen backends"
    async with Client(StreamableHttpTransport(f"{served}/mcp/finance-suite")) as c:
        assert (await c.call_tool("alpha_ping", {})).structured_content["ok"] is True
        with pytest.raises(ToolError, match="not part of this gateway"):
            await c.call_tool("gamma_ping", {})

    # Membership changes apply on the next request, no restart.
    await admin.patch("/api/gateways/finance-suite", json={"providers": [alpha, gamma]})
    assert await names(f"{served}/mcp/finance-suite") == {"alpha_ping", "gamma_ping"}

    await admin.delete("/api/gateways/finance-suite")
    async with httpx.AsyncClient() as http:
        assert (await http.post(f"{served}/mcp/finance-suite", json={})).status_code == 404


async def test_gateway_validation(admin, services):
    assert (await admin.post("/api/gateways", json={"name": "", "providers": services})).status_code == 400
    assert (await admin.post("/api/gateways", json={"name": "Nope", "providers": ["ghost"]})).status_code == 400
    assert (await admin.post("/api/gateways", json={"name": services[0], "providers": services})).status_code == 409, "must not shadow a backend's own /mcp/<id>"
    ok = await admin.post("/api/gateways", json={"name": "All of it", "providers": ",".join(services)})
    assert ok.status_code == 201 and len(ok.json()["backends"]) == 3
    assert (await admin.post("/api/gateways", json={"name": "All of it", "providers": services})).status_code == 409


async def test_token_requirement_and_entitlement_are_per_endpoint(admin, services, served, monkeypatch):
    """The shared endpoint can stay open while a named gateway demands a token and a group."""
    monkeypatch.delenv("BIZPLAY_REQUIRE_AGENT_TOKEN", raising=False)
    # The portal's default applies live (no restart): open by default here, finance overrides to required.
    assert (await admin.put("/api/security", json={"require_gateway_bearer": False})).status_code == 200
    alpha, beta, gamma = services
    await admin.post("/api/gateways", json={"name": "Finance", "providers": [alpha, beta]})
    r = await admin.put("/api/endpoints/finance/settings", json={"require_token": True, "access": {"mode": "groups", "groups": "finance"}})
    assert r.status_code == 200 and r.json()["require_token"] is True and not r.json()["inherits"]
    finance_tok = (await admin.post("/api/tokens", json={"label": "f", "user_id": "emp001", "role": "employee", "groups": "finance"})).json()["token"]
    hr_tok = (await admin.post("/api/tokens", json={"label": "h", "user_id": "emp002", "role": "employee", "groups": "hr"})).json()["token"]

    async with httpx.AsyncClient() as http:
        assert (await http.post(f"{served}/mcp/finance", json={})).status_code == 401, "no token: refused"
        assert "www-authenticate" in (await http.post(f"{served}/mcp/finance", json={})).headers
        assert (await http.post(f"{served}/mcp/finance", json={}, headers={"Authorization": "Bearer bogus"})).status_code == 401
        assert (await http.post(f"{served}/mcp/finance", json={}, headers={"Authorization": f"Bearer {hr_tok}"})).status_code == 403, "wrong group"
    assert await names(f"{served}/mcp") == {"alpha_ping", "beta_ping", "gamma_ping"}, "the shared endpoint is untouched (inherits: not required)"
    async with Client(StreamableHttpTransport(f"{served}/mcp/finance", auth=finance_tok)) as c:
        assert {t.name for t in await c.list_tools() if t.name.endswith("_ping")} == {"alpha_ping", "beta_ping"}

    # Back to inheriting the (open) default: no token needed again, live.
    await admin.put("/api/endpoints/finance/settings", json={"require_token": None, "access": {"mode": "everyone"}})
    assert await names(f"{served}/mcp/finance") == {"alpha_ping", "beta_ping"}
    assert (await admin.get("/api/endpoints/nope/settings")).status_code == 404
