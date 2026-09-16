"""The gateway as an OAuth 2.1 authorization server: MCP clients sign in instead of pasting a token.

claude.ai and ChatGPT connectors cannot send a static bearer header; they only
know "no auth" or OAuth against the server itself, discovered the way the MCP
authorization spec says:

    401 from /mcp/<key>  ->  WWW-Authenticate: Bearer resource_metadata="<origin>/.well-known/oauth-protected-resource/mcp/<key>"
    that document        ->  authorization_servers: [<origin>]
    <origin>/.well-known/oauth-authorization-server  ->  /authorize, /token, /register
    /register            ->  the client registers itself (RFC 7591), no admin work
    /authorize           ->  the portal's own sign-in page, employee accounts from the user directory
    /token               ->  authorization code + PKCE, refresh tokens

The access token it issues *is* an agent token bound to that person (role,
company, groups), so entitlement, tool policy, company scoping, per-user
backend links and the audit log all apply unchanged. It shows on the Agent
Tokens page and can be revoked there. Access tokens last an hour and are
renewed with the refresh token, which lasts the portal's token lifetime.
"""

from __future__ import annotations

import base64
import hashlib
import html
import secrets
import time
from urllib.parse import urlencode, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from bizplay_mcp import audit, policy_store

CODE_TTL = 600            # seconds an authorization code stays valid
ACCESS_TTL = 3600         # seconds an access token lasts; the refresh token lasts security.token_ttl_days
SCOPE = "mcp"
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, MCP-Protocol-Version"}


# --- where we are ----------------------------------------------------------------------
def request_origin(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    return f"{scheme}://{host}"


def issuer(state: dict, request: Request) -> str:
    """The public address set on the Security page wins; otherwise the address the client used."""
    base = (state["security"].get("public_mcp_url") or "").strip()
    if base:
        parts = urlsplit(base)
        return f"{parts.scheme}://{parts.netloc}"
    return request_origin(request)


def metadata_doc(iss: str) -> dict:
    return {
        "issuer": iss,
        "authorization_endpoint": f"{iss}/authorize",
        "token_endpoint": f"{iss}/token",
        "registration_endpoint": f"{iss}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "scopes_supported": [SCOPE],
        "service_documentation": f"{iss}/",
    }


def _json(body: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={**CORS, "Cache-Control": "no-store"})


async def preflight(request: Request) -> Response:
    return Response(status_code=204, headers=CORS)


async def as_metadata(request: Request) -> Response:
    return _json(metadata_doc(issuer(policy_store.load(), request)))


async def resource_metadata(request: Request) -> Response:
    """RFC 9728: which authorization server protects /mcp or /mcp/<key>."""
    state = policy_store.load()
    key = (request.path_params.get("key") or "").strip("/")
    if key and key not in state["gateways"] and not (state["providers"].get(key, {}).get("standalone")):
        return _json({"error": f"nothing is served at /mcp/{key}"}, 404)
    iss = issuer(state, request)
    return _json({"resource": f"{iss}/mcp" + (f"/{key}" if key else ""), "authorization_servers": [iss],
                  "scopes_supported": [SCOPE], "bearer_methods_supported": ["header"],
                  "resource_name": state["gateways"].get(key, {}).get("name") or state["providers"].get(key, {}).get("name") or "Bizplay MCP gateway"})


# --- dynamic client registration ----------------------------------------------------
def _valid_redirect(uri: str) -> bool:
    parts = urlsplit(uri)
    if parts.scheme == "https" and parts.netloc:
        return True
    return parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")


async def register(request: Request) -> Response:
    try:
        body = await request.json()
    except ValueError:
        return _json({"error": "invalid_client_metadata", "error_description": "JSON body expected"}, 400)
    uris = body.get("redirect_uris") or []
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) and _valid_redirect(u) for u in uris):
        return _json({"error": "invalid_redirect_uri", "error_description": "redirect_uris must be https URLs (or http://localhost)"}, 400)
    state = policy_store.load()
    client = {
        "client_id": "mcpc_" + secrets.token_urlsafe(12),
        "client_name": " ".join(str(body.get("client_name") or "MCP client").split())[:80],
        "redirect_uris": uris,
        "client_uri": str(body.get("client_uri") or "")[:200],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": SCOPE,
        "client_id_issued_at": int(time.time()),
    }
    state.setdefault("oauth_clients", {})[client["client_id"]] = client
    policy_store.save(state)
    return _json(client, 201)


