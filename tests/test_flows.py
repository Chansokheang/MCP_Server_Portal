"""Parameter sources, origins learned from real calls, gateway overrides and workflow tools."""

import asyncio

import httpx
import httpx2
import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from bizplay_mcp import guidance
from bizplay_mcp.registry_gateway import build_registry_gateway
from portal.app import app as portal_app, create_app

CALLS: list[tuple[str, dict]] = []


async def bots(request: Request):
    CALLS.append(("bots", dict(request.query_params)))
    return JSONResponse({"data": [{"id": "bot-77", "name": "Travel QA"}, {"id": "bot-78", "name": "HR"}]})


async def chat(request: Request):
    body = await request.json()
    CALLS.append(("chat", body))
    return JSONResponse({"data": {"answer": f"echo: {body.get('query')}", "sessionId": "sess-1", "channel": body.get("channel"), "pageSize": body.get("pageSize")}})


async def history(request: Request):
    return JSONResponse({"data": {"sessionId": request.path_params["sid"], "messages": 2}})

api = Starlette(routes=[Route("/bots", bots), Route("/chat", chat, methods=["POST"]), Route("/history/{sid}", history)])
SPEC = {"openapi": "3.0.3", "info": {"title": "Bot", "version": "1"}, "paths": {
    "/bots": {"get": {"operationId": "listBots", "summary": "List bots", "parameters": [
        {"name": "corpNo", "in": "query", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "ok"}}}},
    "/chat": {"post": {"operationId": "askBot", "summary": "Ask", "requestBody": {"required": True, "content": {"application/json": {"schema": {
        "type": "object", "required": ["botId", "query"], "properties": {"botId": {"type": "string"}, "query": {"type": "string"},
                                                                          "channel": {"type": "string"}, "pageSize": {"type": "integer"}}}}}},
        "responses": {"200": {"description": "ok"}}}},
    "/history/{sid}": {"get": {"operationId": "getHistory", "summary": "History", "parameters": [
        {"name": "sid", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "ok"}}}}}}


@pytest.fixture
async def admin(monkeypatch):
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "false")
    CALLS.clear()
    guidance._sessions.clear()
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


async def setup(admin):
    r = await admin.post("/api/registry", json={"name": "Bot", "base_url": "http://x.test", "spec": SPEC, "auth_mode": "open"})
    pid = r.json()["id"]
    await admin.post(f"/api/registry/{pid}/publish")
    await admin.put(f"/api/registry/{pid}/tools/askBot", json={"enabled": True, "confirm": False, "roles": ["employee", "manager"]})
    await admin.post("/api/gateways", json={"name": "Desk", "providers": [pid]})
    return pid


