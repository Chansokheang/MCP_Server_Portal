"""Bizplay MCP gateway (curated tools) built with FastMCP.

    AI agent (Claude, Copilot, Agentforce)
        |  MCP (stdio or HTTP)
    THIS SERVER  -> identity & role checks, Korean compliance, audit log
        |  plain HTTP via adapters.BizplayApiClient
    Existing Bizplay REST API  (unchanged)

Run:
    uv run bizplay-mcp                              # stdio, for Claude Desktop
    uv run bizplay-mcp --transport http --port 8000 # http://127.0.0.1:8000/mcp
"""

from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError, ToolError
from pydantic import Field

from . import audit, compliance, policy_store
from .adapters import BizplayApiClient, BizplayApiError
from .auth import current_principal, gateway_auth

PROVIDER_ID = "bizplay"

mcp = FastMCP(
    name="Bizplay",
    instructions=(
        "Bizplay corporate card and expense tools for Korean companies. "
        "All amounts are KRW. Months use YYYY-MM. Check compliance before "
        "submitting an expense report, and never submit on the user's behalf "
        "without their explicit confirmation."
    ),
    # Over HTTP, every request must carry a portal-issued bearer token, unless
    # the portal's Security page turns that requirement off for a demo.
    auth=gateway_auth(),
)

def _default_api_client() -> BizplayApiClient:
    """Pick the adapter from BIZPLAY_API_BASE_URL.

    The special value "embedded" runs the mock existing API inside this
    process (DEMO ONLY, e.g. for Claude Desktop). The adapter still speaks
    HTTP to it, just without a network socket. Any other value is the URL
    of a separately running Bizplay API.
    """
    if os.environ.get("BIZPLAY_API_BASE_URL") == "embedded":
        import httpx
        from legacy_bizplay_api.app import app as legacy_app

        return BizplayApiClient("http://embedded-bizplay-api", transport=httpx.ASGITransport(app=legacy_app))
    return BizplayApiClient()


_api = _default_api_client()


def set_api_client(client: BizplayApiClient) -> None:
    """Swap the adapter (tests inject an in-process transport)."""
    global _api
    _api = client


class AccessDenied(Exception):
    pass


# --- identity & policy ----------------------------------------------------
# Over HTTP the caller comes from the verified bearer token (see auth.py).
# Over stdio (Claude Desktop, local demo) it falls back to BIZPLAY_USER_ID.
def current_user_id() -> str:
    return current_principal().user_id


@asynccontextmanager
async def guarded(tool: str, arguments: dict):
    """Resolve the caller, enforce the portal's tool policy, audit the outcome."""
    principal = current_principal()
    user_id = principal.user_id
    via = principal.source
    try:
        user = await _api.get_user(user_id)
    except BizplayApiError:
        audit.record(user_id, tool, arguments, "denied", "unknown user", via=via)
        raise ToolError(f"Unknown Bizplay user '{user_id}'") from None

    # The token's role must match Bizplay's record; a forged claim gets nowhere.
    if principal.claims.get("role") and principal.claims["role"] != user["role"]:
        audit.record(user_id, tool, arguments, "denied", "token role mismatch", via=via)
        raise ToolError("Access denied: token role does not match the Bizplay user record")

    allowed, reason = policy_store.check_tool_access(policy_store.load(), PROVIDER_ID, tool, user["role"], principal.claims)
    if not allowed:
        audit.record(user_id, tool, arguments, "denied", reason, via=via)
        raise ToolError(f"Access denied: {reason}")

    try:
        yield user
    except AccessDenied as exc:
        audit.record(user_id, tool, arguments, "denied", str(exc), via=via)
        raise ToolError(f"Access denied: {exc}") from None
    except BizplayApiError as exc:
        audit.record(user_id, tool, arguments, "error", str(exc), via=via)
        raise ToolError(f"Bizplay API error ({exc.status}): {exc.message}") from None
    except ToolError as exc:
        audit.record(user_id, tool, arguments, "error", str(exc), via=via)
        raise
    else:
        audit.record(user_id, tool, arguments, "ok", via=via)


def _month(month: str | None) -> str:
    return month or datetime.now().strftime("%Y-%m")


def _require_own_card(user: dict, card_id: str) -> None:
    if card_id not in user["card_ids"]:
        raise AccessDenied(f"card {card_id} does not belong to {user['user_id']}")


