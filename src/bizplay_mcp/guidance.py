"""Helping a model find its way through many tools.

Everything here is set per backend, so any gateway that serves the backend
inherits it, and a gateway may override values for its own team.

- **Instructions.** MCP lets a server send a short text at connect time, which
  clients hand to the model. Each backend carries its own usage notes; an
  endpoint's text is its own lead plus the notes of every backend it serves
  that this caller may use.
- **Parameter sources.** Where a parameter's value comes from when a tool is
  called: asked from the model (the default), filled from the caller's
  identity (company, user id, role), a fixed value the model never sees, or a
  default used when the model leaves it out. A gateway can override a source
  for its own callers.
- **Where values come from.** ``askBot.botId`` comes from ``listBots``, field
  ``id``. Stated by an admin, or learned by watching real calls: a value that
  came back from one tool and went into another is an observed link. The
  gateway tells the model at the moment it matters: in the tool's description
  and in the error when a call arrives without a usable value.
- **Workflows.** A fixed sequence of tools published as one tool, run by the
  gateway in order, with each step's inputs taken from the request or from an
  earlier step's result. The model cannot get the order wrong because it never
  sees the steps.
- **Tool names.** A spec's operation ids are often ``get_2``; a row may carry
  an ``alias`` that clients see and call.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from . import policy_store

# --- parameter sources ----------------------------------------------------------------
CALLER_SOURCES = {
    "company": "the caller's company (corp number)",
    "user": "the caller's user id",
    "role": "the caller's role",
}
KINDS = ("caller", "fixed", "default")
ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,50}$")
MAX_INSTRUCTIONS = 2000
_USER_HINT = re.compile(r"^(user_?id|employee_?(id|no|number)|emp_?(id|no)|member_?id|corp_?user_?id)$", re.I)


def suggested_source(param: str) -> str | None:
    """A sensible caller binding for a parameter name, offered in the portal, never applied by itself."""
    if param in policy_store.COMPANY_KEYS or re.fullmatch(r"corp_?(no|number|code)|company_?(id|no|code)|business_?(no|number)", param, re.I):
        return "company"
    if _USER_HINT.match(param):
        return "user"
    return None


def clean_instructions(text: Any) -> str:
    return "\n".join(line.rstrip() for line in str(text or "").strip().splitlines())[:MAX_INSTRUCTIONS]


def _coerce(value: Any) -> Any:
    """A typed value from what a form sends: numbers, booleans and JSON stay themselves, the rest is text."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    if text[:1] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def parse_sources(value: Any) -> dict[str, dict]:
    """{param: {kind, value}} from a dict of {param: {kind, value}} or {param: "company"} (a caller binding)."""
    out: dict[str, dict] = {}
    items = value.items() if isinstance(value, dict) else [(b.get("name"), b) for b in value or [] if isinstance(b, dict)]
    for name, spec in items:
        name = str(name or "").strip()
        if not name:
            continue
        if isinstance(spec, str):
            spec = {"kind": "caller", "value": spec}
        if not isinstance(spec, dict):
            continue
        kind = spec.get("kind") or ("caller" if spec.get("source") else "")
        val = spec.get("value", spec.get("source"))
        if kind == "caller" and val in CALLER_SOURCES:
            out[name] = {"kind": "caller", "value": val}
        elif kind in ("fixed", "default") and val not in (None, ""):
            out[name] = {"kind": kind, "value": _coerce(val)}
    return out


def parse_bindings(value: Any) -> dict[str, str]:
    """Older callers send {param: caller source}; keep accepting it."""
    return {n: s["value"] for n, s in parse_sources(value).items() if s["kind"] == "caller"}