async def test_sources_fixed_default_caller_and_gateway_override(admin, served):
    pid = await setup(admin)
    r = await admin.patch(f"/api/registry/{pid}", json={"param_sources": {
        "corpNo": {"kind": "caller", "value": "company"}, "channel": {"kind": "fixed", "value": "claude"}, "pageSize": {"kind": "default", "value": "20"}}})
    assert r.status_code == 200 and r.json()["param_sources"]["pageSize"] == {"kind": "default", "value": 20}, r.text
    assert r.json()["bound_params"] == {"corpNo": "company"}, "older field still derived"
    params = {i["name"]: i for i in (await admin.get(f"/api/registry/{pid}/params")).json()["items"]}
    assert params["channel"]["source"]["kind"] == "fixed" and params["corpNo"]["bound"] == "company"

    tok = (await admin.post("/api/tokens", json={"label": "m", "user_id": "emp001"})).json()["token"]
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        ask = {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema
        assert "channel" not in ask["properties"], "fixed values are hidden"
        assert ask["properties"]["pageSize"]["default"] == 20 and "pageSize" not in ask.get("required", []), "defaults are shown"
        assert "channel" in c.instructions and "corpNo" in c.instructions
        got = (await c.call_tool("bot_askBot", {"botId": "bot-77", "query": "hi"})).structured_content["data"]
        assert got["channel"] == "claude" and got["pageSize"] == 20, "fixed sent, default filled"
        got = (await c.call_tool("bot_askBot", {"botId": "bot-77", "query": "hi", "pageSize": 5, "channel": "web"})).structured_content["data"]
        assert got["pageSize"] == 5 and got["channel"] == "claude", "a given value beats a default; a fixed value is never overridden"

    # This gateway wants a different channel and no default page size.
    r = await admin.put("/api/endpoints/desk/settings", json={"param_sources": {pid: {"channel": {"kind": "fixed", "value": "desk"}, "pageSize": None}}})
    assert r.status_code == 200 and r.json()["param_sources"][pid]["pageSize"] is None
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        ask = {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema
        assert "default" not in ask["properties"]["pageSize"]
        got = (await c.call_tool("bot_askBot", {"botId": "bot-77", "query": "hi"})).structured_content["data"]
        assert got["channel"] == "desk" and got["pageSize"] is None
    async with Client(StreamableHttpTransport(f"{served}/mcp", auth=tok)) as c:
        got = (await c.call_tool("bot_askBot", {"botId": "bot-77", "query": "hi"})).structured_content["data"]
        assert got["channel"] == "claude", "the override is only for that gateway"


async def test_origins_are_learned_from_real_calls_then_confirmed(admin, served):
    pid = await setup(admin)
    tok = (await admin.post("/api/tokens", json={"label": "m", "user_id": "emp001"})).json()["token"]
    # One real session: list, then ask with an id from the list, then history with the session id from the answer.
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        found = (await c.call_tool("bot_listBots", {"corpNo": "1078836129"})).structured_content["data"]
        ans = (await c.call_tool("bot_askBot", {"botId": found[1]["id"], "query": "q"})).structured_content["data"]
        await c.call_tool("bot_getHistory", {"sid": ans["sessionId"]})
        await c.call_tool("bot_askBot", {"botId": found[0]["id"], "query": "again"})
    origins = {f"{o['tool']}.{o['param']}": o for o in (await admin.get(f"/api/registry/{pid}/params")).json()["origins"]}
    assert origins["askBot.botId"]["seen"][0] == {"origin": "listBots.id", "count": 2} and origins["askBot.botId"]["confirmed"] is None
    assert origins["getHistory.sid"]["seen"][0]["origin"] == "askBot.sessionId"
    assert "askBot.query" not in origins, "free text is never an origin"

    # Confirm: the model is told in the schema, and an empty call says what to do first.
    r = await admin.patch(f"/api/registry/{pid}", json={"comes_from": {"askBot.botId": {"tool": "listBots", "field": "id"}, "nope.x": {"tool": "listBots"}}})
    assert r.json()["comes_from"] == {"askBot.botId": {"tool": "listBots", "field": "id"}}
    await admin.put(f"/api/registry/{pid}/tools/listBots", json={"alias": "findBots"})
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        ask = {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema
        assert "Get it from findBots (field id)" in ask["properties"]["botId"]["description"]
        with pytest.raises(ToolError, match="call findBots first"):
            await c.call_tool("bot_askBot", {"query": "no id"})

    # A value typed in by hand: sent on every call of that tool, hidden from the model, and reported as such.
    r = await admin.patch(f"/api/registry/{pid}", json={"comes_from": {"askBot.botId": {"value": "bot-78"}}})
    assert r.json()["comes_from"] == {"askBot.botId": {"value": "bot-78"}}
    origin = next(o for o in (await admin.get(f"/api/registry/{pid}/params")).json()["origins"] if o["param"] == "botId")
    assert origin["fixed"] is True
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        ask = {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema
        assert "botId" not in ask["properties"] and "botId" in c.instructions
        assert (await c.call_tool("bot_askBot", {"query": "fixed"})).structured_content["data"]["answer"] == "echo: fixed"
        assert CALLS[-1][1]["botId"] == "bot-78"
        assert (await c.call_tool("bot_askBot", {"query": "x", "botId": "bot-77"})).structured_content and CALLS[-1][1]["botId"] == "bot-78", "never overridden by the model"

    # A default typed in by hand: the model sees it, and may change it.
    await admin.patch(f"/api/registry/{pid}", json={"comes_from": {"askBot.botId": {"default": "bot-77"}}})
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        ask = {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema
        assert ask["properties"]["botId"]["default"] == "bot-77" and "botId" not in ask.get("required", [])
        await c.call_tool("bot_askBot", {"query": "d"}); assert CALLS[-1][1]["botId"] == "bot-77"
        await c.call_tool("bot_askBot", {"query": "d", "botId": "bot-78"}); assert CALLS[-1][1]["botId"] == "bot-78", "the model's own value wins over a default"

    # Switched off on the backend: kept, reported, but not used.
    r = await admin.patch(f"/api/registry/{pid}", json={"comes_from": {"askBot.botId": {"default": "bot-77", "enabled": False}}})
    assert r.json()["comes_from"]["askBot.botId"] == {"default": "bot-77", "enabled": False}
    assert next(o for o in (await admin.get(f"/api/registry/{pid}/params")).json()["origins"] if o["param"] == "botId")["enabled"] is False
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        ask = {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema
        assert "default" not in ask["properties"]["botId"]

    # One gateway changes the value for its own users: a fixed value here, while the backend keeps its default.
    await admin.patch(f"/api/registry/{pid}", json={"comes_from": {"askBot.botId": {"default": "bot-77"}}})
    r = await admin.put("/api/endpoints/desk/settings", json={"values": {pid: {"askBot.botId": {"value": "bot-99"}, "askBot.nope": {"value": "x"}}, "ghost": {"a.b": {"value": 1}}}})
    assert r.json()["values"] == {pid: {"askBot.botId": {"value": "bot-99"}}}
    eff = r.json()["effective_values"]
    assert eff == [{"backend": pid, "backend_name": "Bot", "tool": "askBot", "alias": "", "tools_taking": 1, "param": "botId", "kind": "value", "value": "bot-99", "enabled": True,
                    "inherited": True, "backend_value": "bot-77", "backend_kind": "default", "backend_enabled": True, "changed": True}]
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        ask = {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema
        assert "botId" not in ask["properties"], "fixed on this gateway"
        await c.call_tool("bot_askBot", {"query": "g", "botId": "bot-78"}); assert CALLS[-1][1]["botId"] == "bot-99"
    # Switched off on the gateway only: the model sees botId again with no default, and its value is sent as given.
    await admin.put("/api/endpoints/desk/settings", json={"values": {pid: {"askBot.botId": {"enabled": False}}}})
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        ask = {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema
        assert "botId" in ask["properties"] and "default" not in ask["properties"]["botId"]
        await c.call_tool("bot_askBot", {"query": "g", "botId": "bot-78"}); assert CALLS[-1][1]["botId"] == "bot-78"
    # One value for every tool that takes the parameter (an API token header, say); a row for one tool wins.
    r = await admin.put("/api/endpoints/desk/settings", json={"values": {pid: {"*.botId": {"value": "B-ALL"}, "*.query": {"value": "Q-ALL"}, "askBot.botId": {"value": "B-ONE"}, "*.nothing": {"value": "x"}}}})
    assert set(r.json()["values"][pid]) == {"*.botId", "*.query", "askBot.botId"}
    every = next(v for v in r.json()["effective_values"] if v["tool"] == "*" and v["param"] == "query")
    assert every["tools_taking"] == 1
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        ask = {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema
        assert "query" not in ask["properties"] and "botId" not in ask["properties"]
        await c.call_tool("bot_askBot", {}); assert CALLS[-1][1]["botId"] == "B-ONE" and CALLS[-1][1]["query"] == "Q-ALL"
    # Back to inheriting: the backend's default is in force again.
    await admin.put("/api/endpoints/desk/settings", json={"values": {}})
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        assert {t.name: t for t in await c.list_tools()}["bot_askBot"].input_schema["properties"]["botId"]["default"] == "bot-77"


async def test_backend_workflows_are_inherited_and_optional(admin, served):
    pid = await setup(admin)
    await admin.patch(f"/api/registry/{pid}", json={"param_sources": {"corpNo": {"kind": "caller", "value": "company"}}})
    await admin.put(f"/api/registry/{pid}/tools/listBots", json={"alias": "findBots"})
    flows = [
        {"name": "askFirstBot", "description": "Ask the first bot.", "inputs": {"question": {}},
         "steps": [{"tool": "findBots", "args": {}}, {"tool": "askBot", "args": {"botId": "{{steps.0.data.0.id}}", "query": "{{input.question}}"}}], "output": "steps.1.data"},
        {"name": "askSecondBot", "description": "Ask the second bot.", "inputs": {"question": {}},
         "steps": [{"tool": "listBots", "args": {}}, {"tool": "askBot", "args": {"botId": "{{steps.0.data.1.id}}", "query": "{{input.question}}"}}], "output": "steps.1.data.answer"},
    ]
    r = await admin.patch(f"/api/registry/{pid}", json={"workflows": flows})
    assert r.status_code == 200 and [w["name"] for w in r.json()["workflows"]] == ["askFirstBot", "askSecondBot"], r.text
    assert r.json()["workflows"][0]["steps"][0]["tool"] == "listBots", "an alias in a step maps to the stored tool"
    assert (await admin.patch(f"/api/registry/{pid}", json={"workflows": [{"name": "x", "steps": [{"tool": "elsewhere", "args": {}}]}]})).status_code == 400
    assert (await admin.patch(f"/api/registry/{pid}", json={"workflows": flows})).status_code == 200

    tok = (await admin.post("/api/tokens", json={"label": "m", "user_id": "emp001"})).json()["token"]
    # Named gateway and shared endpoint: both workflows appear, steps prefixed, and the model is told they are optional.
    for ep in ("/mcp/desk", "/mcp"):
        async with Client(StreamableHttpTransport(f"{served}{ep}", auth=tok)) as c:
            names = {t.name for t in await c.list_tools()}
            assert {"askFirstBot", "askSecondBot"} <= names and "bot_askBot" in names, "shortcuts sit next to the tools, never instead of them"
            assert "Optional shortcuts" in c.instructions and "pick the individual tools yourself" in c.instructions
            assert (await c.call_tool("askSecondBot", {"question": "hr?"})).structured_content == {"result": "echo: hr?"}
            assert CALLS[-1][1]["botId"] == "bot-78"
    inherited = (await admin.get("/api/endpoints/desk/settings")).json()["inherited_workflows"]
    assert [w["backend"] for w in inherited] == [pid, pid] and inherited[0]["steps"][0]["tool"] == "bot_listBots"
    # The gateway's own workflow with the same name wins; a different name adds a third.
    await admin.put("/api/endpoints/desk/settings", json={"workflows": [{"name": "askFirstBot", "description": "gateway's own", "inputs": {"question": {}},
                                                                          "steps": [{"tool": "bot_listBots", "args": {}}], "output": "steps.0.data.0.name"}]})
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert tools["askFirstBot"].description == "gateway's own" and "askSecondBot" in tools
        assert (await c.call_tool("askFirstBot", {"question": "q"})).structured_content == {"result": "Travel QA"}
    # Deployed alone: plain tool names inside the steps still resolve.
    assert (await admin.post(f"/api/registry/{pid}/deploy")).status_code == 200
    async with Client(StreamableHttpTransport(f"{served}/mcp/{pid}", auth=tok)) as c:
        assert (await c.call_tool("askSecondBot", {"question": "solo"})).structured_content == {"result": "echo: solo"}


async def test_workflow_runs_steps_in_order_under_governance(admin, served):
    pid = await setup(admin)
    await admin.patch(f"/api/registry/{pid}", json={"param_sources": {"corpNo": {"kind": "caller", "value": "company"}}})
    wf = {"name": "askCompanyBot", "description": "Ask the company's first chatbot a question.",
          "inputs": {"question": {"description": "What to ask"}},
          "steps": [{"tool": "bot_listBots", "args": {}},
                    {"tool": "bot_askBot", "args": {"botId": "{{steps.0.data.0.id}}", "query": "{{input.question}}"}}],
          "output": "steps.1.data"}
    r = await admin.put("/api/endpoints/desk/settings", json={"workflows": [wf]})
    assert r.status_code == 200 and r.json()["workflows"][0]["name"] == "askCompanyBot", r.text
    assert (await admin.put("/api/endpoints/desk/settings", json={"workflows": [{"name": "bad name", "steps": []}]})).status_code == 400
    assert (await admin.put("/api/endpoints/desk/settings", json={"workflows": [wf, wf]})).status_code == 400

    tok = (await admin.post("/api/tokens", json={"label": "m", "user_id": "emp001"})).json()["token"]
    CALLS.clear()
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        tools = {t.name: t for t in await c.list_tools()}
        assert tools["askCompanyBot"].input_schema["required"] == ["question"] and "askCompanyBot" in c.instructions
        out = (await c.call_tool("askCompanyBot", {"question": "per diem?"})).structured_content
        assert out == {"answer": "echo: per diem?", "sessionId": "sess-1", "channel": None, "pageSize": None}
        assert [n for n, _ in CALLS] == ["bots", "chat"] and CALLS[0][1]["corpNo"] == "1078836129" and CALLS[1][1]["botId"] == "bot-77"
        with pytest.raises(ToolError, match="needs: question"):
            await c.call_tool("askCompanyBot", {})
    # A step the caller may not run stops the workflow with the reason.
    await admin.put(f"/api/registry/{pid}/tools/askBot", json={"enabled": False})
    async with Client(StreamableHttpTransport(f"{served}/mcp/desk", auth=tok)) as c:
        with pytest.raises(ToolError, match="step 2 .*disabled"):
            await c.call_tool("askCompanyBot", {"question": "x"})
    # The workflow belongs to that gateway only.
    async with Client(StreamableHttpTransport(f"{served}/mcp", auth=tok)) as c:
        assert "askCompanyBot" not in {t.name for t in await c.list_tools()}
