"""The zero-code gateway: tools generated from the OpenAPI spec, calling the unchanged API."""

import httpx2
from fastmcp import Client

from bizplay_mcp.openapi_gateway import build_openapi_gateway
from legacy_bizplay_api.app import app as legacy_app


def gateway():
    return build_openapi_gateway("http://legacy.test", transport=httpx2.ASGITransport(app=legacy_app))


async def test_tools_generated_from_spec():
    async with Client(gateway()) as client:
        names = {t.name for t in await client.list_tools()}
    assert {"get_user", "list_card_transactions", "create_expense_report", "submit_expense_report"} <= names
    # Excluded by a route map, not by editing the API.
    assert "decide_expense_report" not in names


async def test_generated_tool_calls_existing_api():
    async with Client(gateway()) as client:
        result = await client.call_tool("list_card_transactions", {"card_id": "card-1001", "month": "2026-09"})
    items = result.structured_content["items"]
    assert len(items) == 7
    assert items[0]["txn_id"] == "txn-0001"
