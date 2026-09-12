"""End-to-end tests: MCP client -> curated gateway -> mock existing API."""

import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from bizplay_mcp.server import mcp

EXPECTED_TOOLS = {
    "get_card_balance", "list_card_transactions", "find_missing_receipts", "validate_tax_compliance",
    "draft_expense_report", "submit_for_approval", "list_pending_approvals", "decide_approval",
}


def audit_entries(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


async def call(name, args=None):
    async with Client(mcp) as client:
        return (await client.call_tool(name, args or {})).data


async def test_lists_curated_tools():
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == EXPECTED_TOOLS


async def test_card_balance():
    data = await call("get_card_balance", {"month": "2026-09"})
    card = data["cards"][0]
    assert card["card_id"] == "card-1001"
    assert card["spent"] == 654_600
    assert card["remaining"] == 3_000_000 - 654_600


async def test_cannot_read_someone_elses_card(wiring):
    with pytest.raises(ToolError, match="Access denied"):
        await call("list_card_transactions", {"month": "2026-09", "card_id": "card-1002"})
    last = audit_entries(wiring)[-1]
    assert (last["user_id"], last["tool"], last["outcome"]) == ("emp001", "list_card_transactions", "denied")


async def test_find_missing_receipts():
    data = await call("find_missing_receipts", {"month": "2026-09"})
    found = {i["txn_id"]: i["missing"] for i in data["items"]}
    assert found == {
        "txn-0002": ["ENTERTAINMENT_ATTENDEES_MISSING"],
        "txn-0003": ["RECEIPT_IMAGE_MISSING"],
        "txn-0005": ["RECEIPT_IMAGE_MISSING"],
    }


async def test_compliance_flags_and_vat():
    data = await call("validate_tax_compliance", {"txn_ids": ["txn-0001", "txn-0004"]})
    codes = {(i["txn_id"], i["code"]) for i in data["issues"]}
    assert ("txn-0004", "RESTRICTED_MERCHANT") in codes
    assert ("txn-0004", "LATE_NIGHT_USE") in codes
    assert ("txn-0004", "WEEKEND_USE") in codes
    assert data["passed"] is False
    # 45,000 and 220,000 KRW are VAT-inclusive: 4,091 + 20,000 deductible.
    assert data["deductible_input_vat"] == 4_091 + 20_000


async def test_full_approval_flow(as_user, wiring):
    draft = await call("draft_expense_report", {"title": "Sept ops", "txn_ids": ["txn-0001", "txn-0006"]})
    report_id = draft["report"]["report_id"]
    assert draft["report"]["status"] == "draft"
    assert draft["compliance"]["passed"] is True

    submitted = await call("submit_for_approval", {"report_id": report_id})
    assert submitted["report"]["status"] == "pending_approval"
    assert submitted["report"]["approver_id"] == "mgr001"

    as_user("mgr001")
    pending = await call("list_pending_approvals")
    assert [r["report_id"] for r in pending["reports"]] == [report_id]
    decided = await call("decide_approval", {"report_id": report_id, "decision": "approve"})
    assert decided["report"]["status"] == "approved"

    tools = [e["tool"] for e in audit_entries(wiring) if e["outcome"] == "ok"]
    assert tools == ["draft_expense_report", "submit_for_approval", "list_pending_approvals", "decide_approval"]


async def test_submit_blocked_by_compliance():
    draft = await call("draft_expense_report", {"title": "Trip", "txn_ids": ["txn-0003"]})
    with pytest.raises(ToolError, match="compliance blocker"):
        await call("submit_for_approval", {"report_id": draft["report"]["report_id"]})


async def test_employee_cannot_approve():
    # Portal policy denies the role first; the tool's own manager check is the second line of defense.
    with pytest.raises(ToolError, match="role 'employee' is not allowed"):
        await call("list_pending_approvals")


async def test_draft_all_unreported_transactions():
    first = await call("draft_expense_report", {"title": "Part 1", "txn_ids": ["txn-0001"]})
    rest = await call("draft_expense_report", {"title": "Rest of Sept", "month": "2026-09"})
    assert "txn-0001" not in rest["report"]["txn_ids"]
    assert len(rest["report"]["txn_ids"]) == 6
    assert first["report"]["report_id"] != rest["report"]["report_id"]


async def test_resources(as_user):
    async with Client(mcp) as client:
        profile = json.loads((await client.read_resource("bizplay://me/profile"))[0].text)
        budget = json.loads((await client.read_resource("bizplay://budgets/Sales/2026-09"))[0].text)
        policy = json.loads((await client.read_resource("bizplay://policies/korean-compliance"))[0].text)
    assert profile["user_id"] == "emp001"
    assert budget["spent"] == 654_600 + 24_000 + 350_000
    assert any(r["code"] == "RESTRICTED_MERCHANT" for r in policy["rules"])


async def test_prompt():
    async with Client(mcp) as client:
        result = await client.get_prompt("month_end_closing", {"month": "2026-09"})
    assert "submit_for_approval" in result.messages[0].content.text
