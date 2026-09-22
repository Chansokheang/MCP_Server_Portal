"""Registry gateway: serves every provider published in the portal.

Two kinds of backend sit behind it:

  * ``openapi``: the portal stored an OpenAPI spec; FastMCP turns it into tools.
  * ``mcp``: an MCP server that already exists; its tools are proxied.

Both are mounted under the provider id and wrapped in governance the backend
may lack:

  * bearer auth on the gateway (portal-issued agent tokens)
  * tool policy from the portal (enabled, allowed roles)
  * company scoping: arguments naming a company must match the caller's
    token, and records belonging to other companies are removed from results
  * an audit entry for every call

Endpoints:

  /mcp            every published provider, tools prefixed with the provider id
  /mcp/<id>       one provider on its own ("deployed as an MCP server" in the
                  portal), tool names unprefixed; 404 until it is deployed

Upstream auth follows the provider's auth mode: "bearer" sends the stored
service token, "network" and "open" send nothing.

Run:
    uv run python -m bizplay_mcp.registry_gateway                         # stdio
    uv run python -m bizplay_mcp.registry_gateway --transport http --port 8002
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any, Callable

import httpx2
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.providers.openapi import OpenAPIProvider
from fastmcp.server.providers.proxy import ProxyClient, ProxyProvider
from fastmcp.tools import Tool
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations

from . import guidance, login_auth, audit, oauth, policy_store, specs
from .auth import claims_for, current_principal, touch_token

TransportFactory = Callable[[dict], httpx2.AsyncBaseTransport | None]
# (provider record, headers for this call) -> fastmcp Client to the backend
McpClientFactory = Callable[[dict, dict[str, str]], Any]


async def _inject_user_token(request: httpx2.Request) -> None:
    """httpx event hook: send the calling user's own token when the gateway holds one."""
    token = oauth.upstream_token.get()
    if token:
        request.headers["Authorization"] = f"Bearer {token}"


def _login_hooks(provider: dict) -> dict:
    """httpx event hooks for a login-endpoint backend: send the token its way, forget it on 401."""
    pid = provider["id"]

    async def on_request(request: httpx2.Request) -> None:
        token = oauth.upstream_token.get()
        if token:
            request.headers.update(login_auth.header_for(policy_store.load()["providers"].get(pid, provider), token))

    async def on_response(response: httpx2.Response) -> None:
        token = oauth.upstream_token.get()
        if response.status_code == 401 and token:
            state = policy_store.load()
            if login_auth.invalidate(state, state["providers"].get(pid, provider), token):
                policy_store.save(state)

    return {"request": [on_request], "response": [on_response]}


class UpstreamProxyClient(ProxyClient):
    """A proxy client that never forwards the caller's own Authorization header upstream.

    FastMCP's ProxyClient forwards the inbound Authorization header to the
    backend by default. Here the inbound header is the gateway's agent token,
    which means nothing to Flow or any other backend; the gateway decides what
    goes upstream (the user's linked token, a service token, or nothing).
    """

    def __init__(self, transport, **kwargs) -> None:
        super().__init__(transport, **kwargs)
        from dataclasses import replace
        from fastmcp.client.transports.base import TransportOptions
        self._transport_options = replace(self._transport_options or TransportOptions(), forward_incoming_headers=False)


class ResilientProxyProvider(ProxyProvider):
    """A proxied MCP server that cannot be reached lists no tools instead of failing the whole gateway.

    A backend in OAuth mode refuses anonymous callers; until someone links an
    account there is no token to list its tools with. `prepare` fetches (and
    refreshes) such a token right before a listing, so an expired one after a
    restart or an idle hour does not make the backend's tools vanish. A failed
    listing is not cached: the next request tries again.
    """

    def __init__(self, client_factory, *, prepare=None, cache_ttl: float | None = None) -> None:
        super().__init__(client_factory, cache_ttl=cache_ttl)
        self._prepare = prepare

    async def _list_tools(self) -> Sequence[Any]:
        reset = None
        try:
            # A user's call in flight already carries their token; only a bare listing needs one.
            if self._prepare and oauth.upstream_token.get() is None:
                token = await self._prepare()
                if token:
                    reset = oauth.upstream_token.set(token)
            return await super()._list_tools()
        except Exception:  # noqa: BLE001 - connection, auth, or protocol failure: same outcome
            return []
        finally:
            if reset is not None:
                oauth.upstream_token.reset(reset)


