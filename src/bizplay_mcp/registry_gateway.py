"""Registry gateway: serves every provider published in the portal.

For each published provider the portal stored an OpenAPI spec. This gateway
turns each spec into MCP tools (FastMCP.from_openapi), mounts them under the
provider id, and wraps every call in governance the upstream API may lack:

  * bearer auth on the gateway (portal-issued agent tokens)
  * tool policy from the portal (enabled, allowed roles)
  * company scoping: arguments naming a company must match the caller's
    token, and records belonging to other companies are removed from results
  * an audit entry for every call

Upstream auth follows the provider's auth mode: "bearer" sends the stored
service token, "network" and "open" send nothing.

Run:
    uv run python -m bizplay_mcp.registry_gateway                         # stdio
    uv run python -m bizplay_mcp.registry_gateway --transport http --port 8002
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from typing import Any, Callable

import httpx2
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.providers.openapi import OpenAPIProvider
from fastmcp.tools.base import ToolResult

from . import audit, policy_store
from .auth import current_principal, gateway_auth

TransportFactory = Callable[[dict], httpx2.AsyncBaseTransport | None]


def namespace_for(provider_id: str) -> str:
    return provider_id.replace("-", "_")


class GovernanceMiddleware(Middleware):
    """Policy, company scoping, and audit for every registered provider.

    Also keeps the gateway in step with the portal: before answering, it checks
    whether the stored registry changed and adds any newly published API, so
    registering one needs no restart.
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
        visible = []
        for tool in tools:
            parts = self.split(tool.name)
            if parts is None:
                visible.append(tool)
                continue
            allowed, _ = policy_store.check_tool_access(state, parts[0], parts[1], role)
            if allowed:
                visible.append(tool)
        return visible

    async def on_call_tool(self, context: MiddlewareContext, call_next) -> ToolResult:
        self.registry.sync()
        name = context.message.name
        arguments = dict(context.message.arguments or {})
        parts = self.split(name)
        if parts is None:
            return await call_next(context)
        pid, op = parts
        principal = current_principal()
        role = principal.claims.get("role", "employee")
        company = str(principal.claims.get("company") or "")
        via = principal.source

        allowed, reason = policy_store.check_tool_access(policy_store.load(), pid, op, role)
        if not allowed:
            audit.record(principal.user_id, name, arguments, "denied", reason, via=via)
            raise ToolError(f"Access denied: {reason}")

        # Company scoping on inputs: a caller may only name their own company.
        # With no company on the caller (token requirement switched off) there is
        # nothing to scope to, so the check is skipped rather than refusing every
        # call. Set BIZPLAY_COMPANY to scope an anonymous gateway to one company.
        for key in policy_store.COMPANY_KEYS if company else ():
            if key in arguments and arguments[key] is not None and str(arguments[key]) != company:
                reason = f"{key}={arguments[key]} is not the caller's company"
                audit.record(principal.user_id, name, arguments, "denied", reason, via=via)
                raise ToolError(f"Access denied: {reason}")

        try:
            result = await call_next(context)
        except Exception as exc:
            audit.record(principal.user_id, name, arguments, "error", str(exc)[:200], via=via)
            raise

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

    def __init__(self, gateway: FastMCP, transport_factory: TransportFactory | None = None) -> None:
        self.gateway = gateway
        self.transport_factory = transport_factory
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
        for provider in policy_store.published_registry_providers(state):
            if provider["id"] in self._loaded:
                continue
            self._add(provider, state)

    def _add(self, provider: dict, state: dict) -> None:
        headers = {}
        if provider.get("auth_mode", "bearer") == "bearer":
            secret = state["credentials"].get(provider.get("upstream_credential_id", ""), {}).get("secret", "")
            if secret:
                headers["Authorization"] = f"Bearer {secret}"
        client = httpx2.AsyncClient(
            base_url=provider["base_url"], headers=headers, timeout=30.0,
            transport=self.transport_factory(provider) if self.transport_factory else None,
        )
        ns = namespace_for(provider["id"])
        # validate_output=False: real-world specs often drift from real responses
        # (e.g. Spring's "200 OK" status enum vs an actual "OK"). A strict output
        # schema would make the MCP client reject perfectly good data.
        self.gateway.add_provider(
            OpenAPIProvider(openapi_spec=provider["spec"], client=client, validate_output=False),
            namespace=ns,
        )
        self.prefixes[ns + "_"] = provider["id"]
        self._loaded.add(provider["id"])


def build_registry_gateway(transport_factory: TransportFactory | None = None) -> FastMCP:
    gateway = FastMCP(
        name="Bizplay Registry Gateway",
        instructions=(
            "Tools generated from APIs registered in the Bizplay MCP portal. Tool names are "
            "prefixed with the provider id. Results are limited to the caller's own company."
        ),
        auth=gateway_auth(),
    )
    registry = ProviderRegistry(gateway, transport_factory)
    registry.sync(force=True)
    gateway.add_middleware(GovernanceMiddleware(registry))
    return gateway


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
        gateway.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
