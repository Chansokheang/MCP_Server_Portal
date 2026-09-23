"""Guidance for the model: composed instructions, identity-bound parameters and tool names, across several backends."""

import asyncio

import httpx
import httpx2
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from bizplay_mcp.registry_gateway import build_registry_gateway
from portal.app import app as portal_app, create_app


async def bots(request: Request):
    return JSONResponse({"corpNo": request.path_params["corpNo"], "bots": [{"id": "bot-1", "name": "Travel QA"}]})


async def chat(request: Request):
    body = await request.json()
    return JSONResponse({"botId": request.path_params["id"], "answer": f"echo: {body.get('question')}", "askedBy": body.get("employeeId")})


async def invoices(request: Request):
    return JSONResponse({"corpNo": request.query_params.get("corpNo"), "invoices": [1, 2]})

api = Starlette(routes=[Route("/api/bots/by-corp/{corpNo}", bots), Route("/api/bots/{id}/chat", chat, methods=["POST"]), Route("/api/invoices", invoices)])

CHATBOT = {"openapi": "3.0.3", "info": {"title": "Chatbot", "version": "1"}, "paths": {
    "/api/bots/by-corp/{corpNo}": {"get": {"operationId": "list_2", "summary": "List bots", "parameters": [
        {"name": "corpNo", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "ok"}}}},
    "/api/bots/{id}/chat": {"post": {"operationId": "chat", "summary": "Chat", "parameters": [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["question"], "properties": {
            "question": {"type": "string"}, "employeeId": {"type": "string"}}}}}}, "responses": {"200": {"description": "ok"}}}}}}
BILLING = {"openapi": "3.0.3", "info": {"title": "Billing", "version": "1"}, "paths": {
    "/api/invoices": {"get": {"operationId": "listInvoices", "summary": "List invoices", "parameters": [
        {"name": "corpNo", "in": "query", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "ok"}}}}}}


@pytest.fixture
async def admin(monkeypatch):
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "false")
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        r = await c.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
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


async def register(admin, name, spec):
    r = await admin.post("/api/registry", json={"name": name, "base_url": "http://x.test", "spec": spec, "auth_mode": "open"})
    assert r.status_code == 201, r.text
    assert (await admin.post(f"/api/registry/{r.json()['id']}/publish")).status_code == 200
    return r.json()["id"]


