"""Tool tables for the two kinds of backend the gateway serves.

  * ``openapi``: a REST API described by an OpenAPI spec. FastMCP generates
    the tools; the names it picks are what the portal must store, otherwise
    the policy check refuses tools that exist under a slightly different name
    (operationIds with ``__`` in them are cut at the first ``__``, slugified
    and capped at 56 characters).
  * ``mcp``: an MCP server that already exists. Its tool list is fetched once
    at registration and proxied unchanged.
"""

from __future__ import annotations

import re
from typing import Any

import httpx2
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from fastmcp.server.providers.openapi import OpenAPIProvider


def mcp_transport(url: str, headers: dict[str, str]) -> StreamableHttpTransport | SSETransport:
    """A client transport for whatever remote MCP server the user registered.

    Streamable HTTP is the current standard; servers still on the older SSE
    transport conventionally end their URL in /sse.
    """
    if url.rstrip("/").lower().endswith("/sse"):
        return SSETransport(url, headers=headers)
    return StreamableHttpTransport(url, headers=headers)

# A read verb at the start of the name or after a prefix: getAllCorps, workflow_list_documents.
READ_VERBS = re.compile(r"(^|_)(get|list|search|find|read|describe|fetch|show|query|count|health|check|lookup)", re.I)


def tools_from_spec(spec: dict) -> dict[str, dict]:
    """Tool policy rows keyed by the exact name FastMCP will serve.

    Reads are on, writes and deletes are off until someone chooses them.
    """
    # The provider builds every tool up front; the base URL is never called.
    provider = OpenAPIProvider(openapi_spec=spec, client=httpx2.AsyncClient(base_url="http://spec.invalid"),
                               validate_output=False)
    tools = {}
    for tool in provider._tools.values():  # pinned FastMCP; no public sync accessor for the table
        route = tool._route
        kind = "read" if route.method.upper() == "GET" else "write"
        tools[tool.name] = {
            "kind": kind, "enabled": kind == "read", "roles": ["employee", "manager"],
            "confirm": kind == "write", "summary": route.summary or "",
            "route": f"{route.method.upper()} {route.path}", "operation_id": route.operation_id or "",
            # What the model sees unless the portal overrides it (tool row "description").
            "generated": (tool.description or "").strip(),
        }
    return tools


def reconcile_tool_names(provider: dict) -> list[tuple[str, str]]:
    """Rename stored tool rows to the names FastMCP actually generates.

    Older registrations stored raw operationIds. Rows whose operationId now maps
    to a different generated name are moved, policy intact. Returns the renames.
    """
    spec = provider.get("spec")
    if not spec:
        return []
    generated = tools_from_spec(spec)
    by_operation = {row["operation_id"]: name for name, row in generated.items() if row["operation_id"]}
    renames = []
    for old in list(provider["tools"]):
        if old in generated:
            # Rows from before the portal kept the generated text: fill it in so the admin sees it.
            if not provider["tools"][old].get("generated") and generated[old]["generated"]:
                provider["tools"][old]["generated"] = generated[old]["generated"]
                renames.append((old, old))
            continue
        new = by_operation.get(old)
        if new and new not in provider["tools"]:
            provider["tools"][new] = {**provider["tools"].pop(old), "operation_id": old,
                                      "route": generated[new]["route"]}
            renames.append((old, new))
    return renames


def tools_from_mcp(listed: list[Any]) -> dict[str, dict]:
    """Tool policy rows for tools listed by an existing MCP server.

    ``readOnlyHint`` decides read or write when the server sets it; otherwise
    the name's verb is the best available guess, and the row can be changed on
    the Access Control page.
    """
    tools = {}
    for tool in listed:
        annotations = getattr(tool, "annotations", None)
        hint = getattr(annotations, "read_only_hint", None) if annotations is not None else None
        kind = ("read" if hint else "write") if hint is not None else ("read" if READ_VERBS.search(tool.name) else "write")
        tools[tool.name] = {
            "kind": kind, "enabled": kind == "read", "roles": ["employee", "manager"],
            "confirm": kind == "write", "summary": (tool.description or "").strip().split("\n")[0][:160],
            "route": "MCP tool", "operation_id": tool.name,
            "generated": (tool.description or "").strip(),
        }
    return tools
