"""Onboarding portal backend (Starlette). Serves the UI and a small JSON API.

Every /api/* endpoint except /api/login requires `Authorization: Bearer
<session token>`, mirroring the rule enforced on the Bizplay API and on
the MCP gateway.

Run:
    uv run bizplay-portal             # http://127.0.0.1:18090
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import time
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from bizplay_mcp import audit, policy_store

STATIC_DIR = Path(__file__).resolve().parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSION_TTL = 8 * 3600


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _mask(secret: str) -> str:
    return secret[:4] + "*" * max(4, len(secret) - 8) + secret[-4:] if len(secret) > 8 else "****"


# --- auth -------------------------------------------------------------------
class NoCacheUIMiddleware(BaseHTTPMiddleware):
    """Serve the UI with revalidation, so a deploy needs no hard reload.

    Files still return 304 when unchanged, so this costs one conditional
    request per asset rather than a full download.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


class SessionAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in ("/api/login", "/api/health"):
            scheme, _, token = request.headers.get("authorization", "").partition(" ")
            state = policy_store.load()
            session = state["sessions"].get(token.strip()) if scheme.lower() == "bearer" else None
            if not session or session["expires_at"] < time.time():
                return JSONResponse({"error": "missing or invalid bearer token"}, status_code=401,
                                    headers={"WWW-Authenticate": 'Bearer realm="bizplay-portal"'})
            request.state.user = session["email"]
            request.state.role = session["role"]
        return await call_next(request)


async def login(request: Request):
    body = await request.json()
    state = policy_store.load()
    user = state["portal_users"].get(body.get("email", "").lower())
    if not user or user["password"] != body.get("password", ""):
        raise ApiError(401, "Invalid email or password")
    token = "ps_" + secrets.token_urlsafe(24)
    state["sessions"][token] = {"email": body["email"].lower(), "role": user["role"], "expires_at": time.time() + SESSION_TTL}
    policy_store.save(state)
    return JSONResponse({"token": token, "user": {"email": body["email"].lower(), "name": user["name"], "role": user["role"]}})


async def logout(request: Request):
    _, _, token = request.headers.get("authorization", "").partition(" ")
    state = policy_store.load()
    state["sessions"].pop(token.strip(), None)
    policy_store.save(state)
    return JSONResponse({"ok": True})


async def me(request: Request):
    state = policy_store.load()
    user = state["portal_users"][request.state.user]
    return JSONResponse({"email": request.state.user, "name": user["name"], "role": user["role"]})


async def health(request: Request):
    return JSONResponse({"status": "ok"})


async def config(request: Request):
    """Values the setup instructions need that only the server knows."""
    return JSONResponse({
        # Where this deployment keeps the project. On a laptop it is the checkout
        # path; in Docker it is /app, which is why the UI asks the reader to
        # replace it with the path on the machine running their AI client.
        "project_dir": os.environ.get("BIZPLAY_PROJECT_DIR", str(PROJECT_ROOT)),
        "gateway_url": policy_store.public_url("curated", request.url.hostname),
        "registry_url": policy_store.public_url("registry", request.url.hostname),
        # When false, the gateways accept anonymous HTTP callers (demo only).
        "require_agent_token": bool(policy_store.load()["security"]["require_gateway_bearer"]),
    })


# --- overview ----------------------------------------------------------------
def _security_checklist(state: dict) -> list[dict]:
    sec = state["security"]
    active_tokens = [t for t in state["agent_tokens"].values() if not t["revoked"] and t["expires_at"] > time.time()]
    long_lived = [t for t in active_tokens if t["expires_at"] - t["created_at"] > 90 * 86400]
    write_unconfirmed = [
        f"{pid}.{name}" for pid, p in state["providers"].items()
        for name, t in p["tools"].items() if t["kind"] == "write" and t["enabled"] and not t["confirm"]
    ]
    open_published = [p["name"] for p in state["providers"].values()
                      if p.get("status") == "published" and p.get("auth_mode") == "open"]
    return [
        {"id": "upstream_bearer", "label": "Bizplay API endpoints require a bearer token",
         "ok": sec["require_upstream_bearer"], "detail": "Every /api/* call from the gateway carries the service token; the API answers 401 without it."},
        {"id": "no_open_providers", "label": "No published provider is an open (unauthenticated) API",
         "ok": not open_published,
         "detail": ("Accepted risk, demo data only: " + ", ".join(open_published)) if open_published
         else "Every published API is protected by a token or network isolation."},
        {"id": "gateway_bearer", "label": "MCP gateway requires a bearer token",
         "ok": sec["require_gateway_bearer"], "detail": "Agents must present a portal-issued token over HTTP."},
        {"id": "confirm_write", "label": "Write tools require user confirmation",
         "ok": not write_unconfirmed, "detail": "Unconfirmed: " + ", ".join(write_unconfirmed) if write_unconfirmed else "All enabled write tools ask before acting."},
        {"id": "token_ttl", "label": "No agent token lives longer than 90 days",
         "ok": not long_lived, "detail": f"{len(long_lived)} long-lived token(s)" if long_lived else "All tokens expire within 90 days."},
        {"id": "oauth", "label": "OAuth 2.1 identity provider connected",
         "ok": False, "detail": "Mockup uses portal-issued static tokens. Production: connect Bizplay SSO."},
        {"id": "secrets", "label": "Upstream credentials stored in a vault",
         "ok": False, "detail": "Mockup stores credentials in a JSON file. Production: KMS / vault."},
    ]


