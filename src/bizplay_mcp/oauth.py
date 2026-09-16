"""Per-user OAuth to backends: the gateway as token broker.

Some backends want the calling user's own token from their own auth server,
not a shared service key. The AI client never sees those auth servers: it
logs in to the gateway once. For each such backend a user links their account
in the portal (authorization code + PKCE), the tokens are kept here keyed by
(user, provider), and the gateway attaches the right one to every upstream
call, refreshing it when it expires.

    portal  --start-->  backend's auth server  --callback-->  portal (stores tokens)
    gateway --call-->   access_token_for(user, provider)  --> Authorization: Bearer <user token>

Optional helpers for MCP servers that publish their auth metadata (RFC 9728 /
RFC 8414) and accept dynamic client registration (RFC 7591): one click fills
the endpoints in and registers the gateway as a client.

DEMO ONLY: tokens are stored in the JSON state file, like every other secret
here. Production keeps them in a vault.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from . import policy_store

# The upstream token for the call in flight, set by the gateway before the
# tool runs and read where the HTTP request to the backend is built.
upstream_token: ContextVar[str | None] = ContextVar("upstream_token", default=None)

# Tests swap this for one that talks to an in-process auth server.
http_client_factory = httpx.AsyncClient

REFRESH_LEEWAY = 60


class OAuthError(Exception):
    pass


def _client(**kwargs) -> httpx.AsyncClient:
    return http_client_factory(timeout=15.0, follow_redirects=True, **kwargs)


# --- discovery and client registration ---------------------------------------------
async def discover(url: str) -> dict[str, Any]:
    """Find the auth server behind an MCP URL (RFC 9728), then its endpoints (RFC 8414).

    Falls back to treating the URL itself as the authorization server when it
    publishes no protected-resource metadata.
    """
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    found: dict[str, Any] = {"resource": url}
    async with _client() as c:
        issuer = None
        for candidate in (f"{origin}/.well-known/oauth-protected-resource{parts.path.rstrip('/')}",
                          f"{origin}/.well-known/oauth-protected-resource"):
            r = await c.get(candidate)
            if r.status_code == 200:
                doc = r.json()
                servers = doc.get("authorization_servers") or []
                if servers:
                    issuer = servers[0]
                    found["scopes"] = " ".join(doc.get("scopes_supported") or [])
                    break
        issuer = issuer or origin
        meta = None
        for candidate in (f"{issuer.rstrip('/')}/.well-known/oauth-authorization-server",
                          f"{issuer.rstrip('/')}/.well-known/openid-configuration"):
            r = await c.get(candidate)
            if r.status_code == 200:
                meta = r.json()
                break
        if not meta:
            raise OAuthError(f"no OAuth metadata found for {url}; fill the endpoints in by hand")
    found.update({
        "issuer": issuer,
        "authorization_url": meta.get("authorization_endpoint", ""),
        "token_url": meta.get("token_endpoint", ""),
        "registration_url": meta.get("registration_endpoint", ""),
    })
    if not found.get("scopes"):
        found["scopes"] = " ".join(meta.get("scopes_supported") or [])
    if not found["authorization_url"] or not found["token_url"]:
        raise OAuthError("the auth server metadata lacks authorization_endpoint or token_endpoint")
    return found


async def register_client(registration_url: str, redirect_uri: str, client_name: str) -> dict[str, str]:
    """Dynamic client registration (RFC 7591). Returns client_id and (maybe) client_secret."""
    async with _client() as c:
        r = await c.post(registration_url, json={
            "client_name": client_name,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
        })
    if r.status_code not in (200, 201):
        raise OAuthError(f"client registration refused: HTTP {r.status_code} {r.text[:120]}")
    doc = r.json()
    if not doc.get("client_id"):
        raise OAuthError("client registration returned no client_id")
    return {"client_id": doc["client_id"], "client_secret": doc.get("client_secret", "")}


# --- the flow ----------------------------------------------------------------------
def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def start(state: dict, provider: dict, user_id: str, redirect_uri: str) -> str:
    """Record a pending authorization and return the URL to send the user to."""
    cfg = provider.get("oauth") or {}
    if not cfg.get("authorization_url") or not cfg.get("client_id"):
        raise OAuthError("this backend has no OAuth configuration yet (authorization URL and client id)")
    verifier, challenge = _pkce()
    nonce = secrets.token_urlsafe(24)
    state.setdefault("oauth_pending", {})[nonce] = {
        "provider_id": provider["id"], "user_id": user_id, "code_verifier": verifier,
        "redirect_uri": redirect_uri, "created_at": time.time(),
    }
    # Forget attempts older than ten minutes.
    for key, pending in list(state["oauth_pending"].items()):
        if pending["created_at"] < time.time() - 600:
            del state["oauth_pending"][key]
    query = {
        "response_type": "code", "client_id": cfg["client_id"], "redirect_uri": redirect_uri,
        "state": nonce, "code_challenge": challenge, "code_challenge_method": "S256",
    }
    if cfg.get("scopes"):
        query["scope"] = cfg["scopes"]
    if cfg.get("resource"):
        query["resource"] = cfg["resource"]  # RFC 8707, what MCP servers expect
    sep = "&" if "?" in cfg["authorization_url"] else "?"
    return cfg["authorization_url"] + sep + urlencode(query)


async def _token_request(cfg: dict, data: dict) -> dict:
    payload = {**data, "client_id": cfg["client_id"]}
    if cfg.get("client_secret"):
        payload["client_secret"] = cfg["client_secret"]
    if cfg.get("resource"):
        payload["resource"] = cfg["resource"]
    try:
        async with _client() as c:
            r = await c.post(cfg["token_url"], data=payload, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OAuthError(f"auth server unreachable at {cfg['token_url']}: {type(exc).__name__}") from exc
    if r.status_code != 200:
        raise OAuthError(f"token endpoint answered HTTP {r.status_code}: {r.text[:160]}")
    doc = r.json()
    if "access_token" not in doc:
        raise OAuthError("token endpoint returned no access_token")
    return doc


def _store(state: dict, provider_id: str, user_id: str, doc: dict, previous: dict | None = None) -> dict:
    now = time.time()
    record = {
        "access_token": doc["access_token"],
        "refresh_token": doc.get("refresh_token") or (previous or {}).get("refresh_token", ""),
        "expires_at": now + float(doc["expires_in"]) if doc.get("expires_in") else None,
        "scope": doc.get("scope", (previous or {}).get("scope", "")),
        "token_type": doc.get("token_type", "Bearer"),
        "connected_at": (previous or {}).get("connected_at", now),
        "refreshed_at": now if previous else None,
    }
    state.setdefault("user_connections", {}).setdefault(user_id, {})[provider_id] = record
    return record


async def finish(state: dict, nonce: str, code: str) -> tuple[dict, dict]:
    """Exchange the code from the callback. Returns (provider, pending)."""
    pending = state.get("oauth_pending", {}).pop(nonce, None)
    if not pending:
        raise OAuthError("unknown or expired authorization attempt; start again from the portal")
    provider = state["providers"].get(pending["provider_id"])
    if not provider:
        raise OAuthError("the backend was deleted while you were signing in")
    doc = await _token_request(provider["oauth"], {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": pending["redirect_uri"], "code_verifier": pending["code_verifier"],
    })
    _store(state, provider["id"], pending["user_id"], doc)
    return provider, pending


def connection(state: dict, provider_id: str, user_id: str) -> dict | None:
    return state.get("user_connections", {}).get(user_id, {}).get(provider_id)


async def access_token_for(state: dict, provider: dict, user_id: str) -> str | None:
    """A valid access token for this user on this backend, refreshed if needed.

    Returns None when the user has not linked an account. Writes the state
    back when a refresh happened.
    """
    record = connection(state, provider["id"], user_id)
    if not record:
        return None
    if record.get("expires_at") and record["expires_at"] < time.time() + REFRESH_LEEWAY:
        if not record.get("refresh_token"):
            return None
        doc = await _token_request(provider["oauth"], {"grant_type": "refresh_token",
                                                       "refresh_token": record["refresh_token"]})
        record = _store(state, provider["id"], user_id, doc, previous=record)
        policy_store.save(state)
    return record["access_token"]


async def listing_token(state: dict, provider: dict) -> str | None:
    """Some linked user's valid token, refreshing an expired one, for reading tool metadata.

    The tool list is the same for every user, so any linked account will do; but
    after a restart or an idle hour every stored access token may have expired,
    and only a refresh gets the list back. Errors from the auth server are
    swallowed here: the caller treats "no token" as "no tools for now".
    """
    for user_id, per_user in list(state.get("user_connections", {}).items()):
        if provider["id"] not in per_user:
            continue
        try:
            token = await access_token_for(state, provider, user_id)
        except (OAuthError, httpx.HTTPError):
            continue
        if token:
            return token
    return None


def any_token(state: dict, provider_id: str) -> str | None:
    """Some user's unexpired token, for reading tool metadata that is not per user."""
    for per_user in state.get("user_connections", {}).values():
        record = per_user.get(provider_id)
        if record and (not record.get("expires_at") or record["expires_at"] > time.time() + REFRESH_LEEWAY):
            return record["access_token"]
    return None


def disconnect(state: dict, provider_id: str, user_id: str) -> bool:
    per_user = state.get("user_connections", {}).get(user_id, {})
    return per_user.pop(provider_id, None) is not None


def public_connections(state: dict, provider_id: str) -> list[dict]:
    out = []
    for user_id, per_user in state.get("user_connections", {}).items():
        record = per_user.get(provider_id)
        if record:
            out.append({"user_id": user_id, "connected_at": record["connected_at"], "expires_at": record.get("expires_at"),
                        "refreshed_at": record.get("refreshed_at"), "scope": record.get("scope", ""),
                        "kind": record.get("type", "oauth"), "username": record.get("username"),
                        "can_refresh": bool(record.get("refresh_token")) or record.get("type") == "login"})
    return sorted(out, key=lambda x: x["user_id"])