def _parsed_text(result: ToolResult) -> Any:
    """A JSON result that came back as text (MCP servers without structured output), or None."""
    for block in result.content or []:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text[:1] in "[{":
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None
    return None


def namespace_for(provider_id: str) -> str:
    return provider_id.replace("-", "_")


def _request_state() -> dict:
    try:
        return get_http_request().scope.get("state") or {}
    except RuntimeError:
        return {}


def standalone_provider() -> str | None:
    """The provider id when the request came in on /mcp/<id>, else None."""
    return _request_state().get("standalone")


def gateway_scope() -> set[str] | None:
    """The provider ids a named gateway (/mcp/<gateway id>) serves, else None for everything."""
    ids = _request_state().get("gateway_providers")
    return set(ids) if ids is not None else None


class GovernanceMiddleware(Middleware):
    """Policy, company scoping, and audit for every registered provider.

    Also keeps the gateway in step with the portal: before answering, it checks
    whether the stored registry changed and adds any newly published API, so
    registering one needs no restart.

    On a standalone endpoint (/mcp/<id>) only that provider's tools are listed,
    without the prefix, and calls are mapped back to the prefixed tool.
    """

    def __init__(self, registry: "ProviderRegistry") -> None:
        self.registry = registry

    @property
    def prefixes(self) -> dict[str, str]:
        return self.registry.prefixes

    def split(self, tool_name: str) -> tuple[str, str] | None:
        for prefix, pid in sorted(self.prefixes.items(), key=lambda kv: -len(kv[0])):
            if tool_name.startswith(prefix):
                return pid, tool_name[len(prefix):]
        return None

    async def on_list_tools(self, context: MiddlewareContext, call_next) -> Sequence[Any]:
        self.registry.sync()
        tools = await call_next(context)
        state = policy_store.load()
        principal = current_principal()
        role = principal.claims.get("role", "employee")
        only = standalone_provider()
        scope = gateway_scope()
        key = only or _request_state().get("gateway_key") or ""
        visible = []
        for tool in tools:
            parts = self.split(tool.name)
            if parts is None:
                if only is None:
                    visible.append(tool)
                continue
            if only is not None and parts[0] != only:
                continue
            if scope is not None and parts[0] not in scope:
                continue
            allowed, _ = policy_store.check_tool_access(state, parts[0], parts[1], role, principal.claims)
            if not allowed:
                continue
            provider = state["providers"][parts[0]]
            policy = provider["tools"][parts[1]]
            # Clients see the name chosen in the portal, prefixed like any other (plain on a standalone endpoint).
            shown = policy.get("alias") or parts[1]
            update: dict[str, Any] = {"name": shown} if only else ({"name": tool.name[: len(tool.name) - len(parts[1])] + shown} if shown != parts[1] else {})
            # Parameters the gateway fills in (caller identity, fixed values) leave the schema; defaults and
            # origins ("get it from listBots") are written into it, where the model reads them when choosing.
            hidden, defaults = guidance.resolve_sources(guidance.sources_for(provider, state, key), principal.user_id, principal.claims, principal.source)
            shaped = guidance.shape_schema(tool.parameters, set(hidden), defaults, guidance.origin_hints(provider, parts[1]))
            if shaped is not tool.parameters:
                update["parameters"] = shaped
            # Tell clients (and any gateway proxying this one) which tools only read.
            if policy["kind"] == "read" and tool.annotations is None:
                update["annotations"] = ToolAnnotations(read_only_hint=True)
            # A description written in the portal replaces whatever the spec or server said.
            if policy.get("description"):
                update["description"] = policy["description"]
            visible.append(tool.model_copy(update=update) if update else tool)
        # Workflows defined on this endpoint: one tool each, run by the gateway in order.
        for wf in guidance.workflows_for(state, key):
            visible.append(Tool(name=wf["name"], description=wf["description"], parameters=guidance.workflow_schema(wf)))
        return visible

    def _instructions(self) -> str:
        """What the model is told about this endpoint, for this caller. Never raises: guidance is a help."""
        try:
            self.registry.sync()
            principal = current_principal()
            key = standalone_provider() or _request_state().get("gateway_key") or ""
            return guidance.compose_instructions(policy_store.load(), key, principal.user_id, principal.claims, principal.source)
        except Exception:  # noqa: BLE001
            return ""

    async def on_initialize(self, context: MiddlewareContext, call_next):
        """Handshake-era clients (claude.ai, ChatGPT today) read instructions from the initialize result."""
        result = await call_next(context)
        text = self._instructions() if result is not None else ""
        if text:
            result.instructions = text
        return result

    async def on_discover(self, context: MiddlewareContext, call_next):
        """Newer clients connect with server/discover instead; the same text goes there."""
        result = await call_next(context)
        text = self._instructions()
        if text:
            if isinstance(result, dict):
                result = {**result, "instructions": text}
            elif result is not None:
                result.instructions = text
        return result

    async def run_workflow(self, wf: dict, arguments: dict, context: MiddlewareContext, call_next) -> ToolResult:
        """Run a workflow's steps in order through this same middleware, so every step is governed and audited."""
        missing = [k for k, v in (wf.get("inputs") or {}).items() if v.get("required", True) and arguments.get(k) in (None, "")]
        if missing:
            raise ToolError(f"{wf['name']} needs: {', '.join(missing)}")
        scope: dict[str, Any] = {"input": arguments, "steps": []}
        last: ToolResult | None = None
        for i, step in enumerate(wf["steps"]):
            raw = step.get("args") or {}
            args = guidance.render(raw, scope)
            # A reference to an earlier step that resolved to nothing: say so, instead of letting the step fail obscurely.
            empty = [k for k, v in args.items() if v is None and isinstance(raw.get(k), str) and "{{steps." in raw[k]]
            if empty:
                prev = wf["steps"][i - 1]["tool"] if i else "the input"
                raise ToolError(f"{wf['name']} stopped at step {i + 1} ({step['tool']}): {prev} returned nothing to fill {', '.join(empty)}. "
                                f"The previous step's result was empty for this user or company.")
            args = {k: v for k, v in args.items() if v is not None}
            step_ctx = context.copy(message=context.message.model_copy(update={"name": step["tool"], "arguments": args}))
            try:
                last = await self.on_call_tool(step_ctx, call_next)
            except ToolError as exc:
                raise ToolError(f"{wf['name']}, step {i + 1} ({step['tool']}): {exc}") from None
            scope["steps"].append(last.structured_content if last.structured_content is not None
                                  else "\n".join(getattr(c, "text", "") for c in (last.content or [])))
        if wf.get("output"):
            picked = guidance.render("{{" + wf["output"] + "}}", scope)
            return ToolResult(structured_content=picked if isinstance(picked, dict) else {"result": picked})
        return last if last is not None else ToolResult(structured_content={})

    async def on_call_tool(self, context: MiddlewareContext, call_next) -> ToolResult:
        self.registry.sync()
        name = context.message.name
        arguments = dict(context.message.arguments or {})
        principal = current_principal()
        endpoint_key = standalone_provider() or _request_state().get("gateway_key") or ""
        for wf in guidance.workflows_for(policy_store.load(), endpoint_key):
            if wf["name"] == name:
                audit.record(principal.user_id, name, arguments, "ok", f"workflow, {len(wf['steps'])} step(s)", via=principal.source)
                return await self.run_workflow(wf, arguments, context, call_next)
        role = principal.claims.get("role", "employee")
        company = str(principal.claims.get("company") or "")
        via = principal.source

        only = standalone_provider()
        if only is not None:
            # Plain names belong to this provider; another provider's prefixed
            # name is refused rather than silently prefixed again.
            parts = self.split(name)
            if parts is not None and parts[0] != only:
                reason = f"'{name}' is not served on the standalone endpoint of '{only}'"
                audit.record(principal.user_id, name, arguments, "denied", reason, via=via)
                raise ToolError(f"Access denied: {reason}")
            if parts is None:
                name = namespace_for(only) + "_" + name
                context = context.copy(message=context.message.model_copy(update={"name": name}))
        parts = self.split(name)
        if parts is None:
            return await call_next(context)
        pid, op = parts
        # A name chosen in the portal maps back to the tool FastMCP serves.
        known = policy_store.load()["providers"].get(pid)
        if known is not None:
            real = guidance.real_tool_name(known, op)
            if real != op:
                name, op = name[: len(name) - len(op)] + real, real
                context = context.copy(message=context.message.model_copy(update={"name": name}))
        scope = gateway_scope()
        if scope is not None and pid not in scope:
            reason = f"'{name}' is not part of this gateway"
            audit.record(principal.user_id, name, arguments, "denied", reason, via=via)
            raise ToolError(f"Access denied: {reason}")

        state = policy_store.load()
        allowed, reason = policy_store.check_tool_access(state, pid, op, role, principal.claims)
        if not allowed:
            audit.record(principal.user_id, name, arguments, "denied", reason, via=via)
            raise ToolError(f"Access denied: {reason}")

        # Parameter sources: caller identity and fixed values replace whatever the model sent; defaults fill gaps.
        provider = state["providers"][pid]
        hidden, defaults = guidance.resolve_sources(guidance.sources_for(provider, state, endpoint_key), principal.user_id, principal.claims, principal.source)
        takes = set((provider["tools"].get(op) or {}).get("params") or [])
        fill = {k: v for k, v in hidden.items() if k in takes}
        fill.update({k: v for k, v in defaults.items() if k in takes and arguments.get(k) in (None, "")})
        if fill and any(arguments.get(k) != v for k, v in fill.items()):
            arguments.update(fill)
            context = context.copy(message=context.message.model_copy(update={"arguments": arguments}))
        # A parameter with a known origin but no value: say what to call first, before the backend fails obscurely.
        hint = guidance.missing_origin_hint(provider, op, arguments)
        if hint:
            audit.record(principal.user_id, name, arguments, "denied", hint, via=via)
            raise ToolError(hint)
        # Learn from real calls: an argument that an earlier tool of this session returned reveals where it comes from.
        session = guidance.session_id()
        if session and guidance.observe(state, session, pid, op, arguments):
            policy_store.save(state)

        # OAuth backends get the calling user's own token, never a shared one.
        user_token = None
        if provider.get("auth_mode") == "oauth":
            try:
                user_token = await oauth.access_token_for(state, provider, principal.user_id)
            except oauth.OAuthError as exc:
                audit.record(principal.user_id, name, arguments, "error", f"token refresh failed: {exc}"[:200], via=via)
                raise ToolError(f"{provider['name']}: your linked account needs to be connected again ({exc})") from None
            if not user_token:
                reason = (f"user '{principal.user_id}' has not connected a {provider['name']} account. "
                          f"Link it in the Bizplay MCP portal: open {provider['name']}, then Connect account.")
                audit.record(principal.user_id, name, arguments, "denied", reason, via=via)
                raise ToolError(f"Account not connected: {reason}")
        elif provider.get("auth_mode") == "login":
            # Login-endpoint backends: the caller's own sign-in when per user, else the service account's.
            try:
                user_token = await login_auth.token_for(state, provider, principal.user_id)
            except login_auth.LoginError as exc:
                audit.record(principal.user_id, name, arguments, "error", f"sign-in failed: {exc}"[:200], via=via)
                raise ToolError(f"{provider['name']}: sign-in failed ({exc})") from None
            if not user_token:
                reason = (f"user '{principal.user_id}' has not connected a {provider['name']} account. "
                          f"Link it in the Bizplay MCP portal: My access, then Connect on {provider['name']}.")
                audit.record(principal.user_id, name, arguments, "denied", reason, via=via)
                raise ToolError(f"Account not connected: {reason}")

        # Company scoping on inputs: a caller may only name their own company.
        # With no company on the caller (token requirement switched off) there is
        # nothing to scope to, so the check is skipped rather than refusing every
        # call. Set BIZPLAY_COMPANY to scope an anonymous gateway to one company.
        for key in policy_store.COMPANY_KEYS if company else ():
            if key in arguments and arguments[key] is not None and str(arguments[key]) != company:
                reason = f"{key}={arguments[key]} is not the caller's company"
                audit.record(principal.user_id, name, arguments, "denied", reason, via=via)
                raise ToolError(f"Access denied: {reason}")

        token_scope = oauth.upstream_token.set(user_token)
        try:
            result = await call_next(context)
        except ToolError as exc:
            audit.record(principal.user_id, name, arguments, "error", str(exc)[:200], via=via)
            raise
        except Exception as exc:
            # A backend that is down or misbehaving must read as that, not as a gateway fault.
            audit.record(principal.user_id, name, arguments, "error", f"{type(exc).__name__}: {exc}"[:200], via=via)
            raise ToolError(f"{provider['name']} did not answer: {type(exc).__name__}: {str(exc)[:160]}") from exc
        finally:
            oauth.upstream_token.reset(token_scope)

        # Company scoping on outputs: drop other companies' records.
        removed = 0
        if company and result.structured_content is not None:
            scoped, removed = policy_store.company_scope(result.structured_content, company)
            if removed:
                result = ToolResult(structured_content=scoped)
        audit.record(principal.user_id, name, arguments, "ok",
                     f"{removed} record(s) outside company {company} removed" if removed else "", via=via)
        if session:
            guidance.remember(session, pid, op, result.structured_content if result.structured_content is not None
                              else _parsed_text(result))
        return result