async def overview(request: Request):
    state = policy_store.load()
    now = time.time()
    tokens = state["agent_tokens"].values()
    checklist = _security_checklist(state)
    return JSONResponse({
        "providers": len(state["providers"]),
        "published": sum(p["status"] == "published" for p in state["providers"].values()),
        "tools_enabled": sum(t["enabled"] for p in state["providers"].values() for t in p["tools"].values()),
        "tokens_active": sum(1 for t in tokens if not t["revoked"] and t["expires_at"] > now),
        "audit_recent": audit.tail(8),
        "checklist": checklist,
        "score": round(100 * sum(c["ok"] for c in checklist) / len(checklist)),
    })


# --- registry ------------------------------------------------------------------
def _public_provider(p: dict) -> dict:
    out = {k: v for k, v in p.items() if k not in ("tools", "spec")}
    out.setdefault("auth_mode", "bearer")
    out["has_spec"] = bool(p.get("spec"))
    out["tool_count"] = len(p["tools"])
    out["tools_enabled"] = sum(t["enabled"] for t in p["tools"].values())
    return out


async def list_registry(request: Request):
    state = policy_store.load()
    return JSONResponse({"items": [_public_provider(p) for p in state["providers"].values()]})


def _normalize_base_url(base_url: str, spec: dict) -> tuple[str, str]:
    """Drop a path from the base URL when the spec's own paths already carry it.

    Registering https://api.example.com/api/v1 together with a spec whose paths
    start with /api/v1 makes every call hit /api/v1/api/v1/... and return 404.
    Returns (base_url, note).
    """
    scheme_host, _, path = base_url.partition("://")[2].partition("/")
    prefix = "/" + path.strip("/")
    paths = list(spec.get("paths", {}))
    if len(prefix) > 1 and paths and all(p.startswith(prefix + "/") for p in paths):
        fixed = base_url.split("://")[0] + "://" + scheme_host
        return fixed, f"Removed '{prefix}' from the base URL: the spec's paths already start with it."
    return base_url, ""


def _tools_from_spec(spec: dict) -> dict:
    tools = {}
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            name = op.get("operationId") or re.sub(r"[^a-z0-9]+", "_", f"{method}_{path}".lower()).strip("_")
            kind = "read" if method.lower() == "get" else "write"
            tools[name] = {"kind": kind, "enabled": True, "roles": ["employee", "manager"],
                           "confirm": kind == "write", "summary": op.get("summary", ""),
                           "route": f"{method.upper()} {path}"}
    return tools