# --- authorize: the portal's sign-in page ----------------------------------------------
PAGE_CSS = """
  :root { --canvas:#f4f6fa; --surface:#fff; --line:#e4e8ef; --ink:#1c2433; --ink-2:#4a5568; --ink-3:#66727f; --primary:#2f6bff; --primary-hover:#245be0; --primary-soft:#eaf0ff; --primary-ink:#1f4fc4; --red:#c62828; --mono:"Geist Mono",ui-monospace,Consolas,monospace }
  * { box-sizing:border-box } body { margin:0; min-height:100dvh; display:grid; place-items:center; padding:24px; background:var(--canvas); color:var(--ink); font:14px/1.5 "Pretendard","Segoe UI",system-ui,sans-serif; -webkit-font-smoothing:antialiased }
  .card { width:min(440px,100%); background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:32px; box-shadow:0 1px 2px rgb(28 36 51/.05),0 4px 16px rgb(28 36 51/.06); display:grid; gap:14px }
  .brand { display:flex; align-items:center; gap:10px; font-weight:800; font-size:18px; letter-spacing:-.02em }
  .mark { width:30px; height:30px; border-radius:8px; background:var(--primary); color:#fff; display:grid; place-items:center; font-size:15px }
  h1 { font-size:20px; margin:0 } p { margin:0; color:var(--ink-2) }
  .ask { padding:12px 14px; border-radius:8px; background:var(--primary-soft); color:var(--primary-ink); font-size:13px } .ask strong { font-weight:650 }
  .ask .res { font-family:var(--mono); font-size:12px; word-break:break-all; display:block; margin-top:4px }
  label { display:grid; gap:6px; font-size:12.5px; font-weight:600; color:var(--ink-2) }
  input { height:38px; padding:0 12px; border:1px solid #cfd6e0; border-radius:8px; font:inherit; color:var(--ink) } input:focus { outline:2px solid var(--primary); outline-offset:1px; border-color:var(--primary) }
  .btn { height:38px; padding:0 16px; border-radius:8px; border:1px solid var(--primary); background:var(--primary); color:#fff; font:inherit; font-weight:600; cursor:pointer } .btn:hover { background:var(--primary-hover) }
  .btn.ghost { background:#fff; color:var(--ink); border-color:#cfd6e0 }
  .row { display:flex; gap:8px; justify-content:flex-end }
  .err { color:var(--red); font-size:13px; margin:0 } .hint { color:var(--ink-3); font-size:12px; margin:0 }
"""


def page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Bizplay MCP Portal</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>{PAGE_CSS}</style></head><body><main class="card">
<div class="brand"><span class="mark">&#9679;</span> bizplay <span style="font-weight:500;color:var(--ink-3)">MCP Portal</span></div>
{body}</main></body></html>"""


def _resource_label(state: dict, resource: str) -> str:
    key = resource.rstrip("/").rsplit("/mcp", 1)[-1].strip("/") if "/mcp" in resource else ""
    if not key:
        return "the shared gateway (every backend you are entitled to)"
    g = state["gateways"].get(key)
    if g:
        return f"the {g['name']} gateway"
    p = state["providers"].get(key)
    return f"{p['name']} (its own MCP server)" if p else f"/mcp/{key}"


AUTH_PARAMS = ("response_type", "client_id", "redirect_uri", "state", "code_challenge", "code_challenge_method", "scope", "resource")


def _authorize_request(state: dict, params) -> tuple[dict | None, dict, str | None]:
    """Validate an authorization request. Returns (client, params, error) where error blocks any redirect."""
    q = {k: (params.get(k) or "").strip() for k in AUTH_PARAMS}
    client = state.get("oauth_clients", {}).get(q["client_id"])
    if not client:
        return None, q, "Unknown client. The app that sent you here has not registered with this portal."
    if not q["redirect_uri"]:
        q["redirect_uri"] = client["redirect_uris"][0] if len(client["redirect_uris"]) == 1 else ""
    if q["redirect_uri"] not in client["redirect_uris"]:
        return client, q, "The app asked to be sent back to an address it did not register."
    return client, q, None


def _authorize_page(state: dict, client: dict, q: dict, error: str = "", email: str = "") -> str:
    hidden = "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in q.items())
    return page("Sign in", f"""