class ProviderRegistry:
    """Keeps the gateway's tools in step with what the portal has published.

    FastMCP can add a provider at runtime but not remove one, so an API that is
    unpublished stays loaded and is instead hidden and refused by the policy
    check. Adding is what matters here: registering an API in the portal makes
    its tools appear on the next request, with no restart.
    """

    def __init__(self, gateway: FastMCP, transport_factory: TransportFactory | None = None,
                 mcp_client_factory: McpClientFactory | None = None) -> None:
        self.gateway = gateway
        self.transport_factory = transport_factory
        self.mcp_client_factory = mcp_client_factory
        self.prefixes: dict[str, str] = {}
        self._loaded: set[str] = set()
        self._stamp: tuple[float, int] | None = None

    def _changed(self) -> bool:
        try:
            stat = policy_store.state_path().stat()
        except OSError:
            return True
        stamp = (stat.st_mtime, stat.st_size)
        if stamp == self._stamp:
            return False
        self._stamp = stamp
        return True

    def sync(self, force: bool = False) -> None:
        if not force and not self._changed():
            return
        state = policy_store.load()
        dirty = False
        for provider in policy_store.published_registry_providers(state):
            if provider["id"] in self._loaded:
                continue
            dirty |= self._add(provider, state)
        if dirty:
            policy_store.save(state)
            self._changed()  # our own write is not a change worth reloading

    @staticmethod
    def _upstream_headers(provider: dict, state: dict) -> dict[str, str]:
        if provider.get("auth_mode", "bearer") != "bearer":
            return {}
        secret = state["credentials"].get(provider.get("upstream_credential_id", ""), {}).get("secret", "")
        return {"Authorization": f"Bearer {secret}"} if secret else {}

    def _add(self, provider: dict, state: dict) -> bool:
        """Mount one provider. Returns True when the stored state was corrected."""
        headers = self._upstream_headers(provider, state)
        ns = namespace_for(provider["id"])
        pid = provider["id"]
        changed = False
        if provider.get("kind") == "mcp":
            def call_headers() -> dict[str, str]:
                # The user's token for the call in flight; for listing tool metadata,
                # any linked user's token will do (the list is not per user).
                token = oauth.upstream_token.get()
                mode = provider.get("auth_mode")
                if token is None and mode == "oauth":
                    token = oauth.any_token(policy_store.load(), pid)
                if not token:
                    return dict(headers)
                if mode == "login":
                    return {**headers, **login_auth.header_for(provider, token)}
                return {**headers, "Authorization": f"Bearer {token}"}

            if self.mcp_client_factory:
                factory = lambda: self.mcp_client_factory(provider, call_headers())  # noqa: E731
            else:
                factory = lambda: UpstreamProxyClient(specs.mcp_transport(provider["base_url"], call_headers()))  # noqa: E731

            async def prepare() -> str | None:
                fresh = policy_store.load()
                current = fresh["providers"].get(pid, provider)
                if current.get("auth_mode") == "login":
                    return await login_auth.listing_token(fresh, current)
                return await oauth.listing_token(fresh, current)

            self.gateway.add_provider(
                ResilientProxyProvider(factory, prepare=prepare if provider.get("auth_mode") in ("oauth", "login") else None), namespace=ns)
        else:
            # Older registrations stored raw operationIds; serve what FastMCP names.
            if specs.reconcile_tool_names(provider):
                changed = True
            client = httpx2.AsyncClient(
                base_url=provider["base_url"], headers=headers, timeout=30.0,
                transport=self.transport_factory(provider) if self.transport_factory else None,
                event_hooks=_login_hooks(provider) if provider.get("auth_mode") == "login" else {"request": [_inject_user_token]},
            )
            # validate_output=False: real-world specs often drift from real responses
            # (e.g. Spring's "200 OK" status enum vs an actual "OK"). A strict output
            # schema would make the MCP client reject perfectly good data.
            self.gateway.add_provider(
                OpenAPIProvider(openapi_spec=specs.gateway_spec(provider["spec"]), client=client, validate_output=False),
                namespace=ns,
            )
        self.prefixes[ns + "_"] = provider["id"]
        self._loaded.add(provider["id"])
        return changed


