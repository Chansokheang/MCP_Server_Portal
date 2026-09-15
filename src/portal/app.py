"""Onboarding portal backend (Starlette). Serves the UI and a small JSON API.

Every /api/* endpoint except /api/login requires `Authorization: Bearer
<session token>`, mirroring the rule enforced on the Bizplay API and on
the MCP gateway.

The portal process also serves the registry gateway on its own origin
(/mcp and /mcp/<provider>), so one public host name covers both the UI and
the endpoints agents connect to.

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
from fastmcp import Client
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from bizplay_mcp import audit, oauth, policy_store, specs
from bizplay_mcp.registry_gateway import build_registry_asgi

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
        # The same registry gateway, served by this portal on the address the browser used.
        "portal_mcp_url": _origin(request) + "/mcp",
        # What the register dialog prefills; the person registering can change it.
        # The UI prefers the browser's own origin over the server-derived one, since
        # a proxy in front may not forward the host name it was reached on.
        "default_mcp_url": _default_endpoint(policy_store.load(), request),
        "public_mcp_url": policy_store.load()["security"].get("public_mcp_url", "").strip(),
        # Where backends' auth servers send users back after they sign in.
        "oauth_redirect_uri": _redirect_uri(request),
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
    out.setdefault("kind", "openapi")
    out.setdefault("standalone", False)
    cfg = p.get("oauth") or {}
    out["oauth"] = {k: v for k, v in cfg.items() if k != "client_secret"} | {"has_client_secret": bool(cfg.get("client_secret"))}
    out["oauth_ready"] = _oauth_ready(p)
    out["access"] = p.get("access") or {"mode": "everyone", "groups": [], "companies": []}
    out["connections"] = len(oauth.public_connections(policy_store.load(), p["id"])) if p.get("auth_mode") == "oauth" else 0
    out["has_spec"] = bool(p.get("spec"))
    out["standalone_url"] = policy_store.standalone_url(p)
    out["tool_count"] = len(p["tools"])
    out["tools_enabled"] = sum(t["enabled"] for t in p["tools"].values())
    return out


async def list_registry(request: Request):
    state = policy_store.load()
    return JSONResponse({"items": [_public_provider(p) for p in state["providers"].values()]})


def _origin(request: Request) -> str:
    """The address the browser reached this portal on, as seen through any proxy."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    return f"{scheme}://{host}"


def _default_endpoint(state: dict, request: Request) -> str:
    """The endpoint to offer when registering, which the caller may replace.

    The public address set on the Security page wins; otherwise the gateway
    this portal serves on its own origin, which is reachable wherever the
    portal is. It is only a prefill: whatever the caller sends is used as is.
    """
    return state["security"].get("public_mcp_url", "").strip() or _origin(request) + "/mcp"


def _redirect_uri(request: Request) -> str:
    return _origin(request) + "/oauth/callback"


OAUTH_FIELDS = ("authorization_url", "token_url", "client_id", "client_secret", "scopes", "registration_url", "resource")


def _oauth_config(body: dict, existing: dict | None = None) -> dict:
    """Merge OAuth settings from a request into the stored ones; blank values keep what was there."""
    cfg = dict(existing or {})
    for key in OAUTH_FIELDS:
        value = (body.get(key) or "").strip()
        if value:
            cfg[key] = value
    for key in ("authorization_url", "token_url", "registration_url"):
        if cfg.get(key) and not cfg[key].startswith("http"):
            raise ApiError(400, f"{key} must start with http")
    return cfg


def _listed(value) -> list[str]:
    """A list from either a JSON list or a comma-separated string, trimmed and de-duplicated."""
    items = value.split(",") if isinstance(value, str) else list(value or [])
    return sorted({str(v).strip() for v in items if str(v).strip()})