<h1>Sign in to continue</h1>
<div class="ask"><strong>{html.escape(client['client_name'])}</strong> wants to use {html.escape(_resource_label(state, q['resource']))} as you.
<span class="res">{html.escape(q['resource'] or 'Bizplay MCP gateway')}</span></div>
<form method="post" action="/authorize" style="display:grid;gap:12px">{hidden}
<label>Email <input name="email" type="email" value="{html.escape(email)}" autocomplete="username" required autofocus></label>
<label>Password <input name="password" type="password" autocomplete="current-password" required></label>
{f'<p class="err">{html.escape(error)}</p>' if error else ''}
<div class="row"><button class="btn ghost" type="submit" name="decision" value="deny" formnovalidate>Cancel</button><button class="btn" type="submit" name="decision" value="allow">Sign in and allow</button></div>
</form>
<p class="hint">Use your employee account. Every call the app makes will be made as you, limited to your company and groups, and recorded in the audit log. You can revoke this access on the portal's Agent Tokens page.</p>""")


def _redirect_error(q: dict, error: str, description: str) -> Response:
    sep = "&" if "?" in q["redirect_uri"] else "?"
    params = {"error": error, "error_description": description}
    if q.get("state"):
        params["state"] = q["state"]
    return RedirectResponse(f"{q['redirect_uri']}{sep}{urlencode(params)}", status_code=303)


async def authorize_get(request: Request) -> Response:
    state = policy_store.load()
    client, q, error = _authorize_request(state, request.query_params)
    if error:
        return HTMLResponse(page("Cannot continue", f"<h1>Cannot continue</h1><p>{html.escape(error)}</p>"), status_code=400)
    if q["response_type"] != "code":
        return _redirect_error(q, "unsupported_response_type", "only response_type=code is supported")
    if not q["code_challenge"] or q["code_challenge_method"] not in ("", "S256"):
        return _redirect_error(q, "invalid_request", "PKCE with S256 is required")
    return HTMLResponse(_authorize_page(state, client, q))


async def authorize_post(request: Request) -> Response:
    form = await request.form()
    state = policy_store.load()
    client, q, error = _authorize_request(state, form)
    if error:
        return HTMLResponse(page("Cannot continue", f"<h1>Cannot continue</h1><p>{html.escape(error)}</p>"), status_code=400)
    if form.get("decision") == "deny":
        return _redirect_error(q, "access_denied", "the user cancelled the sign-in")
    email, password = (form.get("email") or "").strip().lower(), form.get("password") or ""
    user = policy_store.user_by_email(state, email)
    if not user or not user.get("password") or user["password"] != password:
        if email in state["portal_users"] and state["portal_users"][email]["password"] == password:
            msg = "That is a portal admin account. Sign in with an employee account: agents act as a person with a role and company."
        else:
            msg = "Invalid email or password."
        return HTMLResponse(_authorize_page(state, client, q, msg, email), status_code=401)
    code = "ac_" + secrets.token_urlsafe(32)
    state.setdefault("auth_codes", {})[code] = {
        "client_id": client["client_id"], "user_id": user["id"], "redirect_uri": q["redirect_uri"],
        "code_challenge": q["code_challenge"], "resource": q["resource"], "scope": q["scope"] or SCOPE,
        "expires_at": time.time() + CODE_TTL,
    }
    # Codes from earlier attempts that were never redeemed expire on their own; drop the stale ones now.
    for c, rec in list(state["auth_codes"].items()):
        if rec["expires_at"] < time.time():
            del state["auth_codes"][c]
    policy_store.save(state)
    audit.record(user["id"], f"oauth:{client['client_name']}", {}, "ok", "signed in to an MCP client", via="portal")
    sep = "&" if "?" in q["redirect_uri"] else "?"
    params = {"code": code}
    if q.get("state"):
        params["state"] = q["state"]
    return RedirectResponse(f"{q['redirect_uri']}{sep}{urlencode(params)}", status_code=303)


# --- token ---------------------------------------------------------------------------------
def _pkce_ok(verifier: str, challenge: str) -> bool:
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return secrets.compare_digest(digest, challenge)


