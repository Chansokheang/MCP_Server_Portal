"""A backend with its own OAuth server, for demonstrating per-user account linking.

One process, two roles:

  * an authorization server: metadata (RFC 8414), dynamic client registration
    (RFC 7591), a sign-in page at /authorize that asks which demo user you are,
    and a token endpoint with PKCE and refresh
  * a protected API: GET /items answers only with a user token, and the items
    differ per user, so a linked account is visible in the result

Run:
    uv run python scripts/mock_oauth_backend.py --port 18095

Then in the portal register a REST API with base URL http://127.0.0.1:18095,
the spec from http://127.0.0.1:18095/openapi.json, auth mode OAuth, click
Discover, publish, and Connect account.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import secrets
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

PUBLIC = "http://127.0.0.1:18095"
USERS = {"emp001": ["Q3 travel invoice", "Team lunch receipt"], "emp002": ["Client dinner receipt"], "mgr001": ["Budget review"]}
clients: dict[str, dict] = {}
codes: dict[str, dict] = {}
tokens: dict[str, dict] = {}


async def metadata(request: Request):
    return JSONResponse({"issuer": PUBLIC, "authorization_endpoint": f"{PUBLIC}/authorize", "token_endpoint": f"{PUBLIC}/token",
                         "registration_endpoint": f"{PUBLIC}/register", "scopes_supported": ["items:read"],
                         "code_challenge_methods_supported": ["S256"], "grant_types_supported": ["authorization_code", "refresh_token"]})


async def register(request: Request):
    body = await request.json()
    cid, secret = "client_" + secrets.token_hex(4), secrets.token_urlsafe(16)
    clients[cid] = {"secret": secret, "redirect_uris": body.get("redirect_uris", []), "name": body.get("client_name", "")}
    return JSONResponse({"client_id": cid, "client_secret": secret, "redirect_uris": clients[cid]["redirect_uris"]}, status_code=201)


async def authorize(request: Request):
    q = request.query_params
    client = clients.get(q.get("client_id", ""))
    if not client or q.get("redirect_uri") not in client["redirect_uris"]:
        return HTMLResponse("<h2>Unknown client or redirect URI. Click Discover in the portal first.</h2>", status_code=400)
    if request.method == "POST":
        form = await request.form()
        user = str(form.get("user", "emp001"))
        code = "code_" + secrets.token_urlsafe(16)
        codes[code] = {"user": user, "challenge": q.get("code_challenge", ""), "redirect_uri": q["redirect_uri"], "client_id": q["client_id"]}
        return RedirectResponse(f"{q['redirect_uri']}?code={code}&state={q.get('state', '')}", status_code=303)
    options = "".join(f'<option value="{u}">{u}</option>' for u in USERS)
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>Items sign-in</title>
    <body style="font-family:system-ui;max-width:420px;margin:60px auto;line-height:1.5">
    <h2>Items sign-in</h2>
    <p><b>{client['name'] or 'An application'}</b> wants to read your items (scope: {q.get('scope') or 'items:read'}).</p>
    <form method="post"><label>Sign in as <select name="user">{options}</select></label>
    <p><button type="submit">Allow</button></p></form>
    <p style="color:#666;font-size:13px">Demo auth server. A real one would ask for a password.</p></body>""")


async def token(request: Request):
    form = await request.form()
    client = clients.get(str(form.get("client_id", "")))
    if not client or client["secret"] != form.get("client_secret"):
        return JSONResponse({"error": "invalid_client"}, status_code=401)
    grant = form.get("grant_type")
    if grant == "authorization_code":
        pending = codes.pop(str(form.get("code", "")), None)
        if not pending:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        expected = base64.urlsafe_b64encode(hashlib.sha256(str(form.get("code_verifier", "")).encode()).digest()).rstrip(b"=").decode()
        if expected != pending["challenge"]:
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verifier mismatch"}, status_code=400)
        user = pending["user"]
    elif grant == "refresh_token":
        record = tokens.get(str(form.get("refresh_token", "")))
        if not record:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        user = record["user"]
    else:
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    access, refresh = "at_" + secrets.token_urlsafe(16), "rt_" + secrets.token_urlsafe(16)
    tokens[access] = {"user": user, "expires_at": time.time() + 600}
    tokens[refresh] = {"user": user}
    return JSONResponse({"access_token": access, "refresh_token": refresh, "token_type": "Bearer", "expires_in": 600, "scope": "items:read"})


async def items(request: Request):
    access = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    record = tokens.get(access)
    if not record or record.get("expires_at", 0) < time.time():
        return JSONResponse({"error": "sign in required"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    return JSONResponse({"user": record["user"], "items": USERS.get(record["user"], [])})


async def openapi(request: Request):
    return JSONResponse({"openapi": "3.0.3", "info": {"title": "Items API", "version": "1"},
                         "paths": {"/items": {"get": {"operationId": "listMyItems", "summary": "Items of the signed-in user",
                                                      "responses": {"200": {"description": "ok"}}}}}})


app = Starlette(routes=[
    Route("/.well-known/oauth-authorization-server", metadata),
    Route("/register", register, methods=["POST"]),
    Route("/authorize", authorize, methods=["GET", "POST"]),
    Route("/token", token, methods=["POST"]),
    Route("/items", items),
    Route("/openapi.json", openapi),
])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18095)
    args = parser.parse_args()
    PUBLIC = f"http://{args.host}:{args.port}"
    uvicorn.run(app, host=args.host, port=args.port)
