"""Registry gateway: open upstream API, portal policy, company scoping, audit."""

import json

import httpx
import httpx2
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from bizplay_mcp import policy_store
from bizplay_mcp.registry_gateway import build_registry_gateway
from portal.app import app as portal_app

# --- a tiny OPEN upstream API (no auth at all), shaped like the real corp endpoint ---
CORPS = [
    {"corpId": 7, "corpNo": "1078836129", "corpName": "DemoCorp01", "corpGroupCode": "DEMOGROUP"},
    {"corpId": 8, "corpNo": "2200000000", "corpName": "OtherCorp", "corpGroupCode": "DEMOGROUP"},
]


async def all_corps(request):
    return JSONResponse({"message": "Get all corp", "status": "OK", "code": 200, "payload": CORPS})


async def one_corp(request):
    corp = next((c for c in CORPS if c["corpNo"] == request.path_params["corpNo"]), None)
    return JSONResponse({"payload": corp}, status_code=200 if corp else 404)


async def delete_corp(request):
    return JSONResponse({"deleted": request.path_params["corpNo"]})


open_api = Starlette(routes=[
    Route("/api/v1/corp", all_corps),
    Route("/api/v1/corp/{corpNo}", one_corp),
    Route("/api/v1/corp/{corpNo}", delete_corp, methods=["DELETE"]),
])

SPEC = {
    "openapi": "3.0.3", "info": {"title": "Open Corp API", "version": "1"},
    "paths": {
        "/api/v1/corp": {"get": {"operationId": "getAllCorps", "summary": "List corps",
                                 "responses": {"200": {"description": "ok"}}}},
        "/api/v1/corp/{corpNo}": {
            "get": {"operationId": "getCorpByCorpNo", "summary": "One corp",
                    "parameters": [{"name": "corpNo", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "ok"}}},
            "delete": {"operationId": "deleteCorpByCorpNo", "summary": "Delete corp",
                       "parameters": [{"name": "corpNo", "in": "path", "required": True, "schema": {"type": "string"}}],
                       "responses": {"200": {"description": "ok"}}},
        },
    },
}


@pytest.fixture
async def admin():
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        r = await c.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


@pytest.fixture
async def open_provider(admin):
    r = await admin.post("/api/registry", json={"name": "Open Corp API", "base_url": "http://open.test",
                                                "spec": SPEC, "auth_mode": "open"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert (await admin.post(f"/api/registry/{pid}/publish")).status_code == 200, "open mode may publish"
    return pid


def gateway():
    return build_registry_gateway(lambda provider: httpx2.ASGITransport(app=open_api))


@pytest.fixture
def as_company(monkeypatch):
    def _set(company: str, role: str = "employee") -> None:
        monkeypatch.setenv("BIZPLAY_COMPANY", company)
        monkeypatch.setenv("BIZPLAY_ROLE", role)
    return _set


async def test_open_mode_registration_and_checklist(admin, open_provider):
    reg = (await admin.get("/api/registry")).json()["items"]
    p = next(x for x in reg if x["id"] == open_provider)
    assert p["auth_mode"] == "open" and p["status"] == "published" and p["has_spec"] and "spec" not in p
    item = next(c for c in (await admin.get("/api/overview")).json()["checklist"] if c["id"] == "no_open_providers")
    assert item["ok"] is False and "Open Corp API" in item["detail"]


async def test_bearer_mode_still_blocks_publish_without_token(admin):
    pid = (await admin.post("/api/registry", json={"name": "Strict API", "base_url": "http://s.test",
                                                   "spec": SPEC, "auth_mode": "bearer"})).json()["id"]
    assert (await admin.post(f"/api/registry/{pid}/publish")).status_code == 409


async def test_tools_are_namespaced_by_provider(open_provider, as_company):
    as_company("1078836129")
    async with Client(gateway()) as c:
        names = {t.name for t in await c.list_tools()}
    assert {"open_corp_api_getAllCorps", "open_corp_api_getCorpByCorpNo", "open_corp_api_deleteCorpByCorpNo"} <= names


async def test_results_are_scoped_to_callers_company(open_provider, as_company, wiring):
    as_company("1078836129")
    async with Client(gateway()) as c:
        result = await c.call_tool("open_corp_api_getAllCorps", {})
    corps = result.structured_content["payload"]
    assert [x["corpName"] for x in corps] == ["DemoCorp01"], "the other company's record must be removed"
    last = json.loads(wiring.read_text(encoding="utf-8").splitlines()[-1])
    assert last["outcome"] == "ok" and "1 record(s) outside company" in last["detail"]


async def test_without_a_company_scoping_is_skipped_not_refused(open_provider, monkeypatch):
    """Token-free demo mode: no identity means no scoping, and tools still work."""
    monkeypatch.delenv("BIZPLAY_COMPANY", raising=False)
    monkeypatch.setenv("BIZPLAY_ROLE", "employee")
    async with Client(gateway()) as c:
        one = await c.call_tool("open_corp_api_getCorpByCorpNo", {"corpNo": "2200000000"})
        assert one.structured_content["payload"]["corpName"] == "OtherCorp"
        every = await c.call_tool("open_corp_api_getAllCorps", {})
        assert len(every.structured_content["payload"]) == 2, "nothing is filtered out"


async def test_cannot_name_another_company_in_arguments(open_provider, as_company):
    as_company("1078836129")
    async with Client(gateway()) as c:
        with pytest.raises(ToolError, match="not the caller's company"):
            await c.call_tool("open_corp_api_getCorpByCorpNo", {"corpNo": "2200000000"})
        with pytest.raises(ToolError, match="not the caller's company"):
            await c.call_tool("open_corp_api_deleteCorpByCorpNo", {"corpNo": "2200000000"})
        own = await c.call_tool("open_corp_api_getCorpByCorpNo", {"corpNo": "1078836129"})
        assert own.structured_content["payload"]["corpName"] == "DemoCorp01"


async def test_disabled_tool_is_hidden_and_refused(admin, open_provider, as_company):
    as_company("1078836129")
    await admin.put(f"/api/registry/{open_provider}/tools/deleteCorpByCorpNo", json={"enabled": False})
    async with Client(gateway()) as c:
        assert "open_corp_api_deleteCorpByCorpNo" not in {t.name for t in await c.list_tools()}
        with pytest.raises(ToolError, match="disabled by the provider admin"):
            await c.call_tool("open_corp_api_deleteCorpByCorpNo", {"corpNo": "1078836129"})


async def test_role_policy_applies(admin, open_provider, as_company):
    as_company("1078836129", role="employee")
    await admin.put(f"/api/registry/{open_provider}/tools/getAllCorps", json={"roles": ["manager"]})
    async with Client(gateway()) as c:
        with pytest.raises(ToolError, match="role 'employee' is not allowed"):
            await c.call_tool("open_corp_api_getAllCorps", {})


async def test_unpublished_provider_is_not_served(admin, open_provider, as_company):
    as_company("1078836129")
    await admin.post(f"/api/registry/{open_provider}/unpublish")
    async with Client(gateway()) as c:
        assert not [t for t in await c.list_tools() if t.name.startswith("open_corp_api_")]
