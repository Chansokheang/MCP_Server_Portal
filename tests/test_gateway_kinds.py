"""Both backend kinds behind one gateway, and one provider deployed on its own endpoint."""

import asyncio
import json

import httpx
import httpx2
import pytest
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.providers.proxy import ProxyClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from bizplay_mcp import policy_store, specs
from bizplay_mcp.registry_gateway import build_registry_gateway
from portal import app as portal_module
from portal.app import app as portal_app, create_app

# --- an MCP server that already exists (kind "mcp") ---------------------------------
backend = FastMCP("Task Backend")


@backend.tool(annotations={"readOnlyHint": True})
def list_tasks() -> list[dict]:
    return [{"id": 1, "corpNo": "1078836129", "title": "Close the books"},
            {"id": 2, "corpNo": "2200000000", "title": "Someone else's task"}]


@backend.tool
def create_task(title: str) -> dict:
    return {"id": 3, "title": title}


# --- an open REST API with an OpenAPI spec (kind "openapi") -------------------------
CORPS = [{"corpNo": "1078836129", "corpName": "DemoCorp01"}, {"corpNo": "2200000000", "corpName": "OtherCorp"}]

open_api = Starlette(routes=[
    Route("/api/v1/corp", lambda r: JSONResponse({"payload": CORPS})),
    Route("/api/v1/templates/{template_id}/download", lambda r: JSONResponse({"url": f"/files/{r.path_params['template_id']}"})),
])

