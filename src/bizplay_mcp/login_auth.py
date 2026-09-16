"""Login-endpoint auth: the gateway signs in with a username and password and sends the token it gets back.

For APIs that have their own `POST /login` rather than an OAuth server. The
backend's `login` config says where to sign in, what to send, where the token
is in the answer and how to present it on calls. Credentials come in two shapes:

- **service account**: one username and password on the backend's upstream
  credential record; the token is cached there and renewed when it expires or
  the backend answers 401. Every caller shares that identity.
- **per user**: each user's own username and password, kept in
  `user_connections` next to OAuth links, so the backend sees the real user.

Passwords are stored as given. Production encrypts them at rest or keeps them
in a vault; this mockup keeps them in the state file like every other secret.
"""

from __future__ import annotations

import json
import re
import time

import httpx

from . import policy_store

LEEWAY = 60  # seconds before expiry at which a token counts as expired
FIELDS = ("url", "body", "token_path", "expires_path", "ttl_minutes", "header", "scheme", "per_user")
DEFAULTS = {
    "url": "",
    "body": '{"username": "{username}", "password": "{password}"}',
    "token_path": "token",
    "expires_path": "",
    "ttl_minutes": 60,
    "header": "Authorization",
    "scheme": "Bearer",
    "per_user": False,
}

# Tests swap this for a client with an in-memory transport.
http_client_factory = httpx.AsyncClient


class LoginError(Exception):
    pass


def config(provider: dict) -> dict:
    return {**DEFAULTS, **(provider.get("login") or {})}


def ready(provider: dict) -> bool:
    cfg = config(provider)
    return bool(str(cfg.get("url", "")).startswith("http") and cfg.get("token_path"))


def parse_config(body: dict, existing: dict | None = None) -> dict:
    """Merge login settings from a request into the stored ones. Raises ValueError on bad values."""
    cfg = dict(existing or {})
    for key in FIELDS:
        if key not in body:
            continue
        value = body[key]
        if key == "per_user":
            cfg[key] = bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "yes", "on")
        elif key == "ttl_minutes":
            try:
                cfg[key] = max(1, min(24 * 60 * 30, int(value or DEFAULTS["ttl_minutes"])))
            except (TypeError, ValueError):
                raise ValueError("ttl_minutes must be a number of minutes") from None
        else:
            cfg[key] = str(value or "").strip()
    if cfg.get("url") and not cfg["url"].startswith("http"):
        raise ValueError("login url must start with http")
    if cfg.get("body"):
        try:
            json.loads(_render_body(cfg["body"], "u", "p"))
        except json.JSONDecodeError:
            raise ValueError("request body must be JSON; {username} and {password} are filled in") from None
    if not cfg.get("header"):
        cfg["header"] = DEFAULTS["header"]
    return cfg


def _dig(doc, path: str):
    """`data.token` or `tokens[0].value` out of a JSON document; None when absent."""
    cur = doc
    for part in [p for p in re.split(r"[.\[\]]+", path) if p]:
        if isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _render_body(template: str, username: str, password: str) -> str:
    quoted = lambda s: json.dumps(s)[1:-1]  # noqa: E731 - escape for a JSON string context
    return template.replace("{username}", quoted(username)).replace("{password}", quoted(password))


async def sign_in(provider: dict, username: str, password: str) -> dict:
    """POST the login request. Returns {"access_token", "expires_at"} or raises LoginError."""
    cfg = config(provider)
    if not ready(provider):
        raise LoginError("login endpoint not configured: set the login URL and token field")
    try:
        payload = json.loads(_render_body(cfg["body"], username, password))
    except json.JSONDecodeError:
        raise LoginError("request body template is not valid JSON") from None
    try:
        async with http_client_factory(timeout=15.0) as client:
            r = await client.post(cfg["url"], json=payload)
    except httpx.HTTPError as exc:
        raise LoginError(f"login endpoint unreachable: {str(exc)[:120]}") from None
    if r.status_code in (400, 401, 403):
        raise LoginError(f"login refused ({r.status_code}): wrong username or password?")
    if r.status_code >= 400:
        raise LoginError(f"login endpoint answered {r.status_code}")
    try:
        doc = r.json()
    except ValueError:
        raise LoginError("login endpoint did not answer JSON") from None
    token = _dig(doc, cfg["token_path"])
    if not isinstance(token, str) or not token:
        raise LoginError(f"no token at '{cfg['token_path']}' in the login response")
    ttl = None
    if cfg.get("expires_path"):
        value = _dig(doc, cfg["expires_path"])
        if isinstance(value, (int, float)) and value > 0:
            ttl = float(value)  # seconds, the common convention (expiresIn / expires_in)
    if ttl is None:
        ttl = float(cfg.get("ttl_minutes") or DEFAULTS["ttl_minutes"]) * 60
    return {"access_token": token, "expires_at": time.time() + ttl}


