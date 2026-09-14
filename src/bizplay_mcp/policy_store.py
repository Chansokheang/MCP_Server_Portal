"""Shared control-plane state: registry, agent tokens, tool access policy.

Written by the onboarding portal, read by the MCP gateway. A single JSON
file stands in for the database a real control plane would use.

Location: data/portal_state.json (override with BIZPLAY_PORTAL_STATE).
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import threading
import time
from pathlib import Path

_lock = threading.RLock()

GATEWAY_TOOLS = [
    # name, kind, default roles, confirm-before-call
    ("get_card_balance", "read", ["employee", "manager"], False),
    ("list_card_transactions", "read", ["employee", "manager"], False),
    ("find_missing_receipts", "read", ["employee", "manager"], False),
    ("validate_tax_compliance", "read", ["employee", "manager"], False),
    ("draft_expense_report", "write", ["employee", "manager"], False),
    ("submit_for_approval", "write", ["employee", "manager"], True),
    ("list_pending_approvals", "read", ["manager"], False),
    ("decide_approval", "write", ["manager"], True),
]


def _seed_state() -> dict:
    return {
        "portal_users": {
            # DEMO ONLY: plain-text passwords. A real portal uses SSO / hashed passwords.
            "admin@bizplay.co.kr": {"password": "admin1234", "name": "Portal Admin", "role": "owner"},
            "security@bizplay.co.kr": {"password": "sec1234", "name": "Security Reviewer", "role": "security"},
        },
        "sessions": {},
        "providers": {
            "bizplay": {
                "id": "bizplay",
                "name": "Bizplay Expense API",
                "owner": "admin@bizplay.co.kr",
                # In Docker Compose this is http://legacy-api:18080 (BIZPLAY_SEED_API_URL).
                "base_url": os.environ.get("BIZPLAY_SEED_API_URL", "http://127.0.0.1:18080"),
                "spec_source": "openapi/bizplay-existing-api.json",
                "mcp_url": public_url("curated"),
                "status": "published",
                "auth_mode": "bearer",
                "upstream_credential_id": "cred_bizplay_service",
                "identity": {"issuer": "portal", "user_claim": "sub", "role_claim": "role", "company_claim": "company"},
                "tools": {
                    name: {"kind": kind, "enabled": True, "roles": roles, "confirm": confirm}
                    for name, kind, roles, confirm in GATEWAY_TOOLS
                },
                "created_at": "2026-09-11T09:00:00+00:00",
            }
        },
        "credentials": {
            "cred_bizplay_service": {
                "id": "cred_bizplay_service",
                "provider_id": "bizplay",
                "label": "Gateway -> Bizplay service token",
                "type": "bearer",
                "secret": "demo-service-token",
                "created_at": "2026-09-11T09:00:00+00:00",
                "rotated_at": None,
            }
        },
        "agent_tokens": {},
        "security": {
            # The address agents use, when it differs from what this server
            # listens on (a tunnel, or nginx with a certificate in front).
            # Remembered here so it survives deleting every registered API.
            "public_mcp_url": "",
            "require_upstream_bearer": True,
            "require_gateway_bearer": True,
            "confirm_on_write": True,
            "token_ttl_days": 30,
            "allowed_agents": ["Claude Desktop", "Claude.ai", "Microsoft Copilot Studio", "Salesforce Agentforce"],
        },
    }


AUTH_MODES = {
    "bearer": "Bearer token: the gateway sends a service token; the API rejects anonymous calls.",
    "network": "Network-isolated: the API has no token but is reachable only from the gateway's address.",
    "open": "Open: the API accepts anonymous calls. Demo data only; recorded as an accepted risk.",
}

KINDS = {
    "openapi": "REST API described by an OpenAPI spec; the gateway generates the tools.",
    "mcp": "An MCP server that already exists; the gateway proxies its tools.",
}

# Argument names / response fields that identify a company. The gateway
# forces them to match the caller's token when the upstream API cannot
# scope data itself.
COMPANY_KEYS = ("corpNo", "corp_no", "company", "companyId", "corporationId")


def public_url(which: str, host: str | None = None) -> str:
    """The address agents should use to reach a gateway.

    Containers listen on fixed internal ports, but the published host and port
    can differ. BIZPLAY_PUBLIC_GATEWAY_URL (curated tools) and
    BIZPLAY_PUBLIC_REGISTRY_URL (registered APIs) win when set. Otherwise the
    host the portal was opened on is used, which is right far more often than
    127.0.0.1 when the portal runs on a server.
    """
    url_env, port_env, default_port = {
        "curated": ("BIZPLAY_PUBLIC_GATEWAY_URL", "BIZPLAY_GATEWAY_PORT", "8000"),
        "registry": ("BIZPLAY_PUBLIC_REGISTRY_URL", "BIZPLAY_REGISTRY_PORT", "8002"),
    }[which]
    explicit = os.environ.get(url_env)
    if explicit:
        # A configured localhost URL is useless to anything off the server. When
        # the portal is being used from elsewhere, keep the port but use the host
        # the browser reached us on.
        if host and not _is_local(host) and _is_local(_host_of(explicit)):
            return explicit.replace(_host_of(explicit), host, 1)
        return explicit
    port = os.environ.get(port_env, default_port)
    return f"http://{host or '127.0.0.1'}:{port}/mcp"


def _host_of(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]


def _is_local(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def state_path() -> Path:
    default = Path(__file__).resolve().parents[2] / "data" / "portal_state.json"
    return Path(os.environ.get("BIZPLAY_PORTAL_STATE", default))


def load() -> dict:
    path = state_path()
    with _lock:
        if not path.exists():
            state = _seed_state()
            save(state)
            return state
        return json.loads(path.read_text(encoding="utf-8"))


def save(state: dict) -> None:
    path = state_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def reset() -> dict:
    state = _seed_state()
    save(state)
    return state


# --- agent tokens (what AI agents present to the gateway) ------------------
def issue_agent_token(state: dict, *, label: str, user_id: str, role: str, company: str,
                      agent: str, ttl_days: int, created_by: str) -> tuple[str, dict]:
    token = "bz_" + secrets.token_urlsafe(32)
    token_id = "tok_" + secrets.token_hex(4)
    now = time.time()
    record = {
        "id": token_id,
        "label": label,
        "agent": agent,
        "sub": user_id,
        "role": role,
        "company": company,
        "scopes": ["bizplay:read"] + (["bizplay:write"] if role in ("employee", "manager") else []),
        "created_at": now,
        "expires_at": now + ttl_days * 86400,
        "created_by": created_by,
        "revoked": False,
        "last_used_at": None,
        "hint": token[:6] + "..." + token[-4:],
        # DEMO ONLY: the raw token is stored so the gateway can verify it by lookup.
        # Production stores a hash and verifies signed JWTs instead.
        "token": token,
    }
    state["agent_tokens"][token_id] = record
    return token, record


def find_agent_token(state: dict, token: str) -> dict | None:
    for record in state["agent_tokens"].values():
        if record["token"] == token and not record["revoked"] and record["expires_at"] > time.time():
            return record
    return None


def public_token(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "token"}


# --- tool policy ----------------------------------------------------------
def tool_policy(state: dict, provider_id: str, tool: str) -> dict | None:
    provider = state["providers"].get(provider_id)
    if not provider:
        return None
    return copy.deepcopy(provider["tools"].get(tool))


def check_tool_access(state: dict, provider_id: str, tool: str, role: str) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    provider = state["providers"].get(provider_id)
    if provider is None:
        return False, f"unknown provider '{provider_id}'"
    if provider.get("status") != "published":
        return False, f"provider '{provider_id}' is not published"
    policy = tool_policy(state, provider_id, tool)
    if policy is None:
        return False, f"tool '{tool}' is not registered for provider '{provider_id}'"
    if not policy["enabled"]:
        return False, f"tool '{tool}' is disabled by the provider admin"
    if role not in policy["roles"]:
        return False, f"role '{role}' is not allowed to call '{tool}'"
    return True, ""


def published_registry_providers(state: dict) -> list[dict]:
    """Published providers the registry gateway serves: OpenAPI-backed or proxied MCP servers."""
    return [p for p in state["providers"].values()
            if p.get("status") == "published" and (p.get("spec") or p.get("kind") == "mcp")]


def standalone_url(provider: dict) -> str:
    """Where this one provider is served on its own, with unprefixed tool names.

    Lives next to the gateway endpoint the provider was registered on, so it
    inherits that address's reachability and TLS: <mcp_url>/<provider id>.
    """
    return provider["mcp_url"].rstrip("/") + "/" + provider["id"] if provider.get("mcp_url") else ""


def company_scope(value: object, company: str) -> tuple[object, int]:
    """Drop records that belong to another company.

    Returns (scoped_value, removed_count). Records are dicts carrying one of
    COMPANY_KEYS; anything without such a key is passed through unchanged.
    """
    def owner(rec: dict) -> str | None:
        for key in COMPANY_KEYS:
            if key in rec and rec[key] is not None:
                return str(rec[key])
        return None

    removed = 0
    if isinstance(value, list):
        kept = []
        for item in value:
            if isinstance(item, dict) and (o := owner(item)) is not None and o != company:
                removed += 1
                continue
            scoped, r = company_scope(item, company)
            removed += r
            kept.append(scoped)
        return kept, removed
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            scoped, r = company_scope(v, company)
            removed += r
            out[k] = scoped
        return out, removed
    return value, removed