def sources_for(provider: dict, state: dict | None = None, key: str = "") -> dict[str, dict]:
    """Effective parameter sources for a backend on an endpoint: the backend's, then the gateway's overrides.

    Company parameters (corpNo and the other names in COMPANY_KEYS) are filled in
    from the caller without any setup: the gateway already limits every call to
    the caller's company, so asking the model for it only invites a wrong guess.
    """
    own = {k: {"kind": "caller", "value": "company"} for k in policy_store.COMPANY_KEYS}
    own.update(provider.get("param_sources") or {})
    for name, src in (provider.get("bound_params") or {}).items():  # rows from before sources had kinds
        own.setdefault(name, {"kind": "caller", "value": src})
    if state is not None and key:
        overrides = ((state.get("endpoint_settings", {}).get(key) or {}).get("param_sources") or {}).get(provider["id"]) or {}
        for name, spec in overrides.items():
            if spec is None:
                own.pop(name, None)
            else:
                own[name] = spec
    return own


def claim_values(user_id: str, claims: dict | None, source: str) -> dict[str, str]:
    """The values each caller source has for this caller. A source with no value is absent, and its bindings stay idle."""
    claims = claims or {}
    values = {"company": str(claims.get("company") or ""), "role": str(claims.get("role") or "")}
    if source == "bearer":  # the env fallback identity is a demo user, not someone to bind parameters to
        values["user"] = user_id
    return {k: v for k, v in values.items() if v}