async def _own_transactions(user: dict, txn_ids: list[str]) -> list[dict]:
    txns = [await _api.get_transaction(t) for t in txn_ids]
    for t in txns:
        _require_own_card(user, t["card_id"])
    return txns


MonthArg = Annotated[str | None, Field(description="Month as YYYY-MM. Defaults to the current month.",
                                       pattern=r"^\d{4}-\d{2}$")]
READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}


# --- tools --------------------------------------------------------------
@mcp.tool(annotations=READ_ONLY)
async def get_card_balance(month: MonthArg = None) -> dict:
    """Show the caller's corporate cards with monthly limit, amount spent, and remaining balance."""
    month = _month(month)
    async with guarded("get_card_balance", {"month": month}) as user:
        cards = []
        for card_id in user["card_ids"]:
            card = await _api.get_card(card_id)
            spent = sum(t["amount"] for t in await _api.list_transactions(card_id, month))
            cards.append({**card, "month": month, "spent": spent, "remaining": card["monthly_limit"] - spent})
        return {"user_id": user["user_id"], "cards": cards}


@mcp.tool(annotations=READ_ONLY)
async def list_card_transactions(
    month: MonthArg = None,
    card_id: Annotated[str | None, Field(description="One of the caller's card ids. Omit for all cards.")] = None,
) -> dict:
    """List the caller's corporate card transactions for a month."""
    month = _month(month)
    async with guarded("list_card_transactions", {"month": month, "card_id": card_id}) as user:
        card_ids = user["card_ids"]
        if card_id:
            _require_own_card(user, card_id)
            card_ids = [card_id]
        items = [t for c in card_ids for t in await _api.list_transactions(c, month)]
        return {"month": month, "count": len(items), "total_amount": sum(t["amount"] for t in items), "transactions": items}


@mcp.tool(annotations=READ_ONLY)
async def find_missing_receipts(month: MonthArg = None) -> dict:
    """Find the caller's transactions that are missing receipt images or entertainment attendee lists."""
    month = _month(month)
    async with guarded("find_missing_receipts", {"month": month}) as user:
        missing = []
        for c in user["card_ids"]:
            for t in await _api.list_transactions(c, month):
                issues, _ = compliance.check_transaction(t)
                codes = [i.code for i in issues if i.code in ("RECEIPT_IMAGE_MISSING", "ENTERTAINMENT_ATTENDEES_MISSING")]
                if codes:
                    missing.append({"txn_id": t["txn_id"], "merchant": t["merchant"], "amount": t["amount"],
                                    "approved_at": t["approved_at"], "missing": codes})
        return {"month": month, "count": len(missing), "items": missing}


@mcp.tool(annotations=READ_ONLY)
async def validate_tax_compliance(
    txn_ids: Annotated[list[str], Field(min_length=1, description="Transaction ids to check.")],
) -> dict:
    """Check transactions against Korean corporate-card rules (receipts, clean-card merchants,
    entertainment evidence, late-night/weekend use) and estimate deductible input VAT."""
    async with guarded("validate_tax_compliance", {"txn_ids": txn_ids}) as user:
        return compliance.check_transactions(await _own_transactions(user, txn_ids))


@mcp.tool(annotations=WRITE)
async def draft_expense_report(
    title: Annotated[str, Field(min_length=1, max_length=100)],
    txn_ids: Annotated[list[str] | None, Field(description="Transactions to include. Omit to include all "
                                                          "of the month's transactions not already in a report.")] = None,
    month: MonthArg = None,
) -> dict:
    """Create a DRAFT expense report and return it with a compliance check. Nothing is submitted."""
    month = _month(month)
    args = {"title": title, "txn_ids": txn_ids, "month": month}
    async with guarded("draft_expense_report", args) as user:
        if txn_ids:
            txns = await _own_transactions(user, txn_ids)
        else:
            used = {t for r in await _api.list_reports(owner_id=user["user_id"])
                    if r["status"] != "rejected" for t in r["txn_ids"]}
            txns = [t for c in user["card_ids"] for t in await _api.list_transactions(c, month) if t["txn_id"] not in used]
        if not txns:
            raise ToolError(f"No unreported transactions found for {month}")
        report = await _api.create_report(user["user_id"], title, [t["txn_id"] for t in txns])
        return {"report": report, "compliance": compliance.check_transactions(txns)}