def header_for(provider: dict, token: str) -> dict[str, str]:
    """How the token rides on a call: `Authorization: Bearer x` by default, or a custom header."""
    cfg = config(provider)
    return {cfg["header"]: f"{cfg['scheme']} {token}".strip() if cfg.get("scheme") else token}


def _fresh(record: dict | None) -> bool:
    return bool(record and record.get("access_token") and record.get("expires_at", 0) > time.time() + LEEWAY)


def service_credential(state: dict, provider: dict) -> dict | None:
    return state["credentials"].get(provider.get("upstream_credential_id", ""))


async def service_token(state: dict, provider: dict) -> str:
    """The service account's token, signing in when there is none or it has expired."""
    cred = service_credential(state, provider)
    if not cred or not cred.get("username") or not cred.get("secret"):
        raise LoginError("no service account set for this backend")
    cached = cred.get("cached") or {}
    if _fresh(cached):
        return cached["access_token"]
    fresh = await sign_in(provider, cred["username"], cred["secret"])
    cred["cached"] = {**fresh, "signed_in_at": time.time()}
    policy_store.save(state)
    return fresh["access_token"]


def connection(state: dict, provider_id: str, user_id: str) -> dict | None:
    record = state.get("user_connections", {}).get(user_id, {}).get(provider_id)
    return record if record and record.get("type") == "login" else None


async def user_token(state: dict, provider: dict, user_id: str) -> str | None:
    """This user's token, signing in again when it has expired. None when they never connected."""
    record = connection(state, provider["id"], user_id)
    if not record:
        return None
    if _fresh(record):
        return record["access_token"]
    fresh = await sign_in(provider, record["username"], record["password"])
    record.update(fresh, refreshed_at=time.time())
    policy_store.save(state)
    return record["access_token"]


async def connect_user(state: dict, provider: dict, user_id: str, username: str, password: str) -> dict:
    """Store a user's credentials for this backend, after proving them with a real sign-in."""
    fresh = await sign_in(provider, username, password)
    record = {"type": "login", "username": username, "password": password, **fresh,
              "connected_at": time.time(), "refreshed_at": None, "scope": ""}
    state.setdefault("user_connections", {}).setdefault(user_id, {})[provider["id"]] = record
    return record


async def token_for(state: dict, provider: dict, user_id: str) -> str | None:
    """The token a call should carry: the caller's own when per user, else the service account's."""
    if config(provider)["per_user"]:
        return await user_token(state, provider, user_id)
    return await service_token(state, provider)


async def listing_token(state: dict, provider: dict) -> str | None:
    """A token for reading tool metadata: the service account's, or any connected user's."""
    if not config(provider)["per_user"]:
        try:
            return await service_token(state, provider)
        except LoginError:
            return None
    for user_id, per_user in list(state.get("user_connections", {}).items()):
        if per_user.get(provider["id"], {}).get("type") == "login":
            try:
                token = await user_token(state, provider, user_id)
            except LoginError:
                continue
            if token:
                return token
    return None


def invalidate(state: dict, provider: dict, token: str) -> bool:
    """The backend refused this token (401): forget it, so the next call signs in again."""
    cred = service_credential(state, provider) or {}
    if (cred.get("cached") or {}).get("access_token") == token:
        cred["cached"] = {}
        return True
    for per_user in state.get("user_connections", {}).values():
        record = per_user.get(provider["id"])
        if record and record.get("type") == "login" and record.get("access_token") == token:
            record["expires_at"] = 0
            return True
    return False