def resolve_sources(sources: dict[str, dict], user_id: str, claims: dict | None, source: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(hidden, defaults): values the gateway always sends and hides, and values used when the model leaves them out."""
    have = claim_values(user_id, claims, source)
    hidden: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    for name, spec in sources.items():
        if spec["kind"] == "caller":
            if spec["value"] in have:
                hidden[name] = have[spec["value"]]
        elif spec["kind"] == "fixed":
            hidden[name] = spec["value"]
        else:
            defaults[name] = spec["value"]
    return hidden, defaults


def bound_values(provider: dict, user_id: str, claims: dict | None, source: str, state: dict | None = None, key: str = "") -> dict[str, Any]:
    """{param: value} the gateway fills in and hides for this caller (caller bindings and fixed values)."""
    return resolve_sources(sources_for(provider, state, key), user_id, claims, source)[0]


def shape_schema(schema: dict | None, hidden: set[str], defaults: dict[str, Any], hints: dict[str, str]) -> dict | None:
    """The input schema as the model should see it: hidden parameters gone, defaults shown, origins hinted."""
    if not schema or not isinstance(schema.get("properties"), dict):
        return schema
    props = schema["properties"]
    if not (hidden & set(props)) and not (set(defaults) & set(props)) and not (set(hints) & set(props)):
        return schema
    new_props = {}
    for k, v in props.items():
        if k in hidden:
            continue
        v = dict(v) if isinstance(v, dict) else {"type": "string"}
        if k in defaults:
            v["default"] = defaults[k]
            v["description"] = (v.get("description", "") + f" Default: {json.dumps(defaults[k], ensure_ascii=False)}.").strip()
        if k in hints:
            v["description"] = (v.get("description", "") + " " + hints[k]).strip()
        new_props[k] = v
    out = {**schema, "properties": new_props}
    if isinstance(schema.get("required"), list):
        out["required"] = [r for r in schema["required"] if r not in hidden and r not in defaults]
    return out


def strip_params(schema: dict | None, names: set[str]) -> dict | None:
    return shape_schema(schema, names, {}, {})


# --- tool names ---------------------------------------------------------------------------
def real_tool_name(provider: dict, op: str) -> str:
    """The stored tool name for what a client called: an alias maps back, anything else is itself."""
    if op in provider.get("tools", {}):
        return op
    return next((name for name, row in provider.get("tools", {}).items() if row.get("alias") == op), op)


def shown_name(provider: dict, op: str) -> str:
    return (provider.get("tools", {}).get(op) or {}).get("alias") or op


def alias_problem(provider: dict, tool: str, alias: str) -> str | None:
    if not ALIAS_RE.match(alias):
        return "a tool name starts with a letter and uses letters, digits and _ only (2 to 51 characters)"
    for name, row in provider["tools"].items():
        if name != tool and (name == alias or row.get("alias") == alias):
            return f"'{alias}' is already the name of another tool of this backend"
    return None


# --- where values come from -------------------------------------------------------------
def parse_comes_from(value: Any, provider: dict) -> dict[str, dict]:
    """{"tool.param": {"tool": producer, "field": "id"}} or {"tool.param": {"value": ...}} for a value typed by hand.

    Producers must be tools of this backend. A typed value is sent on every call of
    that one tool and hidden from the model, like a fixed value but for a single tool.
    """
    out: dict[str, dict] = {}
    tools = provider.get("tools") or {}
    for key, spec in (value or {}).items() if isinstance(value, dict) else []:
        if not isinstance(spec, dict):
            continue
        tool, _, param = str(key).partition(".")
        if tool not in tools or not param:
            continue
        if spec.get("tool"):
            producer = real_tool_name(provider, str(spec["tool"]))
            if producer in tools:
                out[f"{tool}.{param}"] = {"tool": producer, "field": str(spec.get("field") or "").strip()}
        elif spec.get("value") not in (None, ""):
            out[f"{tool}.{param}"] = {"value": _coerce(spec["value"])}
        elif spec.get("default") not in (None, ""):
            out[f"{tool}.{param}"] = {"default": _coerce(spec["default"])}
        else:
            continue
        if spec.get("enabled") is False and "tool" not in out[f"{tool}.{param}"]:
            out[f"{tool}.{param}"]["enabled"] = False  # typed but switched off: kept so it can be switched on again
    return out


def parse_gateway_values(value: Any, state: dict) -> dict[str, dict[str, dict]]:
    """{backend id: {"tool.param": {"value" | "default": x, "enabled": bool}}}: one gateway's changes to typed values.

    A row may replace the backend's value, change its kind, or only switch it off
    ({"enabled": false}); a row for a parameter the backend has no value for adds one
    for this gateway alone. The tool may be "*": every tool that takes the parameter,
    which is how a header such as an API token is set once.
    """
    out: dict[str, dict[str, dict]] = {}
    for pid, rows in (value or {}).items() if isinstance(value, dict) else []:
        provider = state["providers"].get(pid)
        if not provider or not isinstance(rows, dict):
            continue
        for key, spec in rows.items():
            if not isinstance(spec, dict):
                continue
            tool, _, param = str(key).partition(".")
            if tool == "*":
                if not param or not any(param in (r.get("params") or []) for r in provider.get("tools", {}).values()):
                    continue
            else:
                row = provider.get("tools", {}).get(tool)
                if not row or not param or (row.get("params") and param not in row["params"]):
                    continue
            entry: dict = {}
            if spec.get("value") not in (None, ""):
                entry["value"] = _coerce(spec["value"])
            elif spec.get("default") not in (None, ""):
                entry["default"] = _coerce(spec["default"])
            if spec.get("enabled") is False:
                entry["enabled"] = False
            if entry:
                out.setdefault(pid, {})[f"{tool}.{param}"] = entry
    return out


def typed_rows(provider: dict, state: dict | None = None, key: str = "") -> dict[str, dict]:
    """Every typed value for one backend as seen from one endpoint: the backend's rows with the gateway's changes on top."""
    rows = {k: dict(spec) for k, spec in (provider.get("comes_from") or {}).items() if "value" in spec or "default" in spec}
    if state is not None and key:
        changes = ((state.get("endpoint_settings", {}).get(key) or {}).get("values") or {}).get(provider["id"]) or {}
        for k, change in changes.items():
            merged = {**rows.get(k, {}), **change}
            if "value" in change:
                merged.pop("default", None)
            elif "default" in change:
                merged.pop("value", None)
            if "enabled" not in change:
                merged.pop("enabled", None)  # a new value switches the row back on
            rows[k] = merged
    return rows


def typed_for(provider: dict, tool: str, state: dict | None = None, key: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    """({param: fixed value}, {param: default}) in force for one tool on one endpoint. Switched-off rows are left out."""
    fixed, defaults = {}, {}
    takes = set((provider.get("tools", {}).get(tool) or {}).get("params") or [])
    rows = typed_rows(provider, state, key)
    for k, spec in sorted(rows.items(), key=lambda kv: kv[0].startswith("*.")):  # a row for this one tool wins over "every tool"
        t, _, param = k.partition(".")
        if t == "*":
            if param not in takes or f"{tool}.{param}" in rows:
                continue
        elif t != tool:
            continue
        if spec.get("enabled") is False:
            fixed.pop(param, None); defaults.pop(param, None)
            continue
        if "value" in spec:
            fixed[param] = spec["value"]; defaults.pop(param, None)
        elif "default" in spec:
            defaults[param] = spec["default"]; fixed.pop(param, None)
    return fixed, defaults


def fixed_for_tool(provider: dict, tool: str) -> dict[str, Any]:
    """{param: value} typed by hand for one tool's parameters, as the backend alone defines them."""
    return typed_for(provider, tool)[0]


def defaults_for_tool(provider: dict, tool: str) -> dict[str, Any]:
    """{param: default} typed by hand for one tool's parameters, as the backend alone defines them."""
    return typed_for(provider, tool)[1]


def effective_values(state: dict, key: str) -> list[dict]:
    """The typed values in force on one endpoint, one row per backend parameter, for the gateway page."""
    changes_all = (state.get("endpoint_settings", {}).get(key) or {}).get("values") or {}
    out = []
    for p in backends_for(state, key):
        base = {k: spec for k, spec in (p.get("comes_from") or {}).items() if "value" in spec or "default" in spec}
        changes = changes_all.get(p["id"]) or {}
        for k, spec in typed_rows(p, state, key).items():
            tool, _, param = k.partition(".")
            inherited = base.get(k)
            out.append({"backend": p["id"], "backend_name": p["name"], "tool": tool, "alias": (p["tools"].get(tool) or {}).get("alias") or "",
                        "tools_taking": sum(1 for r in p["tools"].values() if r.get("enabled") and param in (r.get("params") or [])) if tool == "*" else 1,
                        "param": param, "kind": "value" if "value" in spec else "default", "value": spec.get("value", spec.get("default")),
                        "enabled": spec.get("enabled") is not False, "inherited": inherited is not None,
                        "backend_value": None if inherited is None else inherited.get("value", inherited.get("default")),
                        "backend_kind": None if inherited is None else ("value" if "value" in inherited else "default"),
                        "backend_enabled": None if inherited is None else inherited.get("enabled") is not False,
                        "changed": k in changes})
    out.sort(key=lambda r: (r["backend_name"], r["tool"], r["param"]))
    return out


def origin_hints(provider: dict, tool: str) -> dict[str, str]:
    """{param: 'Get it from listBots (field id).'} for a tool's parameters that have a confirmed origin."""
    out = {}
    for key, spec in (provider.get("comes_from") or {}).items():
        t, _, param = key.partition(".")
        if t == tool and spec.get("tool"):
            where = f" (field {spec['field']})" if spec.get("field") else ""
            out[param] = f"Get it from {shown_name(provider, spec['tool'])}{where}; do not ask the user for it."
    return out


def missing_origin_hint(provider: dict, tool: str, arguments: dict) -> str | None:
    """What to call first when a parameter with a known origin was not given."""
    for key, spec in (provider.get("comes_from") or {}).items():
        t, _, param = key.partition(".")
        if t == tool and spec.get("tool") and arguments.get(param) in (None, ""):
            return f"'{shown_name(provider, tool)}' needs {param}: call {shown_name(provider, spec['tool'])} first and use its {spec.get('field') or 'result'}."
    return None


# --- learning from real calls --------------------------------------------------------------
SESSION_TTL = 3600
MAX_SESSIONS = 500
_sessions: dict[str, dict] = {}  # session id -> {"at": time, "values": {value: (backend, tool, field)}}


def _scalars(node: Any, path: str = "", depth: int = 0, out: dict | None = None) -> dict[str, str]:
    """{value: field} for every id-like scalar in a result, to a modest depth."""
    out = {} if out is None else out
    if depth > 4:
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            _scalars(v, str(k), depth + 1, out)
    elif isinstance(node, list):
        for v in node[:50]:
            _scalars(v, path, depth + 1, out)
    elif isinstance(node, (str, int)) and not isinstance(node, bool):
        text = str(node)
        if 3 <= len(text) <= 80 and path:
            out.setdefault(text, path)
    return out


def _prune() -> None:
    now = time.time()
    for sid in [s for s, rec in _sessions.items() if now - rec["at"] > SESSION_TTL]:
        _sessions.pop(sid, None)
    while len(_sessions) > MAX_SESSIONS:
        _sessions.pop(next(iter(_sessions)))


def remember(session: str, backend: str, tool: str, result: Any) -> None:
    """Note the values a tool returned, so a later call using one of them reveals where it came from."""
    if not session or result is None:
        return
    _prune()
    rec = _sessions.setdefault(session, {"at": time.time(), "values": {}})
    rec["at"] = time.time()
    for value, field in _scalars(result).items():
        rec["values"].setdefault(value, (backend, tool, field))
    if len(rec["values"]) > 5000:
        rec["values"] = dict(list(rec["values"].items())[-3000:])


def observe(state: dict, session: str, backend: str, tool: str, arguments: dict) -> bool:
    """Record every argument whose value an earlier tool of this session produced. Returns True when state changed."""
    rec = _sessions.get(session) if session else None
    if not rec:
        return False
    changed = False
    for param, value in arguments.items():
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        hit = rec["values"].get(str(value))
        if not hit or hit[:2] == (backend, tool):
            continue
        src_backend, src_tool, field = hit
        provider = state["providers"].get(backend)
        if provider is None:
            continue
        learned = provider.setdefault("learned", {})
        origin = f"{src_tool}.{field}" if src_backend == backend else f"{src_backend}:{src_tool}.{field}"
        entry = learned.setdefault(f"{tool}.{param}", {})
        entry[origin] = entry.get(origin, 0) + 1
        changed = True
    return changed


def session_id() -> str:
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        return request.headers.get("mcp-session-id") or (request.scope.get("state") or {}).get("principal", {}).get("token_id") or ""
    except Exception:  # noqa: BLE001 - no request (stdio, tests): nothing to learn from
        return ""


# --- workflows: a fixed sequence published as one tool ---------------------------------------
WORKFLOW_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,50}$")
_TEMPLATE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def parse_workflow(spec: dict) -> dict:
    """A workflow from the portal's form. Raises ValueError with a reason a person can act on."""
    name = str(spec.get("name") or "").strip()
    if not WORKFLOW_ID.match(name):
        raise ValueError("a workflow name starts with a letter and uses letters, digits and _ only")
    inputs: dict[str, dict] = {}
    raw_inputs = spec.get("inputs") or {}
    for k, v in (raw_inputs.items() if isinstance(raw_inputs, dict) else [(i.get("name"), i) for i in raw_inputs if isinstance(i, dict)]):
        k = str(k or "").strip()
        if not k:
            continue
        desc = v.get("description", "") if isinstance(v, dict) else str(v or "")
        inputs[k] = {"type": (v.get("type") if isinstance(v, dict) else None) or "string", "description": str(desc)[:300],
                     "required": bool(v.get("required", True)) if isinstance(v, dict) else True}
    steps = []
    for i, s in enumerate(spec.get("steps") or []):
        if not isinstance(s, dict) or not str(s.get("tool") or "").strip():
            raise ValueError(f"step {i + 1} needs a tool")
        args = s.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError:
                raise ValueError(f"step {i + 1}: arguments must be JSON") from None
        if not isinstance(args, dict):
            raise ValueError(f"step {i + 1}: arguments must be a JSON object")
        steps.append({"tool": str(s["tool"]).strip(), "args": args})
    if not steps:
        raise ValueError("a workflow needs at least one step")
    return {"name": name, "description": " ".join(str(spec.get("description") or "").split())[:600] or f"Runs {len(steps)} steps in order.",
            "inputs": inputs, "steps": steps, "output": str(spec.get("output") or "").strip()}