@mcp.tool(annotations=WRITE)
async def submit_for_approval(report_id: str) -> dict:
    """Submit one of the caller's draft reports to their manager. Refused if compliance blockers remain.
    Only call this after the user has explicitly confirmed submission."""
    async with guarded("submit_for_approval", {"report_id": report_id}) as user:
        report = await _api.get_report(report_id)
        if report["owner_id"] != user["user_id"]:
            raise AccessDenied(f"report {report_id} belongs to another user")
        if not user.get("manager_id"):
            raise ToolError("No approver is configured for this user")
        result = compliance.check_transactions(await _own_transactions(user, report["txn_ids"]))
        if not result["passed"]:
            blockers = "; ".join(i["message"] for i in result["issues"] if i["severity"] == "blocker")
            raise ToolError(f"Cannot submit {report_id}: {result['blocker_count']} compliance blocker(s). {blockers}")
        submitted = await _api.submit_report(report_id, user["manager_id"])
        return {"report": submitted, "compliance": result}


@mcp.tool(annotations=READ_ONLY)
async def list_pending_approvals() -> dict:
    """Managers only: list expense reports waiting for the caller's approval."""
    async with guarded("list_pending_approvals", {}) as user:
        if user["role"] != "manager":
            raise AccessDenied("only managers can view pending approvals")
        items = await _api.list_reports(approver_id=user["user_id"], status="pending_approval")
        return {"count": len(items), "reports": items}


@mcp.tool(annotations={**WRITE, "destructiveHint": True})
async def decide_approval(
    report_id: str,
    decision: Literal["approve", "reject"],
    comment: Annotated[str, Field(max_length=500)] = "",
) -> dict:
    """Managers only: approve or reject a report assigned to the caller. Confirm with the user first."""
    async with guarded("decide_approval", {"report_id": report_id, "decision": decision}) as user:
        if user["role"] != "manager":
            raise AccessDenied("only managers can decide approvals")
        report = await _api.get_report(report_id)
        if report["approver_id"] != user["user_id"]:
            raise AccessDenied(f"report {report_id} is not assigned to {user['user_id']}")
        if decision == "reject" and not comment.strip():
            raise ToolError("A comment is required when rejecting a report")
        status = "approved" if decision == "approve" else "rejected"
        return {"report": await _api.decide_report(report_id, status, comment)}


# --- resources ----------------------------------------------------------
@mcp.resource("bizplay://me/profile", mime_type="application/json")
async def my_profile() -> dict:
    """The caller's Bizplay profile: role, department, manager, and cards."""
    try:
        return await _api.get_user(current_user_id())
    except BizplayApiError as exc:
        raise ResourceError(exc.message) from None


@mcp.resource("bizplay://budgets/{department}/{month}", mime_type="application/json")
async def department_budget(department: str, month: str) -> dict:
    """Monthly budget, spend, and remaining amount for the caller's own department."""
    try:
        user = await _api.get_user(current_user_id())
        if user["department"] != department:
            raise ResourceError(f"Access denied: you can only view the {user['department']} budget")
        return await _api.get_budget(department, month)
    except BizplayApiError as exc:
        raise ResourceError(exc.message) from None


@mcp.resource("bizplay://policies/korean-compliance", mime_type="application/json")
def korean_compliance_policy() -> dict:
    """The Korean corporate-card rules this server enforces (simplified demo rules)."""
    return compliance.POLICY_SUMMARY


# --- prompts ------------------------------------------------------------
@mcp.prompt
def month_end_closing(month: str) -> str:
    """Guide an employee through month-end expense closing."""
    return (
        f"Help me close my corporate card expenses for {month}.\n"
        "1. Call get_card_balance and list_card_transactions for that month.\n"
        "2. Call find_missing_receipts and tell me exactly what I still need to attach.\n"
        "3. Call validate_tax_compliance on the remaining transactions and explain any blockers "
        "and the estimated deductible VAT in plain language.\n"
        "4. Draft an expense report with draft_expense_report for the compliant transactions.\n"
        "5. Show me the draft and ask for my confirmation before calling submit_for_approval."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bizplay MCP gateway (curated tools)")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
