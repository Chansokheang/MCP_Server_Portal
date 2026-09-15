"""COOCON mock: project-based scraping of financial data (bank, card, Hometax, insurance).

Shaped like a data-aggregation provider: a customer company owns *projects*,
each project scrapes one or more *sources* through *jobs*, and a finished job
yields *records* (transactions, invoices, filings). Everything is in memory
and deterministic, so the same request always returns the same data.

The OpenAPI spec is hand-written with real summaries and descriptions: it is
what the gateway turns into tools, and what the model reads to choose one.

Run:
    uv run coocon-mock --port 18096          # http://127.0.0.1:18096/openapi.json

Set COOCON_API_TOKEN to require `Authorization: Bearer <token>` on /api/*,
to exercise the gateway's bearer mode; unset, the API is open.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
from datetime import date, datetime, timedelta, timezone

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

SOURCES = {
    "bank": {"id": "bank", "name": "Bank accounts", "nameKo": "은행 계좌", "records": "deposits and withdrawals", "institutions": ["KB Kookmin", "Shinhan", "Woori", "Hana"]},
    "card": {"id": "card", "name": "Corporate cards", "nameKo": "법인카드", "records": "card approvals and cancellations", "institutions": ["Samsung Card", "Shinhan Card", "Hyundai Card"]},
    "hometax": {"id": "hometax", "name": "Hometax (National Tax Service)", "nameKo": "홈택스", "records": "electronic tax invoices issued and received", "institutions": ["NTS"]},
    "insurance": {"id": "insurance", "name": "4 major insurances", "nameKo": "4대보험", "records": "monthly premium notices", "institutions": ["NHIS", "NPS", "EI", "WCI"]},
}

PROJECTS: dict[str, dict] = {
    "prj-1001": {"projectId": "prj-1001", "name": "DemoCorp01 monthly close", "corpNo": "1078836129", "sources": ["bank", "card", "hometax"],
                 "status": "active", "createdAt": "2026-08-01T09:00:00+09:00", "owner": "finance@democorp01.co.kr"},
    "prj-1002": {"projectId": "prj-1002", "name": "DemoCorp01 payroll insurance", "corpNo": "1078836129", "sources": ["insurance"],
                 "status": "active", "createdAt": "2026-08-15T09:00:00+09:00", "owner": "hr@democorp01.co.kr"},
    "prj-2001": {"projectId": "prj-2001", "name": "OtherCorp card audit", "corpNo": "2200000000", "sources": ["card"],
                 "status": "paused", "createdAt": "2026-07-20T09:00:00+09:00", "owner": "audit@othercorp.co.kr"},
}
JOBS: dict[str, dict] = {}
_seq = {"project": 1002, "job": 0}

MERCHANTS = ["Hanil Kitchen", "Seoul BBQ", "Korail KTX", "CloudDocs SaaS", "Corner Stationery", "Seoul Taxi", "Gangnam Hotel", "Coupang Biz"]
COUNTERPARTIES = ["Pacific Trading Co.", "Hanguk Logistics", "Blue Ocean Design", "Daehan Consulting", "Mirae Parts"]


def _seed_job(project: dict, source: str, date_from: str, date_to: str) -> dict:
    _seq["job"] += 1
    job_id = f"job-{_seq['job']:04d}"
    rng = random.Random(f"{project['projectId']}:{source}:{date_from}:{date_to}")
    d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    days = max(1, (d1 - d0).days + 1)
    records = []
    for i in range(rng.randint(6, 14)):
        day = d0 + timedelta(days=rng.randrange(days))
        base = {"recordId": f"{job_id}-r{i + 1:02d}", "corpNo": project["corpNo"], "source": source, "date": day.isoformat()}
        if source == "bank":
            amt = rng.choice([-1, 1]) * rng.randrange(50_000, 9_000_000, 10_000)
            base.update({"institution": rng.choice(SOURCES["bank"]["institutions"]), "account": f"***-{rng.randrange(1000, 9999)}", "counterparty": rng.choice(COUNTERPARTIES),
                         "amount": amt, "kind": "withdrawal" if amt < 0 else "deposit", "currency": "KRW"})
        elif source == "card":
            base.update({"institution": rng.choice(SOURCES["card"]["institutions"]), "card": f"****-{rng.randrange(1000, 9999)}", "merchant": rng.choice(MERCHANTS),
                         "amount": rng.randrange(8_000, 480_000, 100), "approved": rng.random() > 0.08, "currency": "KRW"})
        elif source == "hometax":
            supply = rng.randrange(300_000, 25_000_000, 10_000)
            base.update({"direction": rng.choice(["issued", "received"]), "counterparty": rng.choice(COUNTERPARTIES), "supplyAmount": supply, "vat": supply // 10,
                         "invoiceNo": f"2026{rng.randrange(10**8, 10**9)}", "currency": "KRW"})
        else:
            base.update({"institution": rng.choice(SOURCES["insurance"]["institutions"]), "month": day.strftime("%Y-%m"), "employees": rng.randrange(8, 60),
                         "premium": rng.randrange(1_200_000, 18_000_000, 10_000), "currency": "KRW"})
        records.append(base)
    records.sort(key=lambda r: r["date"])
    job = {"jobId": job_id, "projectId": project["projectId"], "corpNo": project["corpNo"], "source": source, "dateFrom": date_from, "dateTo": date_to,
           "status": "completed", "requestedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "recordCount": len(records), "_records": records}
    JOBS[job_id] = job
    return job


def _public_job(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class OptionalBearer(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = os.environ.get("COOCON_API_TOKEN")
        if token and request.url.path.startswith("/api/"):
            scheme, _, presented = request.headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or presented.strip() != token:
                return JSONResponse({"error": "bearer token required"}, status_code=401, headers={"WWW-Authenticate": 'Bearer realm="coocon"'})
        return await call_next(request)


# --- handlers ---------------------------------------------------------------------------
async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "coocon-mock"})


async def list_sources(request: Request):
    return JSONResponse({"items": list(SOURCES.values())})


async def list_projects(request: Request):
    corp = request.query_params.get("corpNo")
    status = request.query_params.get("status")
    items = [p for p in PROJECTS.values() if (not corp or p["corpNo"] == corp) and (not status or p["status"] == status)]
    return JSONResponse({"items": items, "count": len(items)})


async def create_project(request: Request):
    body = await request.json()
    name, corp = (body.get("name") or "").strip(), str(body.get("corpNo") or "").strip()
    sources = [s for s in body.get("sources") or [] if s in SOURCES]
    if not name or not corp or not sources:
        return _error(400, "name, corpNo and at least one valid source are required")
    _seq["project"] += 1
    pid = f"prj-{_seq['project']}"
    PROJECTS[pid] = {"projectId": pid, "name": name, "corpNo": corp, "sources": sources, "status": "active",
                     "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "owner": body.get("owner") or "api"}
    return JSONResponse(PROJECTS[pid], status_code=201)


async def get_project(request: Request):
    p = PROJECTS.get(request.path_params["projectId"])
    return JSONResponse(p) if p else _error(404, "unknown project")


async def start_job(request: Request):
    p = PROJECTS.get(request.path_params["projectId"])
    if not p:
        return _error(404, "unknown project")
    body = await request.json()
    source = body.get("source")
    if source not in SOURCES:
        return _error(400, f"source must be one of {', '.join(SOURCES)}")
    if source not in p["sources"]:
        return _error(409, f"project {p['projectId']} is not set up for source '{source}'")
    try:
        date_from, date_to = body.get("dateFrom") or "2026-09-01", body.get("dateTo") or "2026-09-30"
        date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError:
        return _error(400, "dateFrom and dateTo must be YYYY-MM-DD")
    return JSONResponse(_public_job(_seed_job(p, source, date_from, date_to)), status_code=201)


async def list_jobs(request: Request):
    pid = request.path_params["projectId"]
    if pid not in PROJECTS:
        return _error(404, "unknown project")
    items = [_public_job(j) for j in JOBS.values() if j["projectId"] == pid]
    return JSONResponse({"items": items, "count": len(items)})


async def get_job(request: Request):
    j = JOBS.get(request.path_params["jobId"])
    return JSONResponse(_public_job(j)) if j else _error(404, "unknown job")


async def job_records(request: Request):
    j = JOBS.get(request.path_params["jobId"])
    if not j:
        return _error(404, "unknown job")
    limit = max(1, min(200, int(request.query_params.get("limit", "50"))))
    return JSONResponse({"jobId": j["jobId"], "corpNo": j["corpNo"], "source": j["source"], "items": j["_records"][:limit], "count": len(j["_records"])})


async def project_summary(request: Request):
    p = PROJECTS.get(request.path_params["projectId"])
    if not p:
        return _error(404, "unknown project")
    per_source = {}
    for j in JOBS.values():
        if j["projectId"] != p["projectId"]:
            continue
        s = per_source.setdefault(j["source"], {"source": j["source"], "jobs": 0, "records": 0, "totalAmount": 0})
        s["jobs"] += 1
        s["records"] += j["recordCount"]
        s["totalAmount"] += sum(r.get("amount") or r.get("supplyAmount") or r.get("premium") or 0 for r in j["_records"])
    return JSONResponse({"projectId": p["projectId"], "corpNo": p["corpNo"], "name": p["name"], "sources": list(per_source.values()),
                         "lastJobAt": max((j["requestedAt"] for j in JOBS.values() if j["projectId"] == p["projectId"]), default=None)})


# --- OpenAPI ------------------------------------------------------------------------------
def _param(name, where, desc, required=False, schema=None, example=None):
    p = {"name": name, "in": where, "description": desc, "required": required, "schema": schema or {"type": "string"}}
    if example is not None:
        p["example"] = example
    return p


OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "COOCON Scraping API (mock)", "version": "1.0.0",
             "description": "Project-based scraping of a company's financial data. A project belongs to one company (corpNo) and lists the sources it may scrape; a job scrapes one source for a date range and yields records."},
    "paths": {
        "/api/v1/sources": {"get": {"operationId": "listSources", "summary": "List the data sources that can be scraped",
                                    "description": "The catalogue of sources (bank accounts, corporate cards, Hometax tax invoices, the four major insurances) with the kind of records each one yields. Use it to explain what a project can collect.",
                                    "responses": {"200": {"description": "ok"}}}},
        "/api/v1/projects": {
            "get": {"operationId": "listProjects", "summary": "List scraping projects, optionally for one company or status",
                    "description": "Every project this API knows. Filter by corpNo to see one company's projects, or by status (active, paused). Start here to find a projectId.",
                    "parameters": [_param("corpNo", "query", "Company number to filter by", example="1078836129"),
                                   _param("status", "query", "active or paused", schema={"type": "string", "enum": ["active", "paused"]})],
                    "responses": {"200": {"description": "ok"}}},
            "post": {"operationId": "createProject", "summary": "Create a scraping project for a company",
                     "description": "Sets up a project that may scrape the listed sources for one company. Returns the new projectId.",
                     "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["name", "corpNo", "sources"], "properties": {
                         "name": {"type": "string", "description": "Project name, e.g. 'DemoCorp01 monthly close'"},
                         "corpNo": {"type": "string", "description": "Company number that owns the project"},
                         "sources": {"type": "array", "items": {"type": "string", "enum": list(SOURCES)}, "description": "Sources the project may scrape"},
                         "owner": {"type": "string", "description": "Contact email"}}}}}},
                     "responses": {"201": {"description": "created"}}},
        },
        "/api/v1/projects/{projectId}": {"get": {"operationId": "getProject", "summary": "Get one project by id",
                                                 "parameters": [_param("projectId", "path", "Project id from listProjects", True, example="prj-1001")],
                                                 "responses": {"200": {"description": "ok"}, "404": {"description": "unknown project"}}}},
        "/api/v1/projects/{projectId}/summary": {"get": {"operationId": "getProjectSummary", "summary": "Totals per source for a project",
                                                         "description": "Jobs run, records collected and total amount per source, plus when the last job ran. Good first answer to 'how is project X doing'.",
                                                         "parameters": [_param("projectId", "path", "Project id", True, example="prj-1001")],
                                                         "responses": {"200": {"description": "ok"}}}},
        "/api/v1/projects/{projectId}/jobs": {
            "get": {"operationId": "listJobs", "summary": "List scraping jobs of a project",
                    "parameters": [_param("projectId", "path", "Project id", True, example="prj-1001")],
                    "responses": {"200": {"description": "ok"}}},
            "post": {"operationId": "startJob", "summary": "Start a scraping job for one source and date range",
                     "description": "Scrapes the given source for the project's company between dateFrom and dateTo (YYYY-MM-DD). The mock completes immediately; read the records with getJobRecords. The source must be one the project is set up for.",
                     "parameters": [_param("projectId", "path", "Project id", True, example="prj-1001")],
                     "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["source"], "properties": {
                         "source": {"type": "string", "enum": list(SOURCES), "description": "Which source to scrape"},
                         "dateFrom": {"type": "string", "format": "date", "description": "First day, YYYY-MM-DD (default 2026-09-01)"},
                         "dateTo": {"type": "string", "format": "date", "description": "Last day, YYYY-MM-DD (default 2026-09-30)"}}}}}},
                     "responses": {"201": {"description": "job created"}, "409": {"description": "source not enabled for this project"}}},
        },
        "/api/v1/jobs/{jobId}": {"get": {"operationId": "getJob", "summary": "Status of one scraping job",
                                         "parameters": [_param("jobId", "path", "Job id from startJob or listJobs", True, example="job-0001")],
                                         "responses": {"200": {"description": "ok"}}}},
        "/api/v1/jobs/{jobId}/records": {"get": {"operationId": "getJobRecords", "summary": "Records a job scraped (transactions, invoices, premiums)",
                                                 "description": "The rows collected by a finished job. Bank rows carry amount (negative = withdrawal) and counterparty; card rows carry merchant and approved; Hometax rows carry supplyAmount, vat and direction; insurance rows carry premium and employees. Every row carries corpNo.",
                                                 "parameters": [_param("jobId", "path", "Job id", True, example="job-0001"),
                                                                _param("limit", "query", "Max rows, up to 200", schema={"type": "integer", "default": 50})],
                                                 "responses": {"200": {"description": "ok"}}}},
    },
}


async def openapi(request: Request):
    return JSONResponse(OPENAPI)


app = Starlette(routes=[
    Route("/health", health),
    Route("/openapi.json", openapi),
    Route("/api/v1/sources", list_sources),
    Route("/api/v1/projects", list_projects),
    Route("/api/v1/projects", create_project, methods=["POST"]),
    Route("/api/v1/projects/{projectId}", get_project),
    Route("/api/v1/projects/{projectId}/summary", project_summary),
    Route("/api/v1/projects/{projectId}/jobs", list_jobs),
    Route("/api/v1/projects/{projectId}/jobs", start_job, methods=["POST"]),
    Route("/api/v1/jobs/{jobId}", get_job),
    Route("/api/v1/jobs/{jobId}/records", job_records),
], middleware=[Middleware(OptionalBearer)])

# A couple of finished jobs so the demo has data before anyone starts one.
for _pid, _src in (("prj-1001", "bank"), ("prj-1001", "card"), ("prj-2001", "card")):
    _seed_job(PROJECTS[_pid], _src, "2026-09-01", "2026-09-14")


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="COOCON mock scraping API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18096)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