def workflow_schema(wf: dict) -> dict:
    props = {k: {"type": v.get("type", "string"), "description": v.get("description", "")} for k, v in (wf.get("inputs") or {}).items()}
    required = [k for k, v in (wf.get("inputs") or {}).items() if v.get("required", True)]
    return {"type": "object", "properties": props, "required": required}


def _lookup(scope: dict, path: str) -> Any:
    """`input.question`, `steps.0.data.0.id`, `steps[1].payload.sessionId` against the run's scope."""
    cur: Any = scope
    for part in [p for p in re.split(r"[.\[\]]+", path.strip()) if p]:
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def render(value: Any, scope: dict) -> Any:
    """Fill {{...}} references in a step's arguments. A lone reference keeps its type; text gets substituted."""
    if isinstance(value, str):
        m = _TEMPLATE.fullmatch(value.strip())
        if m:
            return _lookup(scope, m.group(1))
        return _TEMPLATE.sub(lambda mm: "" if _lookup(scope, mm.group(1)) is None else str(_lookup(scope, mm.group(1))), value)
    if isinstance(value, dict):
        return {k: render(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, scope) for v in value]
    return value


def workflows_for(state: dict, key: str) -> list[dict]:
    """The workflows an endpoint offers: its own, then each served backend's, with step tools prefixed as on that endpoint.

    A backend's workflows name its own tools plainly; on the shared endpoint and on
    named gateways those tools carry the backend's prefix, on the backend's own
    standalone endpoint they do not. An endpoint's own workflow wins a name clash.
    """
    own = list((state.get("endpoint_settings", {}).get(key) or {}).get("workflows") or [])
    names = {w["name"] for w in own}
    standalone = bool(key) and key not in state["gateways"]
    for p in backends_for(state, key):
        prefix = "" if standalone else (p.get("tool_prefix") or p["id"].replace("-", "_") + "_")
        for wf in p.get("workflows") or []:
            if wf["name"] in names:
                continue
            names.add(wf["name"])
            own.append({**wf, "backend": p["id"], "steps": [{**s, "tool": prefix + s["tool"]} for s in wf["steps"]]})
    return own