async def register_provider(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    base_url = (body.get("base_url") or "").strip().rstrip("/")
    if not name or not base_url.startswith("http"):
        raise ApiError(400, "name and a valid base_url are required")
    spec = body.get("spec")
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError:
            raise ApiError(400, "spec must be valid OpenAPI JSON") from None
    if not isinstance(spec, dict) or "paths" not in spec:
        raise ApiError(400, "spec must be an OpenAPI document with 'paths'")
    base_url, base_note = _normalize_base_url(base_url, spec)
    auth_mode = body.get("auth_mode") or "bearer"
    if auth_mode not in policy_store.AUTH_MODES:
        raise ApiError(400, f"auth_mode must be one of {', '.join(policy_store.AUTH_MODES)}")
    allowlist = (body.get("allowlist") or "").strip()
    if auth_mode == "network" and not allowlist:
        raise ApiError(400, "network mode needs the gateway address the API allows (allowlist)")
    state = policy_store.load()
    pid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "provider"
    if pid in state["providers"]:
        pid = f"{pid}-{secrets.token_hex(2)}"
    cred_id = f"cred_{pid}_service"
    state["credentials"][cred_id] = {
        "id": cred_id, "provider_id": pid, "label": f"Gateway -> {name} service token", "type": "bearer",
        "secret": body.get("service_token") or "", "created_at": _now_iso(), "rotated_at": None,
    }
    state["providers"][pid] = {
        "id": pid, "name": name, "owner": request.state.user, "base_url": base_url,
        "spec_source": body.get("spec_source") or "uploaded", "spec": spec,
        # The address agents will use. Set BIZPLAY_PUBLIC_REGISTRY_URL when the
        # gateway is published on a different host or port than it listens on.
        "mcp_url": policy_store.public_url("registry", request.url.hostname),
        "tool_prefix": pid.replace("-", "_") + "_",
        "status": "draft", "auth_mode": auth_mode, "allowlist": allowlist, "upstream_credential_id": cred_id,
        "identity": {"issuer": "portal", "user_claim": "sub", "role_claim": "role", "company_claim": "company"},
        "tools": _tools_from_spec(spec), "created_at": _now_iso(),
    }
    policy_store.save(state)
    return JSONResponse({**_public_provider(state["providers"][pid]), "note": base_note}, status_code=201)


async def update_provider(request: Request):
    """Change how the gateway reaches an API after it was registered."""
    body = await request.json()
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    note = ""
    if "name" in body and body["name"].strip():
        p["name"] = body["name"].strip()
    if "base_url" in body:
        base_url = body["base_url"].strip().rstrip("/")
        if not base_url.startswith("http"):
            raise ApiError(400, "base_url must start with http")
        p["base_url"], note = _normalize_base_url(base_url, p.get("spec") or {})
    if "mcp_url" in body and body["mcp_url"].strip():
        p["mcp_url"] = body["mcp_url"].strip()
    if "auth_mode" in body:
        if body["auth_mode"] not in policy_store.AUTH_MODES:
            raise ApiError(400, f"auth_mode must be one of {', '.join(policy_store.AUTH_MODES)}")
        p["auth_mode"] = body["auth_mode"]
    if "allowlist" in body:
        p["allowlist"] = body["allowlist"].strip()
    if p["auth_mode"] == "network" and not p.get("allowlist"):
        raise ApiError(400, "network mode needs the gateway address the API allows")
    if body.get("service_token"):
        state["credentials"][p["upstream_credential_id"]]["secret"] = body["service_token"].strip()
        state["credentials"][p["upstream_credential_id"]]["rotated_at"] = _now_iso()
    policy_store.save(state)
    return JSONResponse({**_public_provider(p), "note": note})


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def _get_provider(state: dict, pid: str) -> dict:
    try:
        return state["providers"][pid]
    except KeyError:
        raise ApiError(404, f"unknown provider '{pid}'") from None


async def set_provider_status(request: Request):
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    action = request.path_params["action"]
    if action not in ("publish", "unpublish"):
        raise ApiError(400, "action must be publish or unpublish")
    mode = p.get("auth_mode", "bearer")
    if action == "publish" and mode == "bearer" and not state["credentials"][p["upstream_credential_id"]]["secret"]:
        raise ApiError(409, "bearer mode: add an upstream service token before publishing")
    if action == "publish" and mode == "network" and not p.get("allowlist"):
        raise ApiError(409, "network mode: record the allowlisted gateway address before publishing")
    p["status"] = "published" if action == "publish" else "draft"
    policy_store.save(state)
    return JSONResponse(_public_provider(p))


async def delete_provider(request: Request):
    state = policy_store.load()
    pid = request.path_params["pid"]
    if pid == "bizplay":
        raise ApiError(409, "the Bizplay demo provider cannot be deleted")
    p = _get_provider(state, pid)
    state["credentials"].pop(p["upstream_credential_id"], None)
    del state["providers"][pid]
    policy_store.save(state)
    return JSONResponse({"ok": True})


async def test_provider(request: Request):
    """Probe the provider: /health must be open, /api/* must answer 401 without a token."""
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    secret = state["credentials"][p["upstream_credential_id"]]["secret"]
    # Curated providers (like the Bizplay seed) have no per-tool routes; fall back to a known endpoint.
    routes = [t["route"].split(" ", 1)[1] for t in p["tools"].values() if t["kind"] == "read" and t.get("route")]
    probe_path = next((r for r in routes if "{" not in r), routes[0] if routes else "/api/v1/users/emp001")
    probe_path = probe_path.replace("{user_id}", "emp001").replace("{card_id}", "card-1001")
    results = []
    async with httpx.AsyncClient(base_url=p["base_url"], timeout=8.0) as client:
        # 1. Reachability: any HTTP answer counts. Try common health paths first for a nicer status.
        reach = {"check": "API reachable", "path": "/health", "status": None, "ok": False}
        for path in ("/health", "/actuator/health", probe_path):
            try:
                r = await client.get(path)
                reach.update(path=path, status=r.status_code, ok=True)
                if r.status_code == 200:
                    break
            except httpx.HTTPError as exc:
                reach.update(path=path, error=str(exc)[:120])
        results.append(reach)

        mode = p.get("auth_mode", "bearer")
        # 2. Anonymous call: must be refused in bearer mode; recorded as accepted risk otherwise.
        try:
            r = await client.get(probe_path)
            anon = {"path": probe_path, "status": r.status_code}
        except httpx.HTTPError as exc:
            anon = {"path": probe_path, "status": None, "error": str(exc)[:120]}
        if mode == "bearer":
            results.append({"check": "Protected endpoint rejects missing token", **anon,
                            "ok": anon["status"] in (401, 403)})
        elif mode == "network":
            results.append({"check": "Anonymous call from the gateway host succeeds (network mode)", **anon,
                            "ok": anon["status"] == 200,
                            "note": f"Isolation itself cannot be verified from here; allowlist recorded: {p.get('allowlist')}"})
        else:
            results.append({"check": "Anonymous call succeeds (open mode, accepted risk)", **anon,
                            "ok": anon["status"] == 200,
                            "note": "The gateway enforces identity, policy, and company scoping; the API itself is public."})

        # 3. Bearer mode only: the stored service token must be accepted.
        if mode != "bearer":
            results.append({"check": "Service token", "path": probe_path, "status": None, "ok": True,
                            "note": f"not used in {mode} mode"})
        elif not secret:
            results.append({"check": "Protected endpoint accepts service token", "path": probe_path, "status": None,
                            "ok": False, "error": "no service token set on this provider (Security page > Rotate, or re-register)"})
        else:
            try:
                r = await client.get(probe_path, headers={"Authorization": f"Bearer {secret}"})
                results.append({"check": "Protected endpoint accepts service token", "path": probe_path,
                                "status": r.status_code, "ok": r.status_code in (200, 404)})
            except httpx.HTTPError as exc:
                results.append({"check": "Protected endpoint accepts service token", "path": probe_path,
                                "status": None, "ok": False, "error": str(exc)[:120]})
    return JSONResponse({"provider": p["id"], "results": results, "ok": all(r["ok"] for r in results)})


# --- tools / access control -----------------------------------------------------
async def list_tools(request: Request):
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    return JSONResponse({"provider": p["id"], "roles": ["employee", "manager"],
                         "items": [{"name": n, **t} for n, t in p["tools"].items()]})


async def update_tool(request: Request):
    body = await request.json()
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    name = request.path_params["name"]
    if name not in p["tools"]:
        raise ApiError(404, f"unknown tool '{name}'")
    tool = p["tools"][name]
    for key in ("enabled", "confirm"):
        if key in body:
            tool[key] = bool(body[key])
    if "roles" in body:
        roles = [r for r in body["roles"] if r in ("employee", "manager")]
        tool["roles"] = roles
    policy_store.save(state)
    return JSONResponse({"name": name, **tool})


# --- agent tokens ---------------------------------------------------------------
async def list_tokens(request: Request):
    state = policy_store.load()
    items = sorted((policy_store.public_token(t) for t in state["agent_tokens"].values()),
                   key=lambda t: t["created_at"], reverse=True)
    return JSONResponse({"items": items, "now": time.time()})


async def issue_token(request: Request):
    body = await request.json()
    state = policy_store.load()
    role = body.get("role")
    if role not in ("employee", "manager"):
        raise ApiError(400, "role must be employee or manager")
    ttl = int(body.get("ttl_days") or state["security"]["token_ttl_days"])
    if not 1 <= ttl <= 365:
        raise ApiError(400, "ttl_days must be between 1 and 365")
    token, record = policy_store.issue_agent_token(
        state, label=(body.get("label") or "Untitled").strip(), user_id=(body.get("user_id") or "").strip(),
        role=role, company=(body.get("company") or "Bizplay Demo Co.").strip(),
        agent=body.get("agent") or "Claude Desktop", ttl_days=ttl, created_by=request.state.user,
    )
    if not record["sub"]:
        raise ApiError(400, "user_id is required")
    policy_store.save(state)
    return JSONResponse({"token": token, "record": policy_store.public_token(record)}, status_code=201)


async def revoke_token(request: Request):
    state = policy_store.load()
    record = state["agent_tokens"].get(request.path_params["tid"])
    if not record:
        raise ApiError(404, "unknown token")
    record["revoked"] = True
    policy_store.save(state)
    return JSONResponse(policy_store.public_token(record))


# --- security -------------------------------------------------------------------
async def security(request: Request):
    state = policy_store.load()
    creds = [{**c, "secret": _mask(c["secret"]) if c["secret"] else "(not set)"} for c in state["credentials"].values()]
    return JSONResponse({"settings": state["security"], "credentials": creds, "checklist": _security_checklist(state),
                         "identity": {p["id"]: p["identity"] for p in state["providers"].values()}})


async def update_security(request: Request):
    body = await request.json()
    state = policy_store.load()
    sec = state["security"]
    for key in ("require_upstream_bearer", "require_gateway_bearer", "confirm_on_write"):
        if key in body:
            sec[key] = bool(body[key])
    if "token_ttl_days" in body:
        sec["token_ttl_days"] = max(1, min(365, int(body["token_ttl_days"])))
    if body.get("confirm_on_write"):
        for p in state["providers"].values():
            for t in p["tools"].values():
                if t["kind"] == "write":
                    t["confirm"] = True
    policy_store.save(state)
    return JSONResponse(sec)


async def rotate_credential(request: Request):
    state = policy_store.load()
    cred = state["credentials"].get(request.path_params["cid"])
    if not cred:
        raise ApiError(404, "unknown credential")
    body = await request.json() if request.headers.get("content-length", "0") not in ("", "0") else {}
    cred["secret"] = (body.get("secret") or "").strip() or "svc_" + secrets.token_urlsafe(24)
    cred["rotated_at"] = _now_iso()
    policy_store.save(state)
    return JSONResponse({"id": cred["id"], "secret": cred["secret"], "rotated_at": cred["rotated_at"],
                         "note": "Give this token to the provider: their API must accept it (BIZPLAY_API_TOKENS) "
                                 "and the gateway must send it (BIZPLAY_API_TOKEN)."})


# --- audit ----------------------------------------------------------------------
async def audit_log(request: Request):
    limit = max(1, min(500, int(request.query_params.get("limit", "100"))))
    return JSONResponse({"items": audit.tail(limit)})


# --- app -------------------------------------------------------------------------
async def index(request: Request):
    return FileResponse(STATIC_DIR / "index.html")


async def api_error(request: Request, exc: ApiError):
    return JSONResponse({"error": exc.message}, status_code=exc.status)


app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/health", health),
        Route("/api/config", config),
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/me", me),
        Route("/api/overview", overview),
        Route("/api/registry", list_registry),
        Route("/api/registry", register_provider, methods=["POST"]),
        Route("/api/registry/{pid}", update_provider, methods=["PATCH"]),
        Route("/api/registry/{pid}", delete_provider, methods=["DELETE"]),
        Route("/api/registry/{pid}/test", test_provider, methods=["POST"]),
        Route("/api/registry/{pid}/tools", list_tools),
        Route("/api/registry/{pid}/tools/{name}", update_tool, methods=["PUT"]),
        Route("/api/registry/{pid}/{action}", set_provider_status, methods=["POST"]),
        Route("/api/tokens", list_tokens),
        Route("/api/tokens", issue_token, methods=["POST"]),
        Route("/api/tokens/{tid}/revoke", revoke_token, methods=["POST"]),
        Route("/api/security", security),
        Route("/api/security", update_security, methods=["PUT"]),
        Route("/api/credentials/{cid}/rotate", rotate_credential, methods=["POST"]),
        Route("/api/audit", audit_log),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ],
    exception_handlers={ApiError: api_error},
    middleware=[Middleware(NoCacheUIMiddleware), Middleware(SessionAuthMiddleware)],
)


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Bizplay MCP onboarding portal (mockup)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18090)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