SPEC = {
    "openapi": "3.0.3", "info": {"title": "Corp API", "version": "1"},
    "paths": {
        "/api/v1/corp": {"get": {"operationId": "getAllCorps", "summary": "List corps",
                                 "responses": {"200": {"description": "ok"}}}},
        # FastAPI-style operationId: FastMCP cuts it at the first "__".
        "/api/v1/templates/{template_id}/download": {
            "get": {"operationId": "download_url_api_v1_templates__template_id__download_get", "summary": "Download URL",
                    "parameters": [{"name": "template_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "ok"}}}},
    },
}


@pytest.fixture
async def admin(monkeypatch):
    # The portal lists an MCP server's tools at registration; point it at the in-memory backend.
    monkeypatch.setattr(portal_module, "mcp_client", lambda url, headers: Client(backend))
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        r = await c.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


@pytest.fixture
async def tasks(admin):
    r = await admin.post("/api/registry", json={"name": "Tasks", "kind": "mcp", "base_url": "http://tasks.test/mcp",
                                                "auth_mode": "open"})
    assert r.status_code == 201, r.text
    assert (await admin.post(f"/api/registry/{r.json()['id']}/publish")).status_code == 200
    return r.json()["id"]


@pytest.fixture
async def corp(admin):
    r = await admin.post("/api/registry", json={"name": "Corp API", "base_url": "http://open.test",
                                                "spec": SPEC, "auth_mode": "open"})
    assert r.status_code == 201, r.text
    assert (await admin.post(f"/api/registry/{r.json()['id']}/publish")).status_code == 200
    return r.json()["id"]


@pytest.fixture
def as_company(monkeypatch):
    def _set(company: str, role: str = "employee") -> None:
        monkeypatch.setenv("BIZPLAY_COMPANY", company)
        monkeypatch.setenv("BIZPLAY_ROLE", role)
    return _set


def gateway():
    return build_registry_gateway(transport_factory=lambda p: httpx2.ASGITransport(app=open_api),
                                  mcp_client_factory=lambda p: ProxyClient(backend))


# --- kind "mcp" -------------------------------------------------------------------------
async def test_registering_an_mcp_server_uses_its_own_tool_list(admin, tasks):
    p = next(x for x in (await admin.get("/api/registry")).json()["items"] if x["id"] == tasks)
    assert p["kind"] == "mcp" and p["tool_count"] == 2 and p["spec_source"] == "MCP server"
    rows = {t["name"]: t for t in (await admin.get(f"/api/registry/{tasks}/tools")).json()["items"]}
    assert rows["list_tasks"]["kind"] == "read" and rows["list_tasks"]["enabled"], "readOnlyHint makes a read tool"
    assert rows["create_task"]["kind"] == "write" and not rows["create_task"]["enabled"], "writes start off"
    test = (await admin.post(f"/api/registry/{tasks}/test")).json()
    assert test["ok"], test


async def test_unreachable_mcp_server_is_a_clear_registration_error(admin, monkeypatch):
    monkeypatch.setattr(portal_module, "mcp_client", lambda url, headers: Client("http://127.0.0.1:9/mcp"))
    r = await admin.post("/api/registry", json={"name": "Dead", "kind": "mcp", "base_url": "http://127.0.0.1:9/mcp",
                                                "auth_mode": "open"})
    assert r.status_code == 502 and "could not list tools" in r.json()["error"]


async def test_proxied_tools_get_the_same_governance(admin, tasks, as_company, wiring):
    as_company("1078836129")
    async with Client(gateway()) as c:
        names = {t.name for t in await c.list_tools()}
        assert "tasks_list_tasks" in names and "tasks_create_task" not in names
        result = await c.call_tool("tasks_list_tasks", {})
        assert [t["title"] for t in result.structured_content["result"]] == ["Close the books"], "scoped to the caller's company"
        with pytest.raises(ToolError, match="disabled"):
            await c.call_tool("tasks_create_task", {"title": "x"})
    await admin.put(f"/api/registry/{tasks}/tools/create_task", json={"enabled": True})
    async with Client(gateway()) as c:
        assert (await c.call_tool("tasks_create_task", {"title": "Ship it"})).structured_content["id"] == 3
    last = json.loads(wiring.read_text(encoding="utf-8").splitlines()[-1])
    assert last["tool"] == "tasks_create_task" and last["outcome"] == "ok"


# --- kind "openapi": stored names must be the ones FastMCP serves -------------------------
async def test_portal_stores_the_names_fastmcp_generates(admin, corp):
    names = {t["name"] for t in (await admin.get(f"/api/registry/{corp}/tools")).json()["items"]}
    assert names == {"getAllCorps", "download_url_api_v1_templates"}
    async with Client(gateway()) as c:
        served = {t.name: t for t in await c.list_tools() if t.name.startswith("corp_api_")}
    assert set(served) == {"corp_api_getAllCorps", "corp_api_download_url_api_v1_templates"}, "every enabled read is visible"
    assert served["corp_api_getAllCorps"].annotations.read_only_hint is True, "reads are announced as read-only"


def test_read_verb_guess_for_unannotated_mcp_tools():
    class T:
        def __init__(self, name): self.name, self.description, self.annotations = name, "", None
    rows = specs.tools_from_mcp([T("bizplay_57a3_getAllCorps"), T("workflow_list_documents_api_v1_documents_get"),
                                 T("download_url_api_v1_templates"), T("create_task")])
    assert [r["kind"] for r in rows.values()] == ["read", "read", "write", "write"]


async def test_old_registrations_with_raw_operation_ids_are_healed(admin, corp, as_company):
    """Rows stored under the raw operationId are renamed on load, policy intact."""
    as_company("1078836129", role="manager")
    state = policy_store.load()
    row = state["providers"][corp]["tools"].pop("download_url_api_v1_templates")
    state["providers"][corp]["tools"]["download_url_api_v1_templates__template_id__download_get"] = {**row, "roles": ["manager"]}
    policy_store.save(state)

    gw = gateway()  # sync() reconciles and writes the corrected table back
    healed = policy_store.load()["providers"][corp]["tools"]
    assert "download_url_api_v1_templates" in healed and healed["download_url_api_v1_templates"]["roles"] == ["manager"]
    assert "download_url_api_v1_templates__template_id__download_get" not in healed
    async with Client(gw) as c:
        r = await c.call_tool("corp_api_download_url_api_v1_templates", {"template_id": "t1"})
    assert r.structured_content["url"] == "/files/t1"


def test_reconcile_is_a_no_op_for_current_tables():
    provider = {"spec": SPEC, "tools": specs.tools_from_spec(SPEC)}
    assert specs.reconcile_tool_names(provider) == []


# --- standalone endpoint: /mcp/<provider> ---------------------------------------------------
@pytest.fixture
async def served():
    """The portal process as deployed: UI, API and gateway on one origin, over real HTTP."""
    config = uvicorn.Config(create_app(gateway()), host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


async def test_deploy_serves_one_provider_with_plain_tool_names(admin, corp, tasks, served):
    assert (await admin.post(f"/api/registry/{corp}/deploy")).json()["standalone"] is True
    p = next(x for x in (await admin.get("/api/registry")).json()["items"] if x["id"] == corp)
    assert p["standalone_url"] == p["mcp_url"].rstrip("/") + f"/{corp}"
    # The gateway requires an agent token by default; the standalone endpoint is no exception.
    token = (await admin.post("/api/tokens", json={"label": "t", "user_id": "emp001", "role": "employee",
                                                   "company": "1078836129"})).json()["token"]

    async with httpx.AsyncClient() as http:
        assert (await http.post(f"{served}/mcp/{corp}", json={})).status_code == 401, "no token, no access"

    async with Client(StreamableHttpTransport(f"{served}/mcp/{corp}", auth=token)) as c:
        names = {t.name for t in await c.list_tools()}
        assert names == {"getAllCorps", "download_url_api_v1_templates"}, "no prefix, and no other provider's tools"
        corps = (await c.call_tool("getAllCorps", {})).structured_content["payload"]
        assert [x["corpName"] for x in corps] == ["DemoCorp01"], "company scoping applies here too"
        with pytest.raises(ToolError, match="not served on the standalone endpoint"):
            await c.call_tool("tasks_list_tasks", {})

    async with Client(StreamableHttpTransport(f"{served}/mcp", auth=token)) as c:
        shared = {t.name for t in await c.list_tools()}
    assert {"corp_api_getAllCorps", "tasks_list_tasks"} <= shared, "the shared endpoint is unchanged"

    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
        assert (await http.get(f"{served}/api/health")).status_code == 200, "the portal still answers on the same origin"
        assert (await http.post(f"{served}/mcp/{tasks}", json={})).status_code == 404, "not deployed"
        assert (await http.post(f"{served}/mcp/nope", json={})).status_code == 404

    await admin.post(f"/api/registry/{corp}/undeploy")
    async with httpx.AsyncClient() as http:
        assert (await http.post(f"{served}/mcp/{corp}", json={})).status_code == 404, "undeploy takes effect at once"


async def test_deploy_publishes_and_needs_a_credential_in_bearer_mode(admin):
    r = await admin.post("/api/registry", json={"name": "Strict", "base_url": "http://s.test", "spec": SPEC, "auth_mode": "bearer"})
    pid = r.json()["id"]
    assert (await admin.post(f"/api/registry/{pid}/deploy")).status_code == 409
    await admin.patch(f"/api/registry/{pid}", json={"service_token": "s3cret"})
    d = (await admin.post(f"/api/registry/{pid}/deploy")).json()
    assert d["standalone"] and d["status"] == "published"
    assert (await admin.post("/api/registry/bizplay/deploy")).status_code == 409, "the curated server is not a registered API"


# --- the portal's own origin is the default endpoint --------------------------------------
async def test_default_endpoint_is_the_portal_origin(admin):
    cfg = (await admin.get("/api/config")).json()
    assert cfg["portal_mcp_url"] == "http://portal.test/mcp" and cfg["default_mcp_url"] == "http://portal.test/mcp"
    r = await admin.post("/api/registry", json={"name": "Plain", "base_url": "http://x.test", "spec": SPEC, "auth_mode": "open"})
    assert r.json()["mcp_url"] == "http://portal.test/mcp"
    behind_proxy = await admin.get("/api/config", headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "mcp-portal.example.com"})
    assert behind_proxy.json()["default_mcp_url"] == "https://mcp-portal.example.com/mcp"