def parse_backend_workflows(value: Any, provider: dict) -> list[dict]:
    """Workflows stored on a backend: step tools must be its own tools (a stored name or an alias)."""
    flows, names = [], set()
    for spec in value or []:
        wf = parse_workflow(spec if isinstance(spec, dict) else {})
        if wf["name"] in names:
            raise ValueError(f"two workflows are named {wf['name']}")
        for i, step in enumerate(wf["steps"]):
            real = real_tool_name(provider, step["tool"])
            if real not in provider.get("tools", {}):
                raise ValueError(f"step {i + 1}: '{step['tool']}' is not a tool of this backend")
            step["tool"] = real
        names.add(wf["name"])
        flows.append(wf)
    return flows


# --- what the model is told at connect time --------------------------------------------------
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
        takes = {q for row in p.get("tools", {}).values() if row.get("enabled") for q in row.get("params") or []}
        filled |= set(bound_values(p, user_id, claims, source, state, key)) & takes
        for t, row in p["tools"].items():
            if row.get("enabled"):
                filled |= set(typed_for(p, t, state, key)[0])
        notes = clean_instructions(p.get("instructions"))
        if notes:
            prefix = "" if standalone else f" (tools named `{p.get('tool_prefix') or p['id'].replace('-', '_') + '_'}*`)"
            parts.append(f"## {p['name']}{prefix}\n{notes}")
    flows = workflows_for(state, key)
    if flows:
        parts.append("Optional shortcuts, each a single call that runs several tools in the right order: " +
                     "; ".join(f"{w['name']} ({w['description']})" for w in flows) +
                     ". Use one when it matches what the user wants; otherwise pick the individual tools yourself.")
    if filled:
        parts.append("The gateway fills in these parameters from the signed-in user or fixed settings, so they do not appear in the tools and "
                     f"must never be asked for: {', '.join(sorted(filled))}.")
    return "\n\n".join(parts)[: MAX_INSTRUCTIONS * 4]