def build_registry_gateway(transport_factory: TransportFactory | None = None,
                           mcp_client_factory: McpClientFactory | None = None) -> FastMCP:
    gateway = FastMCP(
        name="Bizplay Registry Gateway",
        instructions=(
            "Tools from APIs and MCP servers registered in the Bizplay MCP portal. On the shared "
            "endpoint tool names are prefixed with the provider id. Results are limited to the "
            "caller's own company."
        ),
        # Authentication is enforced per endpoint by RegistryASGI (token requirement and
        # entitlement can differ per gateway and change without a restart).
        auth=None,
    )
    registry = ProviderRegistry(gateway, transport_factory, mcp_client_factory)
    registry.sync(force=True)
    gateway.add_middleware(GovernanceMiddleware(registry))
    return gateway


class RegistryASGI:
    """The gateway over HTTP: /mcp for everything, /mcp/<id> for one deployed provider.

    A standalone path is rewritten to the single MCP route and the provider id
    is left in the request state, where GovernanceMiddleware reads it.
    """

    def __init__(self, gateway: FastMCP) -> None:
        self.gateway = gateway
        # Public hosts vary (IP, domain, tunnel), so host/origin checks are off.
        self.inner = gateway.http_app(path="/mcp", host_origin_protection=False)

    @property
    def lifespan(self):
        return self.inner.lifespan

    @staticmethod
    async def _reply(send, status: int, body: dict, extra_headers=()) -> None:
        raw = json.dumps(body).encode()
        headers = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode()), *extra_headers]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": raw})

    @staticmethod
    def _origin(headers: dict, state: dict) -> str:
        """Where clients find this gateway's own sign-in: the public address if set, else the address they used."""
        base = (state["security"].get("public_mcp_url") or "").strip()
        if base:
            from urllib.parse import urlsplit
            parts = urlsplit(base)
            return f"{parts.scheme}://{parts.netloc}"
        proto = headers.get(b"x-forwarded-proto", b"http").decode(errors="ignore").split(",")[0].strip() or "http"
        host = (headers.get(b"x-forwarded-host") or headers.get(b"host") or b"127.0.0.1").decode(errors="ignore").split(",")[0].strip()
        return f"{proto}://{host}"

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            state = policy_store.load()
            headers = dict(scope.get("headers") or {})
            key, extra = "", {}
            if path.startswith("/mcp/") and path.strip("/") != "mcp":
                key = path[len("/mcp/"):].strip("/")
                p = state["providers"].get(key)
                g = state["gateways"].get(key)
                if p and p.get("status") == "published" and p.get("standalone"):
                    extra = {"standalone": key}
                elif g:
                    extra = {"gateway_providers": list(g.get("providers") or []), "gateway_key": key}
                else:
                    message = (f"Nothing is served at /mcp/{key}. It is neither a deployed MCP server "
                               "nor a named gateway; use /mcp for everything.")
                    accept = dict(scope.get("headers") or {}).get(b"accept", b"").decode(errors="ignore")
                    if "text/html" in accept:
                        from portal.app import error_html  # browsers get the portal's page, agents get JSON
                        body = error_html(404, "No MCP server here", message, path).encode()
                        ctype = b"text/html; charset=utf-8"
                    else:
                        body = json.dumps({"error": message}).encode()
                        ctype = b"application/json"
                    await send({"type": "http.response.start", "status": 404,
                                "headers": [(b"content-type", ctype), (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                    return
            if (path == "/mcp" or key) and scope.get("method") == "OPTIONS":
                # A browser-based client's preflight: answer it, never demand a token for it.
                await send({"type": "http.response.start", "status": 204, "headers": [
                    (b"access-control-allow-origin", b"*"), (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
                    (b"access-control-allow-headers", b"Authorization, Content-Type, Accept, MCP-Protocol-Version, Mcp-Session-Id"),
                    (b"access-control-expose-headers", b"Mcp-Session-Id, WWW-Authenticate"), (b"access-control-max-age", b"600")]})
                await send({"type": "http.response.body", "body": b""})
                return
            if path == "/mcp" or key:
                # Who is calling: a portal-issued agent token, if one is presented.
                auth_header = headers.get(b"authorization", b"").decode(errors="ignore")
                scheme, _, token = auth_header.partition(" ")
                record = policy_store.find_agent_token(state, token.strip()) if scheme.lower() == "bearer" and token.strip() else None
                policy = policy_store.endpoint_policy(state, key)
                # The challenge points at the protected-resource document (RFC 9728), which is how
                # claude.ai, ChatGPT and other MCP clients find this gateway's own OAuth sign-in.
                metadata = f"{self._origin(headers, state)}/.well-known/oauth-protected-resource/mcp" + (f"/{key}" if key else "")
                challenge = (b"www-authenticate", f'Bearer realm="bizplay-gateway", resource_metadata="{metadata}"'.encode())
                agent = headers.get(b"user-agent", b"").decode(errors="ignore")
                if auth_header and record is None:
                    policy_store.auth_log(state, "gateway", 401, f"{scheme or 'no scheme'} credential not a valid agent token", path=path, agent=agent)
                    policy_store.save(state)
                    return await self._reply(send, 401, {"error": "invalid or expired agent token"}, [challenge])
                if policy["require_token"] and record is None:
                    policy_store.auth_log(state, "gateway", 401, "no token; challenge sent (a sign-in should follow)", path=path, agent=agent)
                    policy_store.save(state)
                    return await self._reply(send, 401, {"error": "this gateway requires an agent token; issue one in the Bizplay MCP portal"}, [challenge])
                claims = claims_for(record) if record else None
                ok, reason = policy_store.check_endpoint_access(policy, claims)
                if not ok:
                    policy_store.auth_log(state, "gateway", 403, reason, path=path, user=record["sub"] if record else "", agent=agent)
                    policy_store.save(state)
                    return await self._reply(send, 403, {"error": reason})
                if record:
                    touch_token(state, record)
                    extra = {**extra, "principal": claims}
                scope = {**scope, "path": "/mcp", "raw_path": b"/mcp", "state": {**(scope.get("state") or {}), **extra}}
        await self.inner(scope, receive, send)


def build_registry_asgi(gateway: FastMCP | None = None) -> RegistryASGI:
    return RegistryASGI(gateway or build_registry_gateway())


def main() -> None:
    parser = argparse.ArgumentParser(description="Bizplay registry gateway (all published providers)")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    gateway = build_registry_gateway()
    if args.transport == "stdio":
        gateway.run(transport="stdio")
    else:
        import uvicorn

        uvicorn.run(build_registry_asgi(gateway), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
