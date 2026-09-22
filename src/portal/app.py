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
from datetime import datetime, timezone
import time
from pathlib import Path

import httpx
from fastmcp import Client
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from bizplay_mcp import guidance, login_auth, audit, oauth, policy_store, specs
from bizplay_mcp.registry_gateway import build_registry_asgi
from portal import gateway_oauth

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


# What a member (an employee signed in to serve themselves) may call. Everything else is admin only.
MEMBER_ROUTES = [
    ("GET", re.compile(r"^/api/(me|config|tokens|registry|gateways|groups)$")),
    ("POST", re.compile(r"^/api/(logout|tokens)$")),
    ("POST", re.compile(r"^/api/tokens/[^/]+/revoke$")),
    ("GET", re.compile(r"^/api/registry/[^/]+/(connections|tools)$")),
    ("POST", re.compile(r"^/api/registry/[^/]+/oauth/start$")),
    ("POST", re.compile(r"^/api/registry/[^/]+/login/connect$")),
    ("DELETE", re.compile(r"^/api/registry/[^/]+/connections/[^/]+$")),
    ("GET", re.compile(r"^/api/endpoints/[^/]+/settings$")),
]


def _member_may(method: str, path: str) -> bool:
    return any(m == method and rx.match(path) for m, rx in MEMBER_ROUTES)


def _is_member(request: Request) -> bool:
    return getattr(request.state, "role", None) == "member"


def _own_user_id(request: Request) -> str | None:
    return getattr(request.state, "user_id", None)


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
            request.state.user_id = session.get("user_id")
            if session["role"] == "member" and not _member_may(request.method, path):
                return JSONResponse({"error": "admin only: members manage their own tokens and linked accounts"}, status_code=403)
        return await call_next(request)


async def login(request: Request):
    body = await request.json()
    state = policy_store.load()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password", "")
    staff = state["portal_users"].get(email)
    member = policy_store.user_by_email(state, email)
    if staff and staff["password"] == password:
        session = {"email": email, "role": staff["role"], "user_id": None, "name": staff["name"]}
    elif member and member.get("password") and member["password"] == password:
        session = {"email": email, "role": "member", "user_id": member["id"], "name": member["name"]}
    else:
        raise ApiError(401, "Invalid email or password")
    token = "ps_" + secrets.token_urlsafe(24)
    state["sessions"][token] = {**session, "expires_at": time.time() + SESSION_TTL}
    policy_store.save(state)
    return JSONResponse({"token": token, "user": _session_user(state, session)})


def _session_user(state: dict, session: dict) -> dict:
    out = {"email": session["email"], "name": session.get("name") or session["email"], "role": session["role"],
           "user_id": session.get("user_id"), "is_admin": session["role"] != "member"}
    if session.get("user_id"):
        u = state.get("users", {}).get(session["user_id"])
        if u:
            out.update({"name": u["name"], "company": u.get("company"), "groups": u.get("groups", []), "user_role": u.get("role")})
    return out


async def logout(request: Request):
    _, _, token = request.headers.get("authorization", "").partition(" ")
    state = policy_store.load()
    state["sessions"].pop(token.strip(), None)
    policy_store.save(state)
    return JSONResponse({"ok": True})


async def me(request: Request):
    state = policy_store.load()
    _, _, token = request.headers.get("authorization", "").partition(" ")
    session = state["sessions"][token.strip()]
    if session["role"] != "member":
        session = {**session, "name": state["portal_users"].get(request.state.user, {}).get("name", request.state.user)}
    return JSONResponse(_session_user(state, session))


# --- user directory --------------------------------------------------------------
def _user_stats(state: dict, uid: str) -> dict:
    now = time.time()
    tokens = [t for t in state["agent_tokens"].values() if t["sub"] == uid and not t["revoked"] and t["expires_at"] > now]
    linked = sorted(state.get("user_connections", {}).get(uid, {}).keys())
    return {"active_tokens": len(tokens), "linked_backends": linked}


async def list_users(request: Request):
    state = policy_store.load()
    items = [{**policy_store.public_user(u), **_user_stats(state, u["id"])} for u in state["users"].values()]
    return JSONResponse({"items": sorted(items, key=lambda u: u["id"]), "roles": list(policy_store.USER_ROLES)})


def _apply_user_fields(u: dict, body: dict, state: dict) -> None:
    if "name" in body:
        u["name"] = " ".join(str(body["name"]).split())[:80] or u.get("name") or u["id"]
    if "email" in body:
        email = (body["email"] or "").strip().lower()
        other = policy_store.user_by_email(state, email) if email else None
        if other and other["id"] != u["id"]:
            raise ApiError(409, f"{email} already belongs to {other['id']}")
        u["email"] = email
    if "role" in body:
        if body["role"] not in policy_store.USER_ROLES:
            raise ApiError(400, "role must be employee or manager")
        u["role"] = body["role"]
    if "company" in body:
        u["company"] = (body["company"] or "").strip() or policy_store.DEMO_CORP
    if "groups" in body:
        u["groups"] = _listed(body["groups"])
    if "password" in body:
        pw = body["password"] or None
        if pw is not None and len(str(pw)) < 6:
            raise ApiError(400, "password must be at least 6 characters (or empty for no portal sign-in)")
        u["password"] = pw
        if pw and not u.get("email"):
            raise ApiError(400, "a user who signs in needs an email")


