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
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations

from . import audit, oauth, policy_store, specs
from .auth import current_principal, gateway_auth

TransportFactory = Callable[[dict], httpx2.AsyncBaseTransport | None]
# (provider record, headers for this call) -> fastmcp Client to the backend
McpClientFactory = Callable[[dict, dict[str, str]], Any]


async def _inject_user_token(request: httpx2.Request) -> None:
    """httpx event hook: send the calling user's own token when the gateway holds one."""
    token = oauth.upstream_token.get()
    if token:
        request.headers["Authorization"] = f"Bearer {token}"


class ResilientProxyProvider(ProxyProvider):
    """A proxied MCP server that cannot be reached lists no tools instead of failing the whole gateway.

    A backend in OAuth mode refuses anonymous callers; until someone links an
    account there is no token to list its tools with.
    """

    async def _list_tools(self) -> Sequence[Any]:
        try:
            return await super()._list_tools()
        except Exception:  # noqa: BLE001 - connection, auth, or protocol failure: same outcome
            return []


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
            update: dict[str, Any] = {"name": parts[1]} if only else {}
            # Tell clients (and any gateway proxying this one) which tools only read.
            policy = state["providers"][parts[0]]["tools"][parts[1]]
            if policy["kind"] == "read" and tool.annotations is None:
                update["annotations"] = ToolAnnotations(read_only_hint=True)
            # A description written in the portal replaces whatever the spec or server said.
            if policy.get("description"):
                update["description"] = policy["description"]
            visible.append(tool.model_copy(update=update) if update else tool)
        return visible

    async def on_call_tool(self, context: MiddlewareContext, call_next) -> ToolResult:
        self.registry.sync()
        name = context.message.name
        arguments = dict(context.message.arguments or {})
        principal = current_principal()
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

        # OAuth backends get the calling user's own token, never a shared one.
        provider = state["providers"][pid]
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
                if token is None and provider.get("auth_mode") == "oauth":
                    token = oauth.any_token(policy_store.load(), pid)
                return {**headers, "Authorization": f"Bearer {token}"} if token else dict(headers)

            if self.mcp_client_factory:
                factory = lambda: self.mcp_client_factory(provider, call_headers())  # noqa: E731
            else:
                factory = lambda: ProxyClient(specs.mcp_transport(provider["base_url"], call_headers()))  # noqa: E731
            self.gateway.add_provider(ResilientProxyProvider(factory), namespace=ns)
        else:
            # Older registrations stored raw operationIds; serve what FastMCP names.
            if specs.reconcile_tool_names(provider):
                changed = True
            client = httpx2.AsyncClient(
                base_url=provider["base_url"], headers=headers, timeout=30.0,
                transport=self.transport_factory(provider) if self.transport_factory else None,
                event_hooks={"request": [_inject_user_token]},
            )
            # validate_output=False: real-world specs often drift from real responses
            # (e.g. Spring's "200 OK" status enum vs an actual "OK"). A strict output
            # schema would make the MCP client reject perfectly good data.
            self.gateway.add_provider(
                OpenAPIProvider(openapi_spec=provider["spec"], client=client, validate_output=False),
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
        auth=gateway_auth(),
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

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            path = scope["path"]
            if path.startswith("/mcp/") and path.strip("/") != "mcp":
                key = path[len("/mcp/"):].strip("/")
                state = policy_store.load()
                p = state["providers"].get(key)
                g = state["gateways"].get(key)
                if p and p.get("status") == "published" and p.get("standalone"):
                    extra = {"standalone": key}
                elif g:
                    extra = {"gateway_providers": list(g.get("providers") or [])}
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