async def test_two_backends_one_gateway_guided_end_to_end(admin, served):
    chatbot, billing = await register(admin, "Chatbot", CHATBOT), await register(admin, "Billing", BILLING)
    other = await register(admin, "Other", BILLING)
    await admin.put(f"/api/registry/{chatbot}/tools/chat", json={"enabled": True, "confirm": False, "roles": ["employee", "manager"]})

    # The portal lists each backend's parameters with a suggestion, never a silent default.
    params = {i["name"]: i for i in (await admin.get(f"/api/registry/{chatbot}/params")).json()["items"]}
    assert params["corpNo"]["suggested"] == "company" and params["employeeId"]["suggested"] == "user"
    assert params["corpNo"]["bound"] == "company", "company parameters are bound from the start"
    assert params["question"]["suggested"] is None

    # Guidance is per backend, so every gateway that serves the backend inherits it.
    r = await admin.patch(f"/api/registry/{chatbot}", json={
        "instructions": "To answer a policy question: 1) listBots to get a botId, 2) askBot with that id. Never ask the user for a botId.",
        "bound_params": {"employeeId": "user", "nonsense": "moon"}})
    assert r.status_code == 200 and r.json()["bound_params"] == {"corpNo": "company", "employeeId": "user"}, "corpNo is filled in without any setup"
    assert params["corpNo"]["implicit"] is True
    await admin.patch(f"/api/registry/{billing}", json={"instructions": "Invoices are per company."})
    await admin.patch(f"/api/registry/{other}", json={"instructions": "NOT IN THIS GATEWAY"})

    # Tool names the model can read.
    assert (await admin.put(f"/api/registry/{chatbot}/tools/list_2", json={"alias": "listBots"})).json()["alias"] == "listBots"
    assert (await admin.put(f"/api/registry/{chatbot}/tools/chat", json={"alias": "askBot"})).status_code == 200
    assert (await admin.put(f"/api/registry/{chatbot}/tools/chat", json={"alias": "listBots"})).status_code == 400, "aliases are unique per backend"
    assert (await admin.put(f"/api/registry/{chatbot}/tools/chat", json={"alias": "2bad name"})).status_code == 400

    await admin.post("/api/gateways", json={"name": "Help Desk", "providers": [chatbot, billing]})
    await admin.put("/api/endpoints/help-desk/settings", json={"require_token": True, "instructions": "You are the help desk assistant."})
    preview = (await admin.get("/api/endpoints/help-desk/instructions", params={"as": "emp001"})).json()
    assert preview["text"].startswith("You are the help desk assistant.") and "listBots" in preview["text"] and "NOT IN THIS GATEWAY" not in preview["text"]

    minji = (await admin.post("/api/tokens", json={"label": "m", "user_id": "emp001"})).json()["token"]
    async with Client(StreamableHttpTransport(f"{served}/mcp/help-desk", auth=minji)) as c:
        told = c.instructions
        assert "help desk assistant" in told and "## Chatbot" in told and "## Billing" in told and "NOT IN THIS GATEWAY" not in told
        assert "corpNo" in told and "employeeId" in told and "never be asked for" in told, "the model is told what is filled in for it"

        tools = {t.name: t for t in await c.list_tools()}
        assert {"chatbot_listBots", "chatbot_askBot", "billing_listInvoices"} <= set(tools) and "chatbot_list_2" not in tools
        assert "corpNo" not in tools["chatbot_listBots"].input_schema.get("properties", {}), "bound parameters leave the schema"
        assert "corpNo" not in (tools["chatbot_listBots"].input_schema.get("required") or [])
        ask = tools["chatbot_askBot"].input_schema["properties"]
        assert "question" in ask and "id" in ask and "employeeId" not in ask

        # Called with no company at all: the caller's own goes upstream, on both backends.
        assert (await c.call_tool("chatbot_listBots", {})).structured_content["corpNo"] == "1078836129"
        assert (await c.call_tool("billing_listInvoices", {})).structured_content["corpNo"] == "1078836129"
        # Whatever the model sends is replaced, not trusted.
        assert (await c.call_tool("chatbot_listBots", {"corpNo": "ACME-001"})).structured_content["corpNo"] == "1078836129"
        got = (await c.call_tool("chatbot_askBot", {"id": "bot-1", "question": "per diem?", "employeeId": "someone-else"})).structured_content
        assert got["answer"] == "echo: per diem?" and got["askedBy"] == "emp001"

    # No token, no identity to bind to: the parameter is visible again and the shared endpoint says nothing about filling it.
    async with Client(StreamableHttpTransport(f"{served}/mcp")) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert "employeeId" in tools["chatbot_askBot"].input_schema["properties"], "the demo identity has no user id to bind"
        assert "NOT IN THIS GATEWAY" in (c.instructions or ""), "the shared endpoint serves every backend"

    # Handshake-era clients (claude.ai today) get the same text from initialize.
    async with Client(StreamableHttpTransport(f"{served}/mcp/help-desk", auth=minji), mode="legacy") as c:
        assert "help desk assistant" in c.initialize_result.instructions and "## Billing" in c.initialize_result.instructions

    # A deployed backend alone: plain names, its own notes only.
    assert (await admin.post(f"/api/registry/{chatbot}/deploy")).status_code == 200
    async with Client(StreamableHttpTransport(f"{served}/mcp/{chatbot}", auth=minji)) as c:
        assert "listBots" in {t.name for t in await c.list_tools()}
        assert "Billing" not in c.instructions and "listBots to get a botId" in c.instructions
        assert (await c.call_tool("listBots", {})).structured_content["corpNo"] == "1078836129"

    # Removing an alias restores the original name; the company stays filled in, since that needs no setup.
    await admin.put(f"/api/registry/{chatbot}/tools/list_2", json={"alias": ""})
    await admin.patch(f"/api/registry/{chatbot}", json={"bound_params": {}})
    async with Client(StreamableHttpTransport(f"{served}/mcp/help-desk", auth=minji)) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert "chatbot_list_2" in tools and "corpNo" not in tools["chatbot_list_2"].input_schema["properties"]
        assert "employeeId" in tools["chatbot_askBot"].input_schema["properties"], "the explicit binding was removed"


async def test_usage_notes_over_the_limit_are_refused_not_cut(admin, served):
    from bizplay_mcp import guidance
    pid = (await admin.get("/api/registry")).json()["items"][0]["id"]
    r = await admin.patch(f"/api/registry/{pid}", json={"instructions": "x" * (guidance.MAX_INSTRUCTIONS + 1)})
    assert r.status_code == 400 and "limited to" in r.json()["error"]
    r = await admin.patch(f"/api/registry/{pid}", json={"instructions": "y" * guidance.MAX_INSTRUCTIONS})
    assert r.status_code == 200 and len(r.json()["instructions"]) == guidance.MAX_INSTRUCTIONS
    r = await admin.put("/api/endpoints/_shared/settings", json={"instructions": "z" * (guidance.MAX_INSTRUCTIONS + 1)})
    assert r.status_code == 400
