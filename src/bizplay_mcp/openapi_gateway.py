"""Zero-code option: generate MCP tools straight from the existing API's OpenAPI spec.

No existing API code changes and no per-endpoint wrapper code. FastMCP reads
openapi/bizplay-existing-api.json and turns each operation into an MCP tool
that forwards the call over HTTP.

Trade-off: tools mirror raw endpoints 1:1. There are no per-user permission
checks, no Korean compliance rules, and no audit log. Use it to prototype
quickly, then move the tools you keep into the curated server (server.py).

Run:
    uv run bizplay-mcp-openapi                               # stdio
    uv run bizplay-mcp-openapi --transport http --port 8001  # http://127.0.0.1:8001/mcp
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx2
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi" / "bizplay-existing-api.json"

# Choose which endpoints AI agents may see, without touching the API itself.
ROUTE_MAPS = [
    # Approving money should never be a raw, unguarded tool.
    RouteMap(methods=["POST"], pattern=r".*/decision$", mcp_type=MCPType.EXCLUDE),
]


def build_openapi_gateway(base_url: str | None = None,
                          transport: httpx2.AsyncBaseTransport | None = None) -> FastMCP:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    client = httpx2.AsyncClient(
        base_url=base_url or os.environ.get("BIZPLAY_API_BASE_URL", spec["servers"][0]["url"]),
        headers={"Authorization": f"Bearer {os.environ.get('BIZPLAY_API_TOKEN', 'demo-service-token')}"},
        transport=transport,
        timeout=30.0,
    )
    return FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name="Bizplay (auto-generated from OpenAPI)",
        route_maps=ROUTE_MAPS,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bizplay MCP gateway auto-generated from OpenAPI")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    gateway = build_openapi_gateway()
    if args.transport == "stdio":
        gateway.run(transport="stdio")
    else:
        gateway.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
