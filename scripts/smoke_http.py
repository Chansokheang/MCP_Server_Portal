"""Real-network smoke test.

Start both servers first:
    uv run legacy-bizplay-api --port 18080
    uv run bizplay-mcp --transport http --port 8000
Then:
    uv run python scripts/smoke_http.py
"""

import asyncio
import json

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

URL = "http://127.0.0.1:8000/mcp"


def client_for(user_id: str) -> Client:
    return Client(StreamableHttpTransport(URL, headers={"X-Bizplay-User": user_id}))


async def main() -> None:
    async with client_for("emp001") as c:
        tools = sorted(t.name for t in await c.list_tools())
        print("tools:", tools)
        balance = (await c.call_tool("get_card_balance", {"month": "2026-09"})).data
        print("balance:", json.dumps(balance["cards"][0], ensure_ascii=False))
        missing = (await c.call_tool("find_missing_receipts", {"month": "2026-09"})).data
        print("missing receipts:", [(i["txn_id"], i["missing"]) for i in missing["items"]])
        draft = (await c.call_tool("draft_expense_report",
                                   {"title": "Smoke test", "txn_ids": ["txn-0001", "txn-0006"]})).data
        report_id = draft["report"]["report_id"]
        print("draft:", report_id, draft["report"]["status"], "passed:", draft["compliance"]["passed"])
        submitted = (await c.call_tool("submit_for_approval", {"report_id": report_id})).data
        print("submitted:", submitted["report"]["status"], "->", submitted["report"]["approver_id"])

    async with client_for("mgr001") as c:
        decided = (await c.call_tool("decide_approval", {"report_id": report_id, "decision": "approve"})).data
        print("decided:", decided["report"]["status"])


if __name__ == "__main__":
    asyncio.run(main())
