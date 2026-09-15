"""COOCON mock: a second REST backend registered from its own spec and driven end to end through the gateway."""

import httpx
import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError

from bizplay_mcp.registry_gateway import build_registry_gateway
from coocon_mock.app import OPENAPI, app as coocon
from portal.app import app as portal_app


@pytest.fixture
async def admin(monkeypatch):
    monkeypatch.setenv("BIZPLAY_REQUIRE_AGENT_TOKEN", "false")
    async with httpx.AsyncClient(base_url="http://portal.test", transport=httpx.ASGITransport(app=portal_app)) as c:
        r = await c.post("/api/login", json={"email": "admin@bizplay.co.kr", "password": "admin1234"})
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


async def test_mock_serves_project_based_scraping(monkeypatch):
    monkeypatch.delenv("COOCON_API_TOKEN", raising=False)
    async with httpx.AsyncClient(base_url="http://coocon.test", transport=httpx.ASGITransport(app=coocon)) as c:
        assert (await c.get("/openapi.json")).json()["info"]["title"].startswith("COOCON")
        projects = (await c.get("/api/v1/projects", params={"corpNo": "1078836129"})).json()["items"]
        assert {p["projectId"] for p in projects} == {"prj-1001", "prj-1002"}, "scoped by company"
        assert (await c.post("/api/v1/projects/prj-1002/jobs", json={"source": "bank"})).status_code == 409, "source not enabled for the project"
        job = (await c.post("/api/v1/projects/prj-1001/jobs", json={"source": "hometax", "dateFrom": "2026-09-01", "dateTo": "2026-09-10"})).json()
        assert job["status"] == "completed" and job["recordCount"] > 0
        rows = (await c.get(f"/api/v1/jobs/{job['jobId']}/records")).json()["items"]
        assert all(r["corpNo"] == "1078836129" and "supplyAmount" in r for r in rows)
        again = (await c.post("/api/v1/projects/prj-1001/jobs", json={"source": "hometax", "dateFrom": "2026-09-01", "dateTo": "2026-09-10"})).json()
        assert again["recordCount"] == job["recordCount"], "deterministic for the same request"

    monkeypatch.setenv("COOCON_API_TOKEN", "s3cret")
    async with httpx.AsyncClient(base_url="http://coocon.test", transport=httpx.ASGITransport(app=coocon)) as c:
        assert (await c.get("/api/v1/sources")).status_code == 401
        assert (await c.get("/api/v1/sources", headers={"Authorization": "Bearer s3cret"})).status_code == 200
        assert (await c.get("/openapi.json")).status_code == 200, "the spec stays open so the portal can fetch it"


async def test_coocon_through_the_gateway(admin, monkeypatch):
    monkeypatch.delenv("COOCON_API_TOKEN", raising=False)
    r = await admin.post("/api/registry", json={"name": "COOCON", "kind": "openapi", "base_url": "http://coocon.test", "spec": OPENAPI, "auth_mode": "open"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert (await admin.post(f"/api/registry/{pid}/publish")).status_code == 200
    tools = {t["name"]: t for t in (await admin.get(f"/api/registry/{pid}/tools")).json()["items"]}
    assert tools["listProjects"]["kind"] == "read" and tools["listProjects"]["enabled"]
    assert tools["startJob"]["kind"] == "write" and not tools["startJob"]["enabled"], "writes start disabled"

    gw = build_registry_gateway(transport_factory=lambda p: httpx2.ASGITransport(app=coocon))
    async with Client(FastMCPTransport(gw)) as m:
        names = {t.name for t in await m.list_tools() if t.name.startswith(f"{pid}_")}
        assert names == {f"{pid}_{n}" for n in ("listSources", "listProjects", "getProject", "getProjectSummary", "listJobs", "getJob", "getJobRecords")}
        got = (await m.call_tool(f"{pid}_listProjects", {"corpNo": "1078836129"})).structured_content
        assert [p["projectId"] for p in got["items"]] == ["prj-1001", "prj-1002"]
        with pytest.raises(ToolError, match="disabled"):
            await m.call_tool(f"{pid}_startJob", {"projectId": "prj-1001", "source": "card"})

    assert (await admin.put(f"/api/registry/{pid}/tools/startJob", json={"enabled": True, "roles": ["employee", "manager"]})).status_code == 200
    async with Client(FastMCPTransport(gw)) as m:
        job = (await m.call_tool(f"{pid}_startJob", {"projectId": "prj-1001", "source": "card", "dateFrom": "2026-09-01", "dateTo": "2026-09-07"})).structured_content
        rows = (await m.call_tool(f"{pid}_getJobRecords", {"jobId": job["jobId"], "limit": 3})).structured_content
        assert rows["count"] == job["recordCount"] and len(rows["items"]) == 3 and all("merchant" in r for r in rows["items"])