async def create_user(request: Request):
    body = await request.json()
    state = policy_store.load()
    uid = re.sub(r"[^a-z0-9_-]", "", (body.get("id") or "").strip().lower())
    if not uid:
        raise ApiError(400, "id is required: letters, digits, - or _ (the Bizplay user id agents call with)")
    if uid in state["users"]:
        raise ApiError(409, f"user {uid} already exists")
    u = {"id": uid, "name": uid, "email": "", "role": "employee", "company": policy_store.DEMO_CORP, "groups": [], "password": None,
         "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _apply_user_fields(u, body, state)
    state["users"][uid] = u
    policy_store.save(state)
    return JSONResponse({**policy_store.public_user(u), **_user_stats(state, uid)}, status_code=201)


async def update_user(request: Request):
    body = await request.json()
    state = policy_store.load()
    u = state["users"].get(request.path_params["uid"])
    if not u:
        raise ApiError(404, "unknown user")
    _apply_user_fields(u, body, state)
    policy_store.save(state)
    return JSONResponse({**policy_store.public_user(u), **_user_stats(state, u["id"])})


async def delete_user(request: Request):
    state = policy_store.load()
    uid = request.path_params["uid"]
    if uid not in state["users"]:
        raise ApiError(404, "unknown user")
    del state["users"][uid]
    # Their tokens stop working and their linked accounts are dropped: nothing may act as them.
    for t in state["agent_tokens"].values():
        if t["sub"] == uid:
            t["revoked"] = True
    state.get("user_connections", {}).pop(uid, None)
    for tok, sess in list(state["sessions"].items()):
        if sess.get("user_id") == uid:
            del state["sessions"][tok]
    policy_store.save(state)
    return JSONResponse({"ok": True})


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
        "oauth_issuer": gateway_oauth.issuer(policy_store.load(), request),
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
         "ok": sec["require_gateway_bearer"] and not any((s or {}).get("require_token") is False for s in state.get("endpoint_settings", {}).values()),
         "detail": "The default for every gateway endpoint; an endpoint may override it on its own page."},
        {"id": "confirm_write", "label": "Write tools require user confirmation",
         "ok": not write_unconfirmed, "detail": "Unconfirmed: " + ", ".join(write_unconfirmed) if write_unconfirmed else "All enabled write tools ask before acting."},
        {"id": "token_ttl", "label": "No agent token lives longer than 90 days",
         "ok": not long_lived, "detail": f"{len(long_lived)} long-lived token(s)" if long_lived else "All tokens expire within 90 days."},
        {"id": "oauth", "label": "MCP clients sign in with OAuth 2.1",
         "ok": True, "detail": "The gateway is its own authorization server (PKCE, dynamic client registration, refresh tokens); "
                               "identities come from the user directory. Production: federate the sign-in page to Bizplay SSO."},
        {"id": "secrets", "label": "Upstream credentials stored in a vault",
         "ok": False, "detail": "Mockup stores credentials in a JSON file. Production: KMS / vault."},
    ]


def _backend_of(state: dict, tool: str) -> str | None:
    """Which backend a logged tool name belongs to: longest prefix wins; unprefixed names are the curated server."""
    if tool.startswith("oauth:"):
        return None
    best = None
    for p in state["providers"].values():
        prefix = p.get("tool_prefix") or ""
        if prefix and tool.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, p["name"])
    if best:
        return best[1]
    curated = state["providers"].get("bizplay")
    return curated["name"] if curated and tool in curated["tools"] else "Other"


def _usage(state: dict, days: int = 14) -> dict:
    """Charts for the overview, from the audit log: per day by outcome, and per backend."""
    entries = audit.tail(5000)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    day_keys = [time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400 * i)) for i in range(days - 1, -1, -1)]
    per_day = {d: {"date": d, "ok": 0, "denied": 0, "error": 0} for d in day_keys}
    per_backend: dict[str, dict] = {}
    for e in entries:
        day = str(e.get("ts", ""))[:10]
        outcome = e.get("outcome") if e.get("outcome") in ("ok", "denied", "error") else "error"
        if day in per_day:
            per_day[day][outcome] += 1
        backend = _backend_of(state, str(e.get("tool", "")))
        if backend and day in per_day:
            row = per_backend.setdefault(backend, {"backend": backend, "calls": 0, "denied": 0, "error": 0})
            row["calls"] += 1
            if outcome != "ok":
                row[outcome] += 1
    ranked = sorted(per_backend.values(), key=lambda r: -r["calls"])
    top, rest = ranked[:6], ranked[6:]
    if rest:
        top.append({"backend": "Other", "calls": sum(r["calls"] for r in rest), "denied": sum(r["denied"] for r in rest),
                    "error": sum(r["error"] for r in rest), "folded": len(rest)})
    return {"days": days, "today": today, "calls_by_day": list(per_day.values()), "calls_by_backend": top,
            "total": sum(v["ok"] + v["denied"] + v["error"] for v in per_day.values())}


