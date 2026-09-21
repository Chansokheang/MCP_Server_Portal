"""Helping a model find its way through many tools: instructions, identity-bound parameters, tool names.

Three things, all per backend so that any gateway serving the backend inherits them:

- **Instructions.** MCP lets a server send a short text at connect time, which
  clients hand to the model. Each backend carries its own usage notes (which
  tool to call first, which next); an endpoint's text is its own lead plus the
  notes of every backend it serves that this caller may use.
- **Identity-bound parameters.** A parameter such as ``corpNo`` can be bound to
  a claim of the caller (company, user id, role). The gateway removes it from
  the tool's input schema and fills it in on every call, so the model never
  guesses which company it is asking about.
- **Tool names.** A spec's operation ids are often ``get_2`` or ``list_3``. A
  row may carry an ``alias``; clients see and call the alias.
"""

from __future__ import annotations

import re
from typing import Any

from . import policy_store

# Where a bound parameter's value comes from.
SOURCES = {
    "company": "the caller's company (corp number)",
    "user": "the caller's user id",
    "role": "the caller's role",
}
ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,50}$")
MAX_INSTRUCTIONS = 2000

_USER_HINT = re.compile(r"^(user_?id|employee_?(id|no|number)|emp_?(id|no)|member_?id|corp_?user_?id)$", re.I)


def suggested_source(param: str) -> str | None:
    """A sensible default binding for a parameter name, offered in the portal, never applied by itself."""
    if param in policy_store.COMPANY_KEYS or re.fullmatch(r"corp_?(no|number|code)|company_?(id|no|code)|business_?(no|number)", param, re.I):
        return "company"
    if _USER_HINT.match(param):
        return "user"
    return None


def clean_instructions(text: Any) -> str:
    return "\n".join(line.rstrip() for line in str(text or "").strip().splitlines())[:MAX_INSTRUCTIONS]


def parse_bindings(value: Any) -> dict[str, str]:
    """{param: source} from a dict or a list of {name, source}; unknown sources and blanks are dropped."""
    pairs = value.items() if isinstance(value, dict) else [(b.get("name"), b.get("source")) for b in value or [] if isinstance(b, dict)]
    return {str(n).strip(): s for n, s in pairs if n and str(n).strip() and s in SOURCES}


def claim_values(user_id: str, claims: dict | None, source: str) -> dict[str, str]:
    """The values each source has for this caller. A source with no value is absent, and its bindings stay idle."""
    claims = claims or {}
    values = {"company": str(claims.get("company") or ""), "role": str(claims.get("role") or "")}
    if source == "bearer":  # the env fallback identity is a demo user, not someone to bind parameters to
        values["user"] = user_id
    return {k: v for k, v in values.items() if v}


def bound_values(provider: dict, user_id: str, claims: dict | None, source: str) -> dict[str, str]:
    """{param: value} for this backend's bindings that have a value for this caller."""
    have = claim_values(user_id, claims, source)
    return {param: have[src] for param, src in (provider.get("bound_params") or {}).items() if src in have}


def strip_params(schema: dict | None, names: set[str]) -> dict | None:
    """The input schema without the bound parameters (they are filled in by the gateway)."""
    if not schema or not names or not isinstance(schema.get("properties"), dict):
        return schema
    hit = names & set(schema["properties"])
    if not hit:
        return schema
    out = {**schema, "properties": {k: v for k, v in schema["properties"].items() if k not in hit}}
    if isinstance(schema.get("required"), list):
        out["required"] = [r for r in schema["required"] if r not in hit]
    return out


def real_tool_name(provider: dict, op: str) -> str:
    """The stored tool name for what a client called: an alias maps back, anything else is itself."""
    if op in provider.get("tools", {}):
        return op
    return next((name for name, row in provider.get("tools", {}).items() if row.get("alias") == op), op)


def alias_problem(provider: dict, tool: str, alias: str) -> str | None:
    if not ALIAS_RE.match(alias):
        return "a tool name starts with a letter and uses letters, digits and _ only (2 to 51 characters)"
    for name, row in provider["tools"].items():
        if name != tool and (name == alias or row.get("alias") == alias):
            return f"'{alias}' is already the name of another tool of this backend"
    return None


def backends_for(state: dict, key: str) -> list[dict]:
    """The published backends one endpoint serves: a named gateway's, a deployed backend alone, or all of them."""
    published = [p for p in policy_store.published_registry_providers(state)]
    if not key:
        return published
    gateway = state["gateways"].get(key)
    if gateway:
        return [p for p in published if p["id"] in set(gateway.get("providers") or [])]
    return [p for p in published if p["id"] == key and p.get("standalone")]


def compose_instructions(state: dict, key: str, user_id: str = "", claims: dict | None = None, source: str = "env") -> str:
    """What the model is told when it connects to this endpoint, for this caller."""
    own = clean_instructions((state.get("endpoint_settings", {}).get(key) or {}).get("instructions"))
    standalone = bool(key) and key not in state["gateways"]
    parts = [own] if own else []
    filled: set[str] = set()
    for p in backends_for(state, key):
        ok, _ = policy_store.check_provider_access(state, p["id"], claims) if claims is not None else (True, "")
        if not ok:
            continue
        filled |= set(bound_values(p, user_id, claims, source))
        notes = clean_instructions(p.get("instructions"))
        if notes:
            prefix = "" if standalone else f" (tools named `{p.get('tool_prefix') or p['id'].replace('-', '_') + '_'}*`)"
            parts.append(f"## {p['name']}{prefix}\n{notes}")
    if filled:
        parts.append("The gateway fills in these parameters from the signed-in user, so they do not appear in the tools and "
                     f"must never be asked for: {', '.join(sorted(filled))}.")
    return "\n\n".join(parts)[: MAX_INSTRUCTIONS * 4]