def _access_config(body: dict) -> dict:
    """Who may use a backend: everyone, listed access groups, or listed companies."""
    mode = body.get("mode") or "everyone"
    if mode not in policy_store.ACCESS_MODES:
        raise ApiError(400, f"access mode must be one of {', '.join(policy_store.ACCESS_MODES)}")
    cfg = {"mode": mode, "groups": _listed(body.get("groups")), "companies": _listed(body.get("companies"))}
    if mode == "groups" and not cfg["groups"]:
        raise ApiError(400, "list at least one access group, or choose everyone")
    if mode == "companies" and not cfg["companies"]:
        raise ApiError(400, "list at least one company, or choose everyone")
    return cfg


async def list_groups(request: Request):
    """Access groups in use anywhere, so dialogs can suggest them."""
    state = policy_store.load()
    groups = {g for t in state["agent_tokens"].values() for g in t.get("groups") or []}
    groups |= {g for p in state["providers"].values() for g in (p.get("access") or {}).get("groups") or []}
    return JSONResponse({"items": sorted(groups)})


def _oauth_ready(p: dict) -> bool:
    cfg = p.get("oauth") or {}
    return bool(cfg.get("authorization_url") and cfg.get("token_url") and cfg.get("client_id"))


def mcp_client(url: str, headers: dict[str, str]) -> Client:
    """Client for an MCP server being registered. Tests swap this for an in-memory one."""
    return Client(specs.mcp_transport(url, headers), timeout=15)


def _backend_headers(state: dict, p: dict, user_id: str | None = None) -> dict[str, str]:
    """Headers the portal itself uses to talk to a backend (tests, tool refresh)."""
    if p.get("auth_mode") == "oauth":
        record = oauth.connection(state, p["id"], user_id) if user_id else None
        token = record["access_token"] if record else oauth.any_token(state, p["id"])
        return {"Authorization": f"Bearer {token}"} if token else {}
    return _upstream_headers(state, p)


async def _tools_from_mcp_server(url: str, headers: dict[str, str]) -> dict:
    try:
        async with mcp_client(url, headers) as c:
            return specs.tools_from_mcp(await c.list_tools())
    except Exception as exc:  # noqa: BLE001 - any transport or protocol failure reads the same to the caller
        raise ApiError(502, f"could not list tools from the MCP server at {url}: {str(exc)[:160]}") from None


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