async def overview(request: Request):
    state = policy_store.load()
    now = time.time()
    tokens = state["agent_tokens"].values()
    checklist = _security_checklist(state)
    tools_by_backend = sorted(({"backend": p["name"], "id": p["id"], "enabled": sum(t["enabled"] for t in p["tools"].values()),
                                "total": len(p["tools"]), "published": p.get("status") == "published"}
                               for p in state["providers"].values()), key=lambda r: -r["total"])
    return JSONResponse({
        "providers": len(state["providers"]),
        "published": sum(p["status"] == "published" for p in state["providers"].values()),
        "tools_enabled": sum(t["enabled"] for p in state["providers"].values() for t in p["tools"].values()),
        "tokens_active": sum(1 for t in tokens if not t["revoked"] and t["expires_at"] > now),
        "audit_recent": audit.tail(8),
        "checklist": checklist,
        "score": round(100 * sum(c["ok"] for c in checklist) / len(checklist)),
        "usage": _usage(state),
        "tools_by_backend": tools_by_backend,
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
    out["login"] = login_auth.config(p)
    out["login_ready"] = login_auth.ready(p)
    out["per_user"] = p.get("auth_mode") == "oauth" or (p.get("auth_mode") == "login" and out["login"]["per_user"])
    out["connections"] = len(oauth.public_connections(policy_store.load(), p["id"])) if out["per_user"] else 0
    if p.get("auth_mode") == "login" and not out["login"]["per_user"]:
        cred = policy_store.load()["credentials"].get(p.get("upstream_credential_id", ""), {})
        cached = cred.get("cached") or {}
        out["service_account"] = {"username": cred.get("username") or "", "has_password": bool(cred.get("secret")),
                                  "signed_in_at": cached.get("signed_in_at"), "expires_at": cached.get("expires_at")}
    out["has_spec"] = bool(p.get("spec"))
    out["instructions"] = p.get("instructions") or ""
    out["param_sources"] = guidance.sources_for(p)
    out["bound_params"] = {n: v["value"] for n, v in out["param_sources"].items() if v["kind"] == "caller"}
    out["comes_from"] = p.get("comes_from") or {}
    out["standalone_url"] = policy_store.standalone_url(p)
    out["tool_count"] = len(p["tools"])
    out["tools_enabled"] = sum(t["enabled"] for t in p["tools"].values())
    return out


async def list_registry(request: Request):
    state = policy_store.load()
    if _is_member(request):
        items = [_public_provider(p) for p in state["providers"].values() if p.get("status") == "published"]
        return JSONResponse({"items": items})
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


def _login_config(body: dict, existing: dict | None = None) -> dict:
    try:
        return login_auth.parse_config(body, existing)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from None


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


async def _backend_headers_for(state: dict, p: dict, user_id: str | None = None) -> dict[str, str]:
    """Like _backend_headers, but a login-endpoint backend may need a sign-in first."""
    if p.get("auth_mode") == "login":
        try:
            if user_id and login_auth.config(p)["per_user"]:
                token = await login_auth.user_token(state, p, user_id)
            else:
                token = await login_auth.listing_token(state, p)
        except login_auth.LoginError as exc:
            raise ApiError(502, f"sign-in failed: {exc}") from None
        return login_auth.header_for(p, token) if token else {}
    return _backend_headers(state, p, user_id)


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
    login_cfg = _login_config(body.get("login") or {}) if auth_mode == "login" else {}
    login_user = (body.get("login_username") or "").strip()
    login_password = body.get("login_password") or ""
    if kind == "mcp":
        # An MCP server that already exists: its own tool list is the policy table.
        # In OAuth mode nobody has linked an account yet, so the list waits for
        # the first connection (Refresh tools on the provider page).
        if auth_mode == "oauth":
            tools = {}
            base_note = "OAuth backend: connect an account, then Refresh tools to load its tool list."
        elif auth_mode == "login" and (login_cfg.get("per_user") or not (login_user and login_password)):
            tools = {}
            base_note = "Login backend: connect an account, then Refresh tools to load its tool list."
        elif auth_mode == "login":
            draft = {"id": "new", "login": login_cfg}
            try:
                token = (await login_auth.sign_in(draft, login_user, login_password))["access_token"]
            except login_auth.LoginError as exc:
                raise ApiError(400, f"service account sign-in failed: {exc}") from None
            tools = await _tools_from_mcp_server(base_url, login_auth.header_for(draft, token))
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
    if auth_mode == "login":
        state["credentials"][cred_id] = {
            "id": cred_id, "provider_id": pid, "label": f"Gateway -> {name} service account", "type": "login",
            "username": login_user, "secret": login_password, "cached": {}, "created_at": _now_iso(), "rotated_at": None,
        }
    else:
        state["credentials"][cred_id] = {
            "id": cred_id, "provider_id": pid, "label": f"Gateway -> {name} service token", "type": "bearer",
            "secret": service_token, "created_at": _now_iso(), "rotated_at": None,
        }
    state["providers"][pid] = {
        "id": pid, "name": name, "owner": request.state.user, "kind": kind, "base_url": base_url,
        "spec_source": spec_source, "spec": spec,
        "mcp_url": mcp_url, "standalone": False, "oauth": oauth_cfg, "login": login_cfg,
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
        if p.get("kind") == "mcp" and (p.get("auth_mode") not in ("oauth", "login") or oauth.any_token(state, p["id"])
                                       or p.get("auth_mode") == "login"):
            fresh = await _tools_from_mcp_server(p["base_url"], await _backend_headers_for(state, p))
            _merge_tools(p, fresh)
            note = f"Tool list refreshed: {len(fresh)} tool(s)."
    if "oauth" in body and isinstance(body["oauth"], dict):
        p["oauth"] = _oauth_config(body["oauth"], p.get("oauth"))
    if "login" in body and isinstance(body["login"], dict):
        p["login"] = _login_config(body["login"], p.get("login"))
        cred = state["credentials"].get(p["upstream_credential_id"])
        if cred is not None:
            cred["cached"] = {}  # a changed endpoint or field path invalidates whatever token was cached
    if body.get("login_username") or body.get("login_password"):
        cred = state["credentials"][p["upstream_credential_id"]]
        cred.update(type="login", cached={}, rotated_at=_now_iso())
        if body.get("login_username"):
            cred["username"] = body["login_username"].strip()
        if body.get("login_password"):
            cred["secret"] = body["login_password"]
    if "access" in body and isinstance(body["access"], dict):
        p["access"] = _access_config(body["access"])
    if "instructions" in body:
        p["instructions"] = guidance.clean_instructions(body["instructions"])
    if "param_sources" in body:
        p["param_sources"] = guidance.parse_sources(body["param_sources"])
        p.pop("bound_params", None)
    elif "bound_params" in body:  # older callers: caller bindings only
        p["param_sources"] = {n: {"kind": "caller", "value": v} for n, v in guidance.parse_bindings(body["bound_params"]).items()}
        p.pop("bound_params", None)
    if "comes_from" in body:
        p["comes_from"] = guidance.parse_comes_from(body["comes_from"], p)
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
        state["credentials"][p["upstream_credential_id"]].update(type="bearer", secret=body["service_token"].strip(), rotated_at=_now_iso())
    if body.get("auth_mode") == "login" and state["credentials"][p["upstream_credential_id"]].get("type") != "login":
        state["credentials"][p["upstream_credential_id"]].update(type="login", secret="", username="", cached={})
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
    if mode == "login":
        if not login_auth.ready(p):
            raise ApiError(409, "login mode: set the login URL and the token field before publishing")
        cred = state["credentials"].get(p["upstream_credential_id"], {})
        if not login_auth.config(p)["per_user"] and not (cred.get("username") and cred.get("secret")):
            raise ApiError(409, "login mode: set the service account's username and password, or switch to per-user sign-in")


async def set_provider_status(request: Request):
    """publish / unpublish on the shared gateway; deploy / undeploy the standalone endpoint."""
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    action = request.path_params["action"]
    if action not in ("publish", "unpublish", "deploy", "undeploy"):
        raise ApiError(400, "action must be publish, unpublish, deploy or undeploy")
    if action in ("publish", "deploy"):
        _publish_gate(state, p)
    if action == "deploy" and p.get("kind") == "mcp":
        raise ApiError(409, "this backend is already an MCP server; put it in a named gateway instead")
    if action == "deploy" and not p.get("spec"):
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
    if p.get("auth_mode") == "login":
        results.append({"check": "Login endpoint configured", "path": login_auth.config(p).get("url", ""), "status": None,
                        "ok": login_auth.ready(p), "note": "login URL and token field set" if login_auth.ready(p)
                        else "incomplete: fill the fields under Edit connection"})
        if not login_auth.ready(p):
            return results
        try:
            if not await login_auth.listing_token(state, p):
                results.append({"check": "A signed-in account to test with", "path": "Connect account", "status": None, "ok": False,
                                "error": "no service account and no connected user, so the server cannot be called"})
                return results
        except login_auth.LoginError as exc:
            results.append({"check": "Sign-in", "path": login_auth.config(p)["url"], "status": None, "ok": False, "error": str(exc)[:160]})
            return results
    try:
        async with mcp_client(p["base_url"], await _backend_headers_for(state, p)) as c:  # entering = initialize handshake
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
        elif mode == "login":
            results.append({"check": "Protected endpoint rejects missing token", **anon, "ok": anon["status"] in (401, 403)})
            cfg = login_auth.config(p)
            results.append({"check": "Login endpoint configured", "path": cfg.get("url", ""), "status": None, "ok": login_auth.ready(p),
                            "note": ("per-user sign-in: each caller's own credentials are used" if cfg["per_user"] else "service account shared by every caller")
                            if login_auth.ready(p) else "incomplete: fill the fields under Edit connection"})
            if login_auth.ready(p):
                try:
                    token = await login_auth.listing_token(state, p)
                    if token:
                        r = await client.get(probe_path, headers=login_auth.header_for(p, token))
                        results.append({"check": "Protected endpoint accepts the sign-in token", "path": probe_path,
                                        "status": r.status_code, "ok": r.status_code in (200, 404)})
                    else:
                        results.append({"check": "Sign-in", "path": cfg["url"], "status": None, "ok": False,
                                        "error": "no service account and no connected user yet"})
                except (login_auth.LoginError, httpx.HTTPError) as exc:
                    results.append({"check": "Sign-in", "path": cfg["url"], "status": None, "ok": False, "error": str(exc)[:160]})
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


def _link_user(request: Request, state: dict, body: dict) -> str:
    """Whose account is being linked: a member's own, or the id an admin picked (added to the directory if new)."""
    user_id = _own_user_id(request) if _is_member(request) else (body.get("user_id") or "").strip()
    if not user_id:
        raise ApiError(400, "user_id is required: the Bizplay user whose account is being linked")
    if user_id not in state["users"]:
        # An admin linking an account for someone new: put them in the directory as they go.
        user_id = re.sub(r"[^a-z0-9_-]", "", user_id.lower())
        if not user_id:
            raise ApiError(400, "user id: letters, digits, - or _")
        u = {"id": user_id, "name": user_id, "email": "", "role": "employee", "company": policy_store.DEMO_CORP, "groups": [],
             "password": None, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _apply_user_fields(u, {k: body[k] for k in ("name", "role", "company", "groups") if k in body}, state)
        state["users"][user_id] = u
    return user_id


async def oauth_start(request: Request):
    """Begin linking one user's account: returns the URL to open."""
    body = await request.json()
    state = policy_store.load()
    user_id = _link_user(request, state, body)
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
            fresh = await _tools_from_mcp_server(provider["base_url"], await _backend_headers_for(state, provider, pending["user_id"]))
            _merge_tools(provider, fresh)
            loaded = f"&tools={len(fresh)}"
        except ApiError:
            pass  # the page offers Refresh tools; the link itself succeeded
    policy_store.save(state)
    audit.record(pending["user_id"], f"oauth:{provider['id']}", {}, "ok", "account linked", via="portal")
    return RedirectResponse(f"/#provider?p={provider['id']}&connected={pending['user_id']}{loaded}", status_code=303)


def _named(state: dict, rows: list[dict]) -> list[dict]:
    """Add the directory name to rows that carry a user id (tokens use `sub`, connections `user_id`)."""
    users = state.get("users", {})
    for r in rows:
        uid = r.get("user_id") or r.get("sub")
        r["user_name"] = users.get(uid, {}).get("name") or uid
    return rows


async def login_connect(request: Request):
    """Store a user's own username and password for a login-endpoint backend, after a real sign-in."""
    body = await request.json()
    state = policy_store.load()
    user_id = _link_user(request, state, body)
    p = _get_provider(state, request.path_params["pid"])
    if p.get("auth_mode") != "login" or not login_auth.config(p)["per_user"]:
        raise ApiError(409, "this backend does not take per-user sign-ins")
    username, password = (body.get("username") or "").strip(), body.get("password") or ""
    if not username or not password:
        raise ApiError(400, "username and password are required")
    try:
        await login_auth.connect_user(state, p, user_id, username, password)
    except login_auth.LoginError as exc:
        raise ApiError(400, str(exc)) from None
    loaded = ""
    if p.get("kind") == "mcp" and not p.get("tools"):
        try:
            fresh = await _tools_from_mcp_server(p["base_url"], await _backend_headers_for(state, p, user_id))
            _merge_tools(p, fresh)
            loaded = f"; {len(fresh)} tools loaded from the server"
        except ApiError:
            pass
    policy_store.save(state)
    audit.record(user_id, f"login:{p['id']}", {}, "ok", "account connected", via="portal")
    row = next(c for c in _named(state, oauth.public_connections(state, p["id"])) if c["user_id"] == user_id)
    return JSONResponse({**row, "note": f"Signed in to {p['name']} as {username}{loaded}"}, status_code=201)


async def list_connections(request: Request):
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    items = _named(state, oauth.public_connections(state, p["id"]))
    if _is_member(request):
        items = [c for c in items if c["user_id"] == _own_user_id(request)]
    return JSONResponse({"provider": p["id"], "items": items, "now": time.time()})


async def delete_connection(request: Request):
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    if _is_member(request) and request.path_params["user_id"] != _own_user_id(request):
        raise ApiError(403, "you can only disconnect your own account")
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
    headers = await _backend_headers_for(state, p, (body.get("user_id") or "").strip() or None)
    if p.get("auth_mode") in ("oauth", "login") and not headers:
        raise ApiError(409, "connect an account first: the server needs a user's token to list its tools")
    fresh = await _tools_from_mcp_server(p["base_url"], headers)
    _merge_tools(p, fresh)
    policy_store.save(state)
    return JSONResponse({**_public_provider(p), "note": f"Tool list refreshed: {len(fresh)} tool(s)."})


# --- named gateways: a chosen set of backends on their own URL ---------------------
def _public_gateway(state: dict, g: dict, request: Request) -> dict:
    providers = [state["providers"][pid] for pid in g.get("providers", []) if pid in state["providers"]]
    # Same base as the register prefill: the public endpoint if set, else the address the browser used.
    policy = policy_store.endpoint_policy(state, g["id"])
    return {**g, "url": _default_endpoint(state, request).rstrip("/") + "/" + g["id"],
            "access": policy["access"], "require_token": policy["require_token"],
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


# --- per-endpoint settings: token requirement and who may use the endpoint ---------
def _endpoint_key(request: Request) -> str:
    key = request.path_params["key"]
    return "" if key == "_shared" else key


def _endpoint_public(state: dict, key: str) -> dict:
    own = state["endpoint_settings"].get(key) or {}
    return {"key": key or "_shared", "require_token": own.get("require_token"), "instructions": own.get("instructions") or "",
            "param_sources": own.get("param_sources") or {}, "workflows": own.get("workflows") or [],
            **policy_store.endpoint_policy(state, key)}


async def get_endpoint_settings(request: Request):
    state = policy_store.load()
    key = _endpoint_key(request)
    if key and key not in state["gateways"] and not (state["providers"].get(key) or {}).get("standalone"):
        raise ApiError(404, "no such endpoint")
    return JSONResponse(_endpoint_public(state, key))


async def put_endpoint_settings(request: Request):
    body = await request.json()
    state = policy_store.load()
    key = _endpoint_key(request)
    if key and key not in state["gateways"] and not (state["providers"].get(key) or {}).get("standalone"):
        raise ApiError(404, "no such endpoint")
    own = dict(state["endpoint_settings"].get(key) or {})
    if "require_token" in body:
        own["require_token"] = None if body["require_token"] in (None, "", "inherit") else bool(body["require_token"])
    if "access" in body and isinstance(body["access"], dict):
        own["access"] = _access_config(body["access"])
    if "instructions" in body:
        own["instructions"] = guidance.clean_instructions(body["instructions"])
    if "param_sources" in body and isinstance(body["param_sources"], dict):
        # {backend id: {param: {kind, value} | null}}; null clears the backend's own source for this gateway.
        overrides: dict[str, dict] = {}
        for pid, per in body["param_sources"].items():
            if pid not in state["providers"] or not isinstance(per, dict):
                continue
            parsed = guidance.parse_sources({n: v for n, v in per.items() if v is not None})
            cleared = {n: None for n, v in per.items() if v is None}
            if parsed or cleared:
                overrides[pid] = {**cleared, **parsed}
        own["param_sources"] = overrides
    if "workflows" in body and isinstance(body["workflows"], list):
        flows, names = [], set()
        for spec in body["workflows"]:
            try:
                wf = guidance.parse_workflow(spec if isinstance(spec, dict) else {})
            except ValueError as exc:
                raise ApiError(400, str(exc)) from None
            if wf["name"] in names:
                raise ApiError(400, f"two workflows are named {wf['name']}")
            names.add(wf["name"])
            flows.append(wf)
        own["workflows"] = flows
    state["endpoint_settings"][key] = own
    policy_store.save(state)
    return JSONResponse(_endpoint_public(state, key))


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
    if "alias" in body:
        alias = str(body["alias"] or "").strip()
        if alias and alias != name:
            problem = guidance.alias_problem(p, name, alias)
            if problem:
                raise ApiError(400, problem)
            tool["alias"] = alias
        else:
            tool.pop("alias", None)
    policy_store.save(state)
    return JSONResponse({"name": name, **tool})


async def provider_params(request: Request):
    """The parameter names this backend's tools take, with how many tools use each and what it is bound to."""
    state = policy_store.load()
    p = _get_provider(state, request.path_params["pid"])
    if p.get("spec") and any("params" not in row for row in p["tools"].values()):
        if specs.reconcile_tool_names(p):  # older rows: read the parameter names off the spec once
            policy_store.save(state)
    counts: dict[str, int] = {}
    for row in p["tools"].values():
        for name in row.get("params") or []:
            counts[name] = counts.get(name, 0) + 1
    sources = guidance.sources_for(p)
    items = [{"name": n, "tools": c, "source": sources.get(n), "bound": (sources.get(n) or {}).get("value") if (sources.get(n) or {}).get("kind") == "caller" else None,
              "suggested": guidance.suggested_source(n)} for n, c in counts.items()]
    items.sort(key=lambda i: (i["source"] is None, i["suggested"] is None, -i["tools"], i["name"]))
    # Origins: confirmed rows, plus what real calls showed (a value returned by one tool used by another).
    confirmed = p.get("comes_from") or {}
    learned = p.get("learned") or {}
    origins = []
    for tool, row in p["tools"].items():
        for param in row.get("params") or []:
            key = f"{tool}.{param}"
            seen = sorted(learned.get(key, {}).items(), key=lambda kv: -kv[1])
            if key in confirmed or seen:
                origins.append({"tool": tool, "param": param, "confirmed": confirmed.get(key),
                                "seen": [{"origin": o, "count": c} for o, c in seen[:3]]})
    origins.sort(key=lambda o: (o["confirmed"] is None, -(o["seen"][0]["count"] if o["seen"] else 0), o["tool"], o["param"]))
    return JSONResponse({"items": items, "sources": guidance.CALLER_SOURCES, "kinds": list(guidance.KINDS), "origins": origins,
                         "tools": [{"name": n, "alias": r.get("alias") or "", "params": r.get("params") or []} for n, r in p["tools"].items()],
                         "unknown": sorted(set(sources) - set(counts)), "needs_refresh": p.get("kind") == "mcp" and not counts})


async def endpoint_instructions(request: Request):
    """What a model is told when it connects to this endpoint, optionally as one directory user."""
    state = policy_store.load()
    key = "" if request.path_params["key"] == "_shared" else request.path_params["key"]
    if key and key not in state["gateways"] and not state["providers"].get(key, {}).get("standalone"):
        raise ApiError(404, "unknown endpoint")
    user = state["users"].get(request.query_params.get("as") or "")
    claims = {"company": user.get("company"), "role": user.get("role"), "groups": user.get("groups", [])} if user else None
    text = guidance.compose_instructions(state, key, user["id"] if user else "", claims, "bearer" if user else "env")
    return JSONResponse({"key": key, "as": user["id"] if user else None, "text": text,
                         "backends": [{"id": b["id"], "name": b["name"], "has_notes": bool(b.get("instructions")),
                                       "bound": {n: v for n, v in guidance.sources_for(b, state, key).items()},
                                       "tools": [{"name": n, "alias": r.get("alias") or "", "params": r.get("params") or [], "enabled": r["enabled"],
                                                  "prefix": (b.get("tool_prefix") or "") if key in state["gateways"] or not key else ""}
                                                 for n, r in b["tools"].items()]}
                                      for b in guidance.backends_for(state, key)]})


# --- agent tokens ---------------------------------------------------------------
async def list_tokens(request: Request):
    state = policy_store.load()
    items = sorted((policy_store.public_token(t) for t in state["agent_tokens"].values()),
                   key=lambda t: t["created_at"], reverse=True)
    if _is_member(request):
        items = [t for t in items if t["sub"] == _own_user_id(request)]
    return JSONResponse({"items": _named(state, items), "now": time.time()})


async def issue_token(request: Request):
    """Issue a token for a directory user. Role, company and groups come from the directory.

    An admin may still pass them explicitly (the API used to require that); then the
    directory entry is updated to match, or created for an id not seen before, so the
    directory stays the one place that says who a user is. Members issue only for themselves.
    """
    body = await request.json()
    state = policy_store.load()
    user_id = _own_user_id(request) if _is_member(request) else (body.get("user_id") or "").strip()
    if not user_id:
        raise ApiError(400, "user_id is required")
    ttl = int(body.get("ttl_days") or state["security"]["token_ttl_days"])
    if not 1 <= ttl <= 365:
        raise ApiError(400, "ttl_days must be between 1 and 365")
    user = state["users"].get(user_id)
    explicit = {k: body[k] for k in ("role", "company", "groups") if k in body and not _is_member(request)}
    if user is None:
        if "role" not in explicit:
            raise ApiError(400, f"unknown user '{user_id}': pick 'Someone not listed' to add them, or add them on the Users page")
        user_id = re.sub(r"[^a-z0-9_-]", "", user_id.lower())
        if not user_id:
            raise ApiError(400, "user id: letters, digits, - or _")
        user = {"id": user_id, "name": (body.get("name") or "").strip() or user_id, "email": "", "role": "employee", "company": policy_store.DEMO_CORP,
                "groups": [], "password": None, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        state["users"][user_id] = user
    if explicit:
        _apply_user_fields(user, explicit, state)
    token, record = policy_store.issue_agent_token(
        state, label=(body.get("label") or "Untitled").strip(), user_id=user_id,
        role=user["role"], company=user.get("company") or policy_store.DEMO_CORP,
        agent=body.get("agent") or "MCP client", ttl_days=ttl, created_by=request.state.user, groups=user.get("groups", []),
    )
    policy_store.save(state)
    return JSONResponse({"token": token, "record": _named(state, [policy_store.public_token(record)])[0]}, status_code=201)


async def revoke_token(request: Request):
    state = policy_store.load()
    record = state["agent_tokens"].get(request.path_params["tid"])
    if not record:
        raise ApiError(404, "unknown token")
    if _is_member(request) and record["sub"] != _own_user_id(request):
        raise ApiError(403, "you can only revoke your own tokens")
    record["revoked"] = True
    policy_store.save(state)
    return JSONResponse(policy_store.public_token(record))


# --- security -------------------------------------------------------------------
async def auth_log(request: Request):
    """Newest first: what MCP clients did at the sign-in endpoints and why the gateway refused calls."""
    state = policy_store.load()
    items = list(reversed(state.get("auth_log", [])))
    clients = [{k: v for k, v in c.items()} for c in state.get("oauth_clients", {}).values()]
    return JSONResponse({"items": items, "clients": sorted(clients, key=lambda c: -c.get("client_id_issued_at", 0))})


async def security(request: Request):
    state = policy_store.load()
    creds = [{**{k: v for k, v in c.items() if k != "cached"}, "secret": _mask(c["secret"]) if c["secret"] else "(not set)"}
             for c in state["credentials"].values()]
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


def wants_html(request: Request) -> bool:
    """Browsers say text/html; agents and scripts say json or event-stream (or nothing)."""
    accept = request.headers.get("accept", "")
    return "text/html" in accept and not request.url.path.startswith("/api/")


ERROR_COPY = {
    404: ("Page not found", "There is nothing at this address. The portal lives at the root, and MCP endpoints are under /mcp."),
    405: ("Method not allowed", "This address exists, but not for that HTTP method."),
    500: ("Something went wrong", "The portal hit an error it did not expect. It has been logged; try again, and tell the admin if it keeps happening."),
    502: ("Backend did not answer", "An upstream service the portal depends on is unreachable right now."),
}


def error_html(status: int, title: str | None = None, detail: str | None = None, path: str = "") -> str:
    """A small self-contained page in the portal's own language, for browsers only."""
    t, d = ERROR_COPY.get(status, ("Error", ""))
    title, detail = title or t, detail or d
    safe = lambda v: str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{status} · Bizplay MCP Portal</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
  :root {{ --canvas:#f4f6fa; --surface:#fff; --line:#e4e8ef; --ink:#1c2433; --ink-2:#4a5568; --ink-3:#66727f; --primary:#2f6bff; --primary-hover:#245be0; --primary-soft:#eaf0ff; --primary-ink:#1f4fc4; --mono: "Geist Mono", ui-monospace, Consolas, monospace; }}
  * {{ box-sizing:border-box }} body {{ margin:0; min-height:100dvh; display:grid; place-items:center; padding:24px; background:var(--canvas); color:var(--ink); font:14px/1.5 "Pretendard","Segoe UI",system-ui,sans-serif; -webkit-font-smoothing:antialiased }}
  .card {{ width:min(520px,100%); background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:32px; box-shadow:0 1px 2px rgb(28 36 51/.05),0 4px 16px rgb(28 36 51/.06) }}
  .brand {{ display:flex; align-items:center; gap:10px; margin-bottom:22px; font-weight:800; font-size:18px; letter-spacing:-.02em }}
  .mark {{ width:30px; height:30px; border-radius:8px; background:var(--primary); color:#fff; display:grid; place-items:center; font-size:15px }}
  .code {{ font-size:56px; font-weight:800; letter-spacing:-.03em; color:var(--primary); line-height:1; margin:0 0 8px }}
  h1 {{ font-size:20px; margin:0 0 6px }} p {{ margin:0 0 10px; color:var(--ink-2) }}
  .path {{ display:inline-block; margin:6px 0 18px; padding:4px 10px; border-radius:6px; background:var(--primary-soft); color:var(--primary-ink); font-family:var(--mono); font-size:12px; word-break:break-all }}
  .btn {{ display:inline-flex; align-items:center; gap:6px; height:36px; padding:0 14px; border-radius:8px; border:1px solid #cfd6e0; background:#fff; color:var(--ink); font:inherit; font-weight:500; text-decoration:none; cursor:pointer }}
  .btn.solid {{ background:var(--primary); border-color:var(--primary); color:#fff }} .btn.solid:hover {{ background:var(--primary-hover) }} .btn + .btn {{ margin-left:8px }}
  .hint {{ margin-top:18px; color:var(--ink-3); font-size:12px }}
</style></head><body>
<main class="card">
  <div class="brand"><span class="mark">&#9679;</span> bizplay <span style="font-weight:500;color:var(--ink-3)">MCP Portal</span></div>
  <p class="code">{status}</p>
  <h1>{safe(title)}</h1>
  <p>{safe(detail)}</p>
  {f'<span class="path">{safe(path)}</span><br>' if path else ''}
  <a class="btn solid" href="/">Open the portal</a><a class="btn" href="javascript:history.back()">Go back</a>
  <p class="hint">Agents connect to <span style="font-family:var(--mono)">/mcp</span>, not to this page. If you followed a link from the portal, the item may have been deleted.</p>
</main></body></html>"""


async def http_error(request: Request, exc: HTTPException):
    if wants_html(request):
        return HTMLResponse(error_html(exc.status_code, path=request.url.path), status_code=exc.status_code)
    return JSONResponse({"error": exc.detail or ERROR_COPY.get(exc.status_code, ("Error", ""))[0]}, status_code=exc.status_code)


async def server_error(request: Request, exc: Exception):
    if wants_html(request):
        return HTMLResponse(error_html(500, path=request.url.path), status_code=500)
    return JSONResponse({"error": "internal error; see the portal log"}, status_code=500)


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
        Route("/api/registry/{pid}/params", provider_params),
        Route("/api/registry/{pid}/tools", list_tools),
        Route("/api/registry/{pid}/tools/{name}", update_tool, methods=["PUT"]),
        Route("/api/registry/{pid}/oauth/discover", oauth_discover, methods=["POST"]),
        Route("/api/registry/{pid}/oauth/start", oauth_start, methods=["POST"]),
        Route("/api/registry/{pid}/login/connect", login_connect, methods=["POST"]),
        Route("/api/registry/{pid}/connections", list_connections),
        Route("/api/registry/{pid}/connections/{user_id}", delete_connection, methods=["DELETE"]),
        Route("/api/registry/{pid}/refresh-tools", refresh_tools, methods=["POST"]),
        Route("/api/registry/{pid}/{action}", set_provider_status, methods=["POST"]),
        Route("/oauth/callback", oauth_callback),
        Route("/api/groups", list_groups),
        Route("/api/endpoints/{key}/instructions", endpoint_instructions),
        Route("/api/endpoints/{key}/settings", get_endpoint_settings),
        Route("/api/endpoints/{key}/settings", put_endpoint_settings, methods=["PUT"]),
        Route("/api/gateways", list_gateways),
        Route("/api/gateways", create_gateway, methods=["POST"]),
        Route("/api/gateways/{gid}", update_gateway, methods=["PATCH"]),
        Route("/api/gateways/{gid}", delete_gateway, methods=["DELETE"]),
        Route("/api/users", list_users),
        Route("/api/users", create_user, methods=["POST"]),
        Route("/api/users/{uid}", update_user, methods=["PATCH"]),
        Route("/api/users/{uid}", delete_user, methods=["DELETE"]),
        Route("/api/tokens", list_tokens),
        Route("/api/tokens", issue_token, methods=["POST"]),
        Route("/api/tokens/{tid}/revoke", revoke_token, methods=["POST"]),
        Route("/api/security", security),
        Route("/api/auth-log", auth_log),
        Route("/api/security", update_security, methods=["PUT"]),
        Route("/api/credentials/{cid}/rotate", rotate_credential, methods=["POST"]),
        Route("/api/audit", audit_log),
        *gateway_oauth.routes,
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ],
    exception_handlers={ApiError: api_error, HTTPException: http_error, 500: server_error},
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