def issue_tokens(state: dict, client: dict, user_id: str, resource: str, scope: str = SCOPE) -> dict:
    """An agent token for this person, short-lived, with a refresh token that lasts the portal's token lifetime."""
    user = state["users"].get(user_id)
    if not user:
        raise KeyError(user_id)
    ttl_days = int(state["security"].get("token_ttl_days") or 30)
    token, record = policy_store.issue_agent_token(
        state, label=f"{client['client_name']} sign-in", user_id=user_id, role=user["role"],
        company=user.get("company") or policy_store.DEMO_CORP, agent=client["client_name"], ttl_days=ttl_days,
        created_by=f"oauth:{client['client_id']}", groups=user.get("groups", []),
    )
    now = time.time()
    record.update({"expires_at": now + ACCESS_TTL, "refresh_token": "rt_" + secrets.token_urlsafe(32),
                   "refresh_expires_at": now + ttl_days * 86400, "client_id": client["client_id"], "resource": resource, "via": "oauth"})
    return {"access_token": token, "token_type": "Bearer", "expires_in": ACCESS_TTL, "refresh_token": record["refresh_token"], "scope": scope}


async def token(request: Request) -> Response:
    form = await request.form()
    grant = form.get("grant_type") or ""
    state = policy_store.load()
    client = state.get("oauth_clients", {}).get((form.get("client_id") or "").strip())
    if grant == "authorization_code":
        rec = state.get("auth_codes", {}).pop(form.get("code") or "", None)
        if not rec or rec["expires_at"] < time.time():
            policy_store.save(state)
            return _json({"error": "invalid_grant", "error_description": "unknown, used or expired code"}, 400)
        client = client or state["oauth_clients"].get(rec["client_id"])
        if not client or client["client_id"] != rec["client_id"]:
            return _json({"error": "invalid_client"}, 401)
        if (form.get("redirect_uri") or rec["redirect_uri"]) != rec["redirect_uri"]:
            return _json({"error": "invalid_grant", "error_description": "redirect_uri does not match"}, 400)
        if not _pkce_ok(form.get("code_verifier") or "", rec["code_challenge"]):
            policy_store.save(state)
            return _json({"error": "invalid_grant", "error_description": "PKCE verification failed"}, 400)
        out = issue_tokens(state, client, rec["user_id"], rec["resource"], rec["scope"])
        policy_store.save(state)
        return _json(out)
    if grant == "refresh_token":
        given = (form.get("refresh_token") or "").strip()
        old = next((t for t in state["agent_tokens"].values() if t.get("refresh_token") == given and not t["revoked"]), None)
        if not old or old.get("refresh_expires_at", 0) < time.time():
            return _json({"error": "invalid_grant", "error_description": "unknown, revoked or expired refresh token"}, 400)
        client = client or state["oauth_clients"].get(old.get("client_id"))
        if not client or client["client_id"] != old.get("client_id"):
            return _json({"error": "invalid_client"}, 401)
        old["revoked"] = True  # rotation: the old pair stops working the moment the new one exists
        out = issue_tokens(state, client, old["sub"], old.get("resource", ""))
        policy_store.save(state)
        return _json(out)
    return _json({"error": "unsupported_grant_type"}, 400)


routes = [
    Route("/.well-known/oauth-authorization-server", as_metadata),
    Route("/.well-known/oauth-authorization-server", preflight, methods=["OPTIONS"]),
    Route("/.well-known/oauth-protected-resource", resource_metadata),
    Route("/.well-known/oauth-protected-resource/mcp", resource_metadata),
    Route("/.well-known/oauth-protected-resource/mcp/{key}", resource_metadata),
    Route("/.well-known/oauth-protected-resource", preflight, methods=["OPTIONS"]),
    Route("/.well-known/oauth-protected-resource/mcp/{key}", preflight, methods=["OPTIONS"]),
    Route("/register", register, methods=["POST"]),
    Route("/register", preflight, methods=["OPTIONS"]),
    Route("/authorize", authorize_get),
    Route("/authorize", authorize_post, methods=["POST"]),
    Route("/token", token, methods=["POST"]),
    Route("/token", preflight, methods=["OPTIONS"]),
]