async def register_provider(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    base_url = (body.get("base_url") or "").strip().rstrip("/")
    if not name or not base_url.startswith("http"):
        raise ApiError(400, "name and a valid base_url are required")
    kind = body.get("kind") or "openapi"
    if kind not in policy_store.KINDS:
        raise ApiError(400, f"kind must be one of {', '.join(policy_store.KINDS)}")
    # Whatever endpoint the caller gives is used verbatim; the default is a prefill.
    mcp_url = (body.get("mcp_url") or "").strip()
    if mcp_url and not mcp_url.startswith("http"):
        raise ApiError(400, "mcp_url must start with http")
    auth_mode = body.get("auth_mode") or "bearer"
    if auth_mode not in policy_store.AUTH_MODES:
        raise ApiError(400, f"auth_mode must be one of {', '.join(policy_store.AUTH_MODES)}")
    allowlist = (body.get("allowlist") or "").strip()
    if auth_mode == "network" and not allowlist:
        raise ApiError(400, "network mode needs the gateway address the API allows (allowlist)")
    service_token = (body.get("service_token") or "").strip()

    base_note = ""
    spec = None
    oauth_cfg = _oauth_config(body.get("oauth") or {}) if auth_mode == "oauth" else {}
    if kind == "mcp":
        # An MCP server that already exists: its own tool list is the policy table.
        # In OAuth mode nobody has linked an account yet, so the list waits for
        # the first connection (Refresh tools on the provider page).
        if auth_mode == "oauth":
            tools = {}
            base_note = "OAuth backend: connect an account, then Refresh tools to load its tool list."
        else:
            headers = {"Authorization": f"Bearer {service_token}"} if auth_mode == "bearer" and service_token else {}
            tools = await _tools_from_mcp_server(base_url, headers)
        spec_source = "MCP server"
    else:
        spec = body.get("spec")
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except json.JSONDecodeError:
                raise ApiError(400, "spec must be valid OpenAPI JSON") from None
        if not isinstance(spec, dict) or "paths" not in spec:
            raise ApiError(400, "spec must be an OpenAPI document with 'paths'")
        base_url, base_note = _normalize_base_url(base_url, spec)
        try:
            tools = specs.tools_from_spec(spec)
        except ValueError as exc:
            raise ApiError(400, f"spec could not be parsed: {str(exc)[:160]}") from None
        spec_source = body.get("spec_source") or "uploaded"

    state = policy_store.load()
    mcp_url = mcp_url or _default_endpoint(state, request)
    pid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "provider"
    if pid in state["providers"]:
        pid = f"{pid}-{secrets.token_hex(2)}"
    cred_id = f"cred_{pid}_service"
    state["credentials"][cred_id] = {
        "id": cred_id, "provider_id": pid, "label": f"Gateway -> {name} service token", "type": "bearer",
        "secret": service_token, "created_at": _now_iso(), "rotated_at": None,
    }
    state["providers"][pid] = {
        "id": pid, "name": name, "owner": request.state.user, "kind": kind, "base_url": base_url,
        "spec_source": spec_source, "spec": spec,
        "mcp_url": mcp_url, "standalone": False, "oauth": oauth_cfg,
        "tool_prefix": pid.replace("-", "_") + "_",
        "status": "draft", "auth_mode": auth_mode, "allowlist": allowlist, "upstream_credential_id": cred_id,
        "identity": {"issuer": "portal", "user_claim": "sub", "role_claim": "role", "company_claim": "company"},
        "tools": tools, "created_at": _now_iso(),
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
        # A moved MCP server may expose a different tool list; refresh it, keeping policy.
        if p.get("kind") == "mcp" and (p.get("auth_mode") != "oauth" or oauth.any_token(state, p["id"])):
            fresh = await _tools_from_mcp_server(p["base_url"], _backend_headers(state, p))
            _merge_tools(p, fresh)
            note = f"Tool list refreshed: {len(fresh)} tool(s)."
    if "oauth" in body and isinstance(body["oauth"], dict):
        p["oauth"] = _oauth_config(body["oauth"], p.get("oauth"))
    if "access" in body and isinstance(body["access"], dict):
        p["access"] = _access_config(body["access"])
    if "mcp_url" in body and body["mcp_url"].strip():
        p["mcp_url"] = body["mcp_url"].strip()
        # One gateway, one public address: remember it for the next registration.
        if p["mcp_url"].startswith("https://"):
            state["security"]["public_mcp_url"] = p["mcp_url"]
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


def _upstream_headers(state: dict, p: dict) -> dict[str, str]:
    secret = state["credentials"].get(p.get("upstream_credential_id", ""), {}).get("secret", "")
    return {"Authorization": f"Bearer {secret}"} if p.get("auth_mode", "bearer") == "bearer" and secret else {}


def _merge_tools(p: dict, fresh: dict) -> None:
    """Replace the tool table with a fresh one, keeping enable/role/confirm choices."""
    p["tools"] = {n: {**row, **{k: p["tools"][n][k] for k in ("enabled", "roles", "confirm")}} if n in p["tools"] else row
                  for n, row in fresh.items()}


def _publish_gate(state: dict, p: dict) -> None:
    mode = p.get("auth_mode", "bearer")
    if mode == "bearer" and not state["credentials"][p["upstream_credential_id"]]["secret"]:
        raise ApiError(409, "bearer mode: add an upstream service token before publishing")
    if mode == "network" and not p.get("allowlist"):
        raise ApiError(409, "network mode: record the allowlisted gateway address before publishing")
    if mode == "oauth" and not _oauth_ready(p):
        raise ApiError(409, "OAuth mode: set the authorization URL, token URL and client id (or use Discover) before publishing")


async def set_provider_status(request: Request):
    """publish / unpublish on the shared gateway; deploy / undeploy the standalone endpoint."""
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    action = request.path_params["action"]
    if action not in ("publish", "unpublish", "deploy", "undeploy"):
        raise ApiError(400, "action must be publish, unpublish, deploy or undeploy")
    if action in ("publish", "deploy"):
        _publish_gate(state, p)
    if action == "deploy" and not (p.get("spec") or p.get("kind") == "mcp"):
        raise ApiError(409, "the curated Bizplay provider is already its own server; deploy applies to registered APIs")
    if action in ("publish", "unpublish"):
        p["status"] = "published" if action == "publish" else "draft"
    else:
        # A standalone endpoint is only served for a published provider, so
        # deploying also publishes; undeploying leaves the shared endpoint alone.
        p["standalone"] = action == "deploy"
        if action == "deploy":
            p["status"] = "published"
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


async def _test_mcp_server(state: dict, p: dict) -> list[dict]:
    """An MCP backend passes when it completes the handshake and lists its tools."""
    results = []
    if p.get("auth_mode") == "oauth":
        results.append({"check": "OAuth configuration", "path": (p.get("oauth") or {}).get("authorization_url", ""),
                        "status": None, "ok": _oauth_ready(p),
                        "note": "authorization URL, token URL and client id set" if _oauth_ready(p)
                        else "incomplete: use Discover or fill the fields under Edit connection"})
        if not oauth.any_token(state, p["id"]):
            results.append({"check": "A linked account to test with", "path": "Connect account", "status": None, "ok": False,
                            "error": "no user has connected an account yet, so the server cannot be called"})
            return results
    try:
        async with mcp_client(p["base_url"], _backend_headers(state, p)) as c:  # entering = initialize handshake
            results.append({"check": "MCP server answers initialize", "path": p["base_url"], "status": "ok", "ok": True})
            listed = await c.list_tools()
            known = set(p["tools"])
            new = [t.name for t in listed if t.name not in known]
            results.append({"check": "Tools listed", "path": "tools/list", "status": len(listed), "ok": bool(listed),
                            "note": (f"{len(new)} tool(s) not in the policy table yet, save Edit connection to refresh: " + ", ".join(new[:5]))
                            if new else f"{len(listed)} tool(s), all in the policy table"})
    except Exception as exc:  # noqa: BLE001
        results.append({"check": "MCP server answers initialize", "path": p["base_url"], "status": None, "ok": False,
                        "error": str(exc)[:160]})
    mode = p.get("auth_mode", "bearer")
    results.append({"check": "Upstream credential", "path": p["base_url"], "status": None, "ok": True,
                    "note": {"bearer": "the stored service token is sent as a bearer header",
                             "oauth": "each caller's own linked token is sent"}.get(mode, f"none sent in {mode} mode")})
    return results


async def test_provider(request: Request):
    """Probe the provider: /health must be open, /api/* must answer 401 without a token."""
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    if p.get("kind") == "mcp":
        results = await _test_mcp_server(state, p)
        return JSONResponse({"provider": p["id"], "results": results, "ok": all(r["ok"] for r in results)})
    secret = state["credentials"][p["upstream_credential_id"]]["secret"]
    # Probe with one of the API's own GET routes, preferring one without path
    # parameters; any parameter left is filled with a placeholder, since the
    # point is the status code, not the record. The curated Bizplay seed stores
    # no routes, so it falls back to a path its mock API serves.
    routes = [t["route"].split(" ", 1)[1] for t in p["tools"].values() if t["kind"] == "read" and t.get("route", "").startswith("GET ")]
    probe_path = next((r for r in routes if "{" not in r), routes[0] if routes else "/api/v1/users/emp001")
    probe_path = re.sub(r"\{[^}]+\}", "1", probe_path)
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
        elif mode == "oauth":
            results.append({"check": "Protected endpoint rejects missing token", **anon,
                            "ok": anon["status"] in (401, 403),
                            "note": "each caller's own linked token is sent at call time"})
            results.append({"check": "OAuth configuration", "path": (p.get("oauth") or {}).get("token_url", ""),
                            "status": None, "ok": _oauth_ready(p),
                            "note": "authorization URL, token URL and client id set" if _oauth_ready(p)
                            else "incomplete: fill the fields under Edit connection"})
            return JSONResponse({"provider": p["id"], "results": results, "ok": all(r["ok"] for r in results)})
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


# --- per-user OAuth: link accounts on backends that want the user's own token --------
async def oauth_discover(request: Request):
    """Read the backend's auth metadata and, when it allows it, register the gateway as a client."""
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    body = await request.json() if request.headers.get("content-length", "0") not in ("", "0") else {}
    url = (body.get("url") or p["base_url"]).strip()
    try:
        found = await oauth.discover(url)
    except (oauth.OAuthError, httpx.HTTPError) as exc:
        raise ApiError(502, str(exc)[:200]) from None
    cfg = dict(p.get("oauth") or {})
    for key in ("authorization_url", "token_url", "registration_url", "resource"):
        if found.get(key):
            cfg[key] = found[key]
    if found.get("scopes") and not cfg.get("scopes"):
        cfg["scopes"] = found["scopes"]
    registered = False
    if not cfg.get("client_id") and cfg.get("registration_url"):
        try:
            cfg.update(await oauth.register_client(cfg["registration_url"], _redirect_uri(request), "Bizplay MCP Gateway"))
            registered = True
        except (oauth.OAuthError, httpx.HTTPError) as exc:
            raise ApiError(502, f"metadata found but client registration failed: {str(exc)[:160]}") from None
    p["oauth"] = cfg
    if p.get("auth_mode") != "oauth":
        p["auth_mode"] = "oauth"
    policy_store.save(state)
    return JSONResponse({**_public_provider(p), "registered_client": registered, "redirect_uri": _redirect_uri(request),
                         "note": ("Client registered with the auth server." if registered else
                                  "Endpoints found." + ("" if cfg.get("client_id") else " The server offers no dynamic registration: enter the client id it gave you."))})


async def oauth_start(request: Request):
    """Begin linking one user's account: returns the URL to open."""
    body = await request.json()
    user_id = (body.get("user_id") or "").strip()
    if not user_id:
        raise ApiError(400, "user_id is required: the Bizplay user whose account is being linked")
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    if p.get("auth_mode") != "oauth":
        raise ApiError(409, "this backend is not in OAuth mode")
    try:
        url = oauth.start(state, p, user_id, _redirect_uri(request))
    except oauth.OAuthError as exc:
        raise ApiError(409, str(exc)) from None
    policy_store.save(state)
    return JSONResponse({"authorization_url": url, "redirect_uri": _redirect_uri(request), "user_id": user_id})


async def oauth_callback(request: Request):
    """Where the backend's auth server sends the user back. No portal session: the state nonce is the proof."""
    q = request.query_params
    state = policy_store.load()
    if q.get("error"):
        return RedirectResponse(f"/#registry?oauth_error={q.get('error_description') or q['error']}", status_code=303)
    try:
        provider, pending = await oauth.finish(state, q.get("state", ""), q.get("code", ""))
    except (oauth.OAuthError, httpx.HTTPError) as exc:
        policy_store.save(state)
        return RedirectResponse(f"/#registry?oauth_error={str(exc)[:160]}", status_code=303)
    # First linked account on an MCP backend: load its tool list right away, so the
    # page the user lands on already shows the tools instead of asking for a refresh.
    loaded = ""
    if provider.get("kind") == "mcp" and not provider.get("tools"):
        try:
            fresh = await _tools_from_mcp_server(provider["base_url"], _backend_headers(state, provider, pending["user_id"]))
            _merge_tools(provider, fresh)
            loaded = f"&tools={len(fresh)}"
        except ApiError:
            pass  # the page offers Refresh tools; the link itself succeeded
    policy_store.save(state)
    audit.record(pending["user_id"], f"oauth:{provider['id']}", {}, "ok", "account linked", via="portal")
    return RedirectResponse(f"/#provider?p={provider['id']}&connected={pending['user_id']}{loaded}", status_code=303)


async def list_connections(request: Request):
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    return JSONResponse({"provider": p["id"], "items": oauth.public_connections(state, p["id"]), "now": time.time()})


async def delete_connection(request: Request):
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    if not oauth.disconnect(state, p["id"], request.path_params["user_id"]):
        raise ApiError(404, "no linked account for that user")
    policy_store.save(state)
    return JSONResponse({"ok": True})


async def refresh_tools(request: Request):
    """Re-read an MCP backend's tool list, with a linked user's token when it needs one."""
    body = await request.json() if request.headers.get("content-length", "0") not in ("", "0") else {}
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    if p.get("kind") != "mcp":
        raise ApiError(409, "only MCP backends can refresh their tool list; re-register a REST API with a new spec")
    headers = _backend_headers(state, p, (body.get("user_id") or "").strip() or None)
    if p.get("auth_mode") == "oauth" and not headers:
        raise ApiError(409, "connect an account first: the server needs a user's token to list its tools")
    fresh = await _tools_from_mcp_server(p["base_url"], headers)
    _merge_tools(p, fresh)
    policy_store.save(state)
    return JSONResponse({**_public_provider(p), "note": f"Tool list refreshed: {len(fresh)} tool(s)."})


# --- named gateways: a chosen set of backends on their own URL ---------------------
def _public_gateway(state: dict, g: dict, request: Request) -> dict:
    providers = [state["providers"][pid] for pid in g.get("providers", []) if pid in state["providers"]]
    # Same base as the register prefill: the public endpoint if set, else the address the browser used.
    return {**g, "url": _default_endpoint(state, request).rstrip("/") + "/" + g["id"],
            "backends": [{"id": p["id"], "name": p["name"], "status": p.get("status"),
                          "tools_enabled": sum(t["enabled"] for t in p["tools"].values())} for p in providers],
            "tools_enabled": sum(t["enabled"] for p in providers if p.get("status") == "published" for t in p["tools"].values())}


def _gateway_providers(state: dict, value) -> list[str]:
    ids = _listed(value)
    unknown = [i for i in ids if i not in state["providers"]]
    if unknown:
        raise ApiError(400, f"unknown backend(s): {', '.join(unknown)}")
    servable = [i for i in ids if state["providers"][i].get("spec") or state["providers"][i].get("kind") == "mcp"]
    if not servable:
        raise ApiError(400, "pick at least one registered backend (the curated Bizplay server is not served by the registry gateway)")
    return servable


async def list_gateways(request: Request):
    state = policy_store.load()
    return JSONResponse({"items": [_public_gateway(state, g, request) for g in state["gateways"].values()]})


async def create_gateway(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(400, "name is required")
    state = policy_store.load()
    gid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "gateway"
    if gid in state["gateways"] or gid in state["providers"]:
        raise ApiError(409, f"'{gid}' is already used by another gateway or backend; pick another name")
    g = {"id": gid, "name": name, "providers": _gateway_providers(state, body.get("providers")),
         "description": (body.get("description") or "").strip(), "owner": request.state.user, "created_at": _now_iso()}
    state["gateways"][gid] = g
    policy_store.save(state)
    return JSONResponse(_public_gateway(state, g, request), status_code=201)


async def update_gateway(request: Request):
    body = await request.json()
    state = policy_store.load()
    g = state["gateways"].get(request.path_params["gid"])
    if not g:
        raise ApiError(404, "unknown gateway")
    if body.get("name", "").strip():
        g["name"] = body["name"].strip()
    if "description" in body:
        g["description"] = (body["description"] or "").strip()
    if "providers" in body:
        g["providers"] = _gateway_providers(state, body["providers"])
    policy_store.save(state)
    return JSONResponse(_public_gateway(state, g, request))


async def delete_gateway(request: Request):
    state = policy_store.load()
    if state["gateways"].pop(request.path_params["gid"], None) is None:
        raise ApiError(404, "unknown gateway")
    policy_store.save(state)
    return JSONResponse({"ok": True})


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
    if "groups" in body:
        tool["groups"] = _listed(body["groups"])
    if "description" in body:
        tool["description"] = " ".join(str(body["description"]).split())[:600]
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
    groups = body.get("groups") or []
    if isinstance(groups, str):
        groups = groups.split(",")
    token, record = policy_store.issue_agent_token(
        state, label=(body.get("label") or "Untitled").strip(), user_id=(body.get("user_id") or "").strip(),
        role=role, company=(body.get("company") or "Bizplay Demo Co.").strip(),
        agent=body.get("agent") or "Claude Desktop", ttl_days=ttl, created_by=request.state.user, groups=groups,
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
    if "public_mcp_url" in body:
        url = body["public_mcp_url"].strip()
        if url and not url.startswith("http"):
            raise ApiError(400, "public_mcp_url must start with http")
        sec["public_mcp_url"] = url
        # A backend does not own an endpoint: every registered one follows the public address,
        # so its standalone URL and setup instructions move with it.
        base = url or _origin(request) + "/mcp"
        for p in state["providers"].values():
            if p.get("spec") or p.get("kind") == "mcp":
                p["mcp_url"] = base
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
        Route("/api/registry/{pid}/oauth/discover", oauth_discover, methods=["POST"]),
        Route("/api/registry/{pid}/oauth/start", oauth_start, methods=["POST"]),
        Route("/api/registry/{pid}/connections", list_connections),
        Route("/api/registry/{pid}/connections/{user_id}", delete_connection, methods=["DELETE"]),
        Route("/api/registry/{pid}/refresh-tools", refresh_tools, methods=["POST"]),
        Route("/api/registry/{pid}/{action}", set_provider_status, methods=["POST"]),
        Route("/oauth/callback", oauth_callback),
        Route("/api/groups", list_groups),
        Route("/api/gateways", list_gateways),
        Route("/api/gateways", create_gateway, methods=["POST"]),
        Route("/api/gateways/{gid}", update_gateway, methods=["PATCH"]),
        Route("/api/gateways/{gid}", delete_gateway, methods=["DELETE"]),
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


class PortalWithGateway:
    """One process, one origin: the portal UI and API, plus the registry gateway under /mcp.

    The gateway is called directly rather than mounted, so its streaming
    responses never pass through the portal's request middleware, and its
    lifespan (the MCP session manager) is the process lifespan.
    """

    def __init__(self, portal: Starlette, gateway) -> None:
        self.portal = portal
        self.gateway = gateway

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            return await self.gateway(scope, receive, send)
        if scope["type"] == "http" and (scope["path"] == "/mcp" or scope["path"].startswith("/mcp/")):
            return await self.gateway(scope, receive, send)
        return await self.portal(scope, receive, send)


def create_app(gateway=None) -> PortalWithGateway:
    """The deployable app. `gateway` may be a FastMCP server (wrapped here) or an ASGI app."""
    if gateway is None or not callable(gateway):
        gateway = build_registry_asgi(gateway)
    return PortalWithGateway(app, gateway)


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Bizplay MCP onboarding portal (mockup)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18090)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
