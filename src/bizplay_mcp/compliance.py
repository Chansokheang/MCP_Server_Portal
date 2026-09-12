"""Korean corporate-card compliance rules (simplified, illustrative).

This is the "localization moat" from the strategy report: rules a global
expense platform does not know. It runs inside the MCP gateway on the JSON
returned by the existing API, so the existing API needs no change.

The thresholds are simplified demo values. They are NOT tax advice and must
be reviewed by a Korean tax professional before any real use.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

# Company policy: itemized receipt image required at or above this amount.
RECEIPT_IMAGE_THRESHOLD = 30_000
# Entertainment spending above this needs an attendee list.
ENTERTAINMENT_EVIDENCE_THRESHOLD = 30_000
# Merchant categories blocked on corporate "clean cards".
RESTRICTED_CATEGORIES = {"bar", "karaoke", "golf", "casino"}
# Late-night window (hour >= start or hour < end) flagged for review.
LATE_NIGHT_START, LATE_NIGHT_END = 23, 6
# Standard Korean VAT rate. Card amounts are VAT-inclusive.
VAT_RATE = 0.10

POLICY_SUMMARY = {
    "disclaimer": "Simplified demo rules. Not tax advice.",
    "rules": [
        {"code": "RECEIPT_IMAGE_MISSING", "severity": "blocker",
         "rule": f"Itemized receipt image required for card spend >= {RECEIPT_IMAGE_THRESHOLD:,} KRW."},
        {"code": "RESTRICTED_MERCHANT", "severity": "blocker",
         "rule": f"Clean-card policy blocks categories: {', '.join(sorted(RESTRICTED_CATEGORIES))}."},
        {"code": "ENTERTAINMENT_ATTENDEES_MISSING", "severity": "blocker",
         "rule": f"Entertainment over {ENTERTAINMENT_EVIDENCE_THRESHOLD:,} KRW needs an attendee list."},
        {"code": "MEMO_MISSING", "severity": "warning", "rule": "Every transaction should state a business purpose."},
        {"code": "LATE_NIGHT_USE", "severity": "warning",
         "rule": f"Use between {LATE_NIGHT_START}:00 and {LATE_NIGHT_END:02d}:00 needs manager review."},
        {"code": "WEEKEND_USE", "severity": "warning", "rule": "Weekend use needs a business justification."},
        {"code": "VAT_NOT_DEDUCTIBLE", "severity": "info",
         "rule": "Input VAT is not deductible for entertainment or simplified-taxpayer merchants."},
    ],
}


@dataclass
class Issue:
    txn_id: str
    code: str
    severity: str  # blocker | warning | info
    message: str


def vat_component(amount: int) -> int:
    """VAT included in a VAT-inclusive amount (10/110)."""
    return round(amount * VAT_RATE / (1 + VAT_RATE))


def check_transaction(t: dict) -> tuple[list[Issue], int]:
    """Return (issues, deductible_input_vat) for one transaction from the API."""
    issues: list[Issue] = []
    tid, merchant, amount = t["txn_id"], t["merchant"], t["amount"]
    when = datetime.fromisoformat(t["approved_at"])

    if amount >= RECEIPT_IMAGE_THRESHOLD and not t["has_receipt_image"]:
        issues.append(Issue(tid, "RECEIPT_IMAGE_MISSING", "blocker",
                            f"{merchant}: {amount:,} KRW has no receipt image attached."))
    if t["merchant_category"] in RESTRICTED_CATEGORIES:
        issues.append(Issue(tid, "RESTRICTED_MERCHANT", "blocker",
                            f"{merchant}: category '{t['merchant_category']}' is blocked on corporate cards."))
    if (t["merchant_category"] == "entertainment" and amount > ENTERTAINMENT_EVIDENCE_THRESHOLD
            and not t.get("attendees")):
        issues.append(Issue(tid, "ENTERTAINMENT_ATTENDEES_MISSING", "blocker",
                            f"{merchant}: entertainment expense needs an attendee list."))
    if not t.get("memo", "").strip():
        issues.append(Issue(tid, "MEMO_MISSING", "warning", f"{merchant}: no business purpose recorded."))
    if when.hour >= LATE_NIGHT_START or when.hour < LATE_NIGHT_END:
        issues.append(Issue(tid, "LATE_NIGHT_USE", "warning", f"{merchant}: used at {when:%H:%M}, outside normal hours."))
    if when.weekday() >= 5:
        issues.append(Issue(tid, "WEEKEND_USE", "warning", f"{merchant}: used on a {when:%A}."))

    vat = vat_component(amount)
    deductible = vat
    if t["merchant_category"] == "entertainment" or t["merchant_tax_type"] == "simplified":
        deductible = 0
        reason = "entertainment" if t["merchant_category"] == "entertainment" else "simplified-taxpayer merchant"
        issues.append(Issue(tid, "VAT_NOT_DEDUCTIBLE", "info",
                            f"{merchant}: {vat:,} KRW input VAT not deductible ({reason})."))
    return issues, deductible


def check_transactions(txns: list[dict]) -> dict:
    """Validate a set of transactions and summarize the result."""
    all_issues: list[Issue] = []
    deductible_vat = 0
    for t in txns:
        issues, vat = check_transaction(t)
        all_issues.extend(issues)
        deductible_vat += vat
    blockers = [i for i in all_issues if i.severity == "blocker"]
    return {
        "passed": not blockers,
        "transaction_count": len(txns),
        "total_amount": sum(t["amount"] for t in txns),
        "deductible_input_vat": deductible_vat,
        "blocker_count": len(blockers),
        "warning_count": sum(i.severity == "warning" for i in all_issues),
        "issues": [asdict(i) for i in all_issues],
        "disclaimer": POLICY_SUMMARY["disclaimer"],
    }
