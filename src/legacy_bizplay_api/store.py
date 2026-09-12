"""In-memory data store behind the mock "existing" Bizplay REST API.

This package stands in for Bizplay's current production system. The MCP
server never imports it. It only talks to it over HTTP, exactly as it would
talk to the real, unmodified Bizplay APIs.

All amounts are integers in KRW.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class User:
    user_id: str
    name: str
    role: str  # "employee" | "manager"
    department: str
    manager_id: str | None
    card_ids: list[str]


@dataclass
class Card:
    card_id: str
    owner_id: str
    masked_number: str
    monthly_limit: int


@dataclass
class Transaction:
    txn_id: str
    card_id: str
    approved_at: str  # ISO 8601 local time (KST)
    merchant: str
    merchant_category: str  # meal, entertainment, travel, supplies, software, transport, bar
    merchant_tax_type: str  # "general" | "simplified" (Korean VAT taxpayer type)
    amount: int
    has_receipt_image: bool
    memo: str = ""
    attendees: list[str] = field(default_factory=list)


@dataclass
class ExpenseReport:
    report_id: str
    owner_id: str
    title: str
    txn_ids: list[str]
    total_amount: int
    status: str  # draft | pending_approval | approved | rejected
    created_at: str
    approver_id: str | None = None
    decision_comment: str = ""


_SEED_USERS = [
    User("emp001", "Minji Kim", "employee", "Sales", "mgr001", ["card-1001"]),
    User("emp002", "Jun Park", "employee", "Sales", "mgr001", ["card-1002"]),
    User("mgr001", "Soyeon Lee", "manager", "Sales", None, ["card-2001"]),
]

_SEED_CARDS = [
    Card("card-1001", "emp001", "5310-****-****-1001", 3_000_000),
    Card("card-1002", "emp002", "5310-****-****-1002", 3_000_000),
    Card("card-2001", "mgr001", "5310-****-****-2001", 5_000_000),
]

_SEED_TRANSACTIONS = [
    Transaction("txn-0001", "card-1001", "2026-09-01T12:30:00", "Hanil Kitchen", "meal", "general", 45_000, True, "Team lunch"),
    Transaction("txn-0002", "card-1001", "2026-09-02T19:40:00", "Seoul BBQ", "entertainment", "general", 180_000, True, "Client dinner"),
    Transaction("txn-0003", "card-1001", "2026-09-03T09:10:00", "Korail KTX", "travel", "general", 59_800, False, "Busan client visit"),
    Transaction("txn-0004", "card-1001", "2026-09-05T23:30:00", "Moonlight Bar", "bar", "general", 220_000, True),
    Transaction("txn-0005", "card-1001", "2026-09-06T14:00:00", "Corner Stationery", "supplies", "simplified", 38_500, False),
    Transaction("txn-0006", "card-1001", "2026-09-08T10:00:00", "CloudDocs SaaS", "software", "general", 99_000, True, "Monthly subscription"),
    Transaction("txn-0007", "card-1001", "2026-09-09T08:30:00", "Seoul Taxi", "transport", "general", 12_300, False, "Airport"),
    Transaction("txn-0101", "card-1002", "2026-09-04T12:00:00", "Noodle House", "meal", "general", 24_000, True, "Lunch meeting"),
    Transaction("txn-0201", "card-2001", "2026-09-07T18:30:00", "Hotel Lounge", "entertainment", "general", 350_000, True, "Partner dinner", ["Partner A", "Partner B"]),
]

# Department monthly budgets (KRW), keyed by (department, "YYYY-MM").
_SEED_BUDGETS = {("Sales", "2026-09"): 4_000_000}


class NotFound(Exception):
    """Entity does not exist (HTTP 404)."""


class InvalidState(Exception):
    """Operation not allowed in the current state (HTTP 409)."""


class BizplayStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.users = {u.user_id: copy.deepcopy(u) for u in _SEED_USERS}
            self.cards = {c.card_id: copy.deepcopy(c) for c in _SEED_CARDS}
            self.transactions = {t.txn_id: copy.deepcopy(t) for t in _SEED_TRANSACTIONS}
            self.budgets = dict(_SEED_BUDGETS)
            self.reports: dict[str, ExpenseReport] = {}
            self._report_seq = 0

    @staticmethod
    def _get(table: dict, key: str, kind: str):
        try:
            return table[key]
        except KeyError:
            raise NotFound(f"Unknown {kind} '{key}'") from None

    def get_user(self, user_id: str) -> User:
        return self._get(self.users, user_id, "user")

    def get_card(self, card_id: str) -> Card:
        return self._get(self.cards, card_id, "card")

    def get_transaction(self, txn_id: str) -> Transaction:
        return self._get(self.transactions, txn_id, "transaction")

    def list_transactions(self, card_id: str, month: str | None = None) -> list[Transaction]:
        self.get_card(card_id)
        txns = [t for t in self.transactions.values() if t.card_id == card_id]
        if month:
            txns = [t for t in txns if t.approved_at.startswith(month)]
        return sorted(txns, key=lambda t: t.approved_at)

    def department_budget(self, department: str, month: str) -> dict:
        budget = self.budgets.get((department, month))
        if budget is None:
            raise NotFound(f"No budget for {department} in {month}")
        cards = [c for u in self.users.values() if u.department == department for c in u.card_ids]
        spent = sum(t.amount for c in cards for t in self.list_transactions(c, month))
        return {"department": department, "month": month, "budget": budget, "spent": spent, "remaining": budget - spent}

    def create_report(self, owner_id: str, title: str, txn_ids: list[str]) -> ExpenseReport:
        self.get_user(owner_id)
        txns = [self.get_transaction(t) for t in txn_ids]
        with self._lock:
            self._report_seq += 1
            report = ExpenseReport(
                report_id=f"RPT-{self._report_seq:04d}",
                owner_id=owner_id,
                title=title,
                txn_ids=list(txn_ids),
                total_amount=sum(t.amount for t in txns),
                status="draft",
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            self.reports[report.report_id] = report
        return report

    def get_report(self, report_id: str) -> ExpenseReport:
        return self._get(self.reports, report_id, "expense report")

    def list_reports(self, owner_id: str | None = None, approver_id: str | None = None,
                     status: str | None = None) -> list[ExpenseReport]:
        reports = list(self.reports.values())
        if owner_id:
            reports = [r for r in reports if r.owner_id == owner_id]
        if approver_id:
            reports = [r for r in reports if r.approver_id == approver_id]
        if status:
            reports = [r for r in reports if r.status == status]
        return reports

    def submit_report(self, report_id: str, approver_id: str) -> ExpenseReport:
        report = self.get_report(report_id)
        self.get_user(approver_id)
        if report.status != "draft":
            raise InvalidState(f"Report {report_id} is '{report.status}', only drafts can be submitted")
        report.status, report.approver_id = "pending_approval", approver_id
        return report

    def decide_report(self, report_id: str, decision: str, comment: str = "") -> ExpenseReport:
        report = self.get_report(report_id)
        if report.status != "pending_approval":
            raise InvalidState(f"Report {report_id} is '{report.status}', not pending approval")
        if decision not in ("approved", "rejected"):
            raise InvalidState(f"Invalid decision '{decision}'")
        report.status, report.decision_comment = decision, comment
        return report


def to_dict(obj) -> dict:
    return asdict(obj)


store = BizplayStore()
