"""A proxied MCP backend must see the credential the gateway chose, never the caller's agent token."""

import asyncio

import httpx
import pytest
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.dependencies import get_http_request

from bizplay_mcp.registry_gateway import build_registry_gateway
from portal.app import app as portal_app, create_app


async def _serve(app):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    return server, task, f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"


@pytest.fixture
async def backend():
    """An MCP server that reports the Authorization header each call arrived with."""
    mcp = FastMCP("Echo")

    @mcp.tool
    def get_auth_header() -> str:
        """Every Authorization header value this server received, joined with ' | '."""
        return " | ".join(get_http_request().headers.getlist("authorization"))

    server, task, url = await _serve(mcp.http_app(path="/mcp", host_origin_protection=False))
    yield url + "/mcp"
    server.should_exit = True
    await task


@pytest.fixture
async def admin(monkeypatch):
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "false")
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        r = await c.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


@pytest.fixture
async def gateway():
    server, task, url = await _serve(create_app(build_registry_gateway()))
    yield url
    server.should_exit = True
    await task


async def test_agent_token_is_not_forwarded_to_the_backend(admin, backend, gateway):
    r = await admin.post("/api/registry", json={"name": "Echo", "kind": "mcp", "base_url": backend, "auth_mode": "bearer", "service_token": "svc-token"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert (await admin.post(f"/api/registry/{pid}/publish")).status_code == 200
    agent = (await admin.post("/api/tokens", json={"label": "t", "user_id": "emp001"})).json()["token"]

    # Anonymous caller: the backend gets the service token.
    async with Client(StreamableHttpTransport(f"{gateway}/mcp")) as c:
        assert (await c.call_tool("echo_get_auth_header", {})).data == "Bearer svc-token"
    # A caller with an agent token: the backend still gets the service token, and lists as usual.
    async with Client(StreamableHttpTransport(f"{gateway}/mcp", auth=agent)) as c:
        assert "echo_get_auth_header" in {t.name for t in await c.list_tools()}, "listing must not break when a token is presented"
        seen = (await c.call_tool("echo_get_auth_header", {})).data
        assert seen == "Bearer svc-token", f"backend saw {seen!r} (a second Authorization header is the caller's token leaking upstream)"
