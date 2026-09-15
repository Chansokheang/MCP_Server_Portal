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
