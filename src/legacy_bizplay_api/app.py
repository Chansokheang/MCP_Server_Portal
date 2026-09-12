"""Mock of the existing Bizplay REST API (plain JSON over HTTP).

It knows nothing about MCP, AI agents, per-user permissions, or Korean
compliance checks. Those live in the MCP gateway.

Every /api/* endpoint requires `Authorization: Bearer <service token>`.
Valid tokens come from BIZPLAY_API_TOKENS (comma-separated); the default
is the demo token "demo-service-token". Only /health is public.

Run it with:

    uv run legacy-bizplay-api          # http://127.0.0.1:18080
"""

from __future__ import annotations

import argparse
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .store import InvalidState, NotFound, store, to_dict


def valid_service_tokens() -> set[str]:
    raw = os.environ.get("BIZPLAY_API_TOKENS", "demo-service-token")
    return {t.strip() for t in raw.split(",") if t.strip()}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject any /api request without a valid bearer token (HTTP 401)."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            header = request.headers.get("authorization", "")
            scheme, _, token = header.partition(" ")
            if scheme.lower() != "bearer" or token.strip() not in valid_service_tokens():
                return JSONResponse(
                    {"error": "missing or invalid bearer token"},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Bearer realm="bizplay-api"'},
                )
        return await call_next(request)


async def health(request: Request):
    return JSONResponse({"status": "ok"})


async def get_user(request: Request):
    return JSONResponse(to_dict(store.get_user(request.path_params["user_id"])))


async def get_card(request: Request):
    return JSONResponse(to_dict(store.get_card(request.path_params["card_id"])))


async def list_card_transactions(request: Request):
    txns = store.list_transactions(request.path_params["card_id"], request.query_params.get("month"))
    return JSONResponse({"items": [to_dict(t) for t in txns]})


async def get_transaction(request: Request):
    return JSONResponse(to_dict(store.get_transaction(request.path_params["txn_id"])))


async def get_budget(request: Request):
    p = request.path_params
    return JSONResponse(store.department_budget(p["department"], p["month"]))


async def reports(request: Request):
    if request.method == "POST":
        body = await request.json()
        report = store.create_report(body["owner_id"], body["title"], body["txn_ids"])
        return JSONResponse(to_dict(report), status_code=201)
    q = request.query_params
    items = store.list_reports(q.get("owner_id"), q.get("approver_id"), q.get("status"))
    return JSONResponse({"items": [to_dict(r) for r in items]})


async def get_report(request: Request):
    return JSONResponse(to_dict(store.get_report(request.path_params["report_id"])))


async def submit_report(request: Request):
    body = await request.json()
    return JSONResponse(to_dict(store.submit_report(request.path_params["report_id"], body["approver_id"])))


async def decide_report(request: Request):
    body = await request.json()
    report = store.decide_report(request.path_params["report_id"], body["decision"], body.get("comment", ""))
    return JSONResponse(to_dict(report))


async def not_found(request: Request, exc: Exception):
    return JSONResponse({"error": str(exc)}, status_code=404)


async def conflict(request: Request, exc: Exception):
    return JSONResponse({"error": str(exc)}, status_code=409)


app = Starlette(
    routes=[
        Route("/health", health),
        Route("/api/v1/users/{user_id}", get_user),
        Route("/api/v1/cards/{card_id}", get_card),
        Route("/api/v1/cards/{card_id}/transactions", list_card_transactions),
        Route("/api/v1/transactions/{txn_id}", get_transaction),
        Route("/api/v1/budgets/{department}/{month}", get_budget),
        Route("/api/v1/expense-reports", reports, methods=["GET", "POST"]),
        Route("/api/v1/expense-reports/{report_id}", get_report),
        Route("/api/v1/expense-reports/{report_id}/submit", submit_report, methods=["POST"]),
        Route("/api/v1/expense-reports/{report_id}/decision", decide_report, methods=["POST"]),
    ],
    exception_handlers={NotFound: not_found, InvalidState: conflict},
    middleware=[Middleware(BearerAuthMiddleware)],
)


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Mock existing Bizplay REST API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
