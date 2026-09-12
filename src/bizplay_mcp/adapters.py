"""Adapter layer: calls Bizplay's existing REST API over HTTP.

This is the only place the MCP server knows about Bizplay's endpoints.
Pointing BIZPLAY_API_BASE_URL at the real system (and supplying a service
token) is all it takes to swap the mock for production. No change to the
existing API is required.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class BizplayApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class BizplayApiClient:
    def __init__(self, base_url: str | None = None, *, service_token: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0) -> None:
        self.base_url = base_url or os.environ.get("BIZPLAY_API_BASE_URL", "http://127.0.0.1:18080")
        self._token = service_token or os.environ.get("BIZPLAY_API_TOKEN", "demo-service-token")
        self._transport = transport  # tests inject an in-process ASGI transport
        self._timeout = timeout

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(base_url=self.base_url, transport=self._transport, timeout=self._timeout,
                                     headers={"Authorization": f"Bearer {self._token}"}) as client:
            try:
                resp = await client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise BizplayApiError(503, f"Bizplay API unreachable at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            try:
                message = resp.json().get("error", resp.text)
            except ValueError:
                message = resp.text
            raise BizplayApiError(resp.status_code, message)
        return resp.json()

    # Each method maps 1:1 to an existing endpoint.
    async def get_user(self, user_id: str) -> dict:
        return await self._request("GET", f"/api/v1/users/{user_id}")

    async def get_card(self, card_id: str) -> dict:
        return await self._request("GET", f"/api/v1/cards/{card_id}")

    async def list_transactions(self, card_id: str, month: str | None = None) -> list[dict]:
        params = {"month": month} if month else None
        return (await self._request("GET", f"/api/v1/cards/{card_id}/transactions", params=params))["items"]

    async def get_transaction(self, txn_id: str) -> dict:
        return await self._request("GET", f"/api/v1/transactions/{txn_id}")

    async def get_budget(self, department: str, month: str) -> dict:
        return await self._request("GET", f"/api/v1/budgets/{department}/{month}")

    async def list_reports(self, **filters: str) -> list[dict]:
        params = {k: v for k, v in filters.items() if v}
        return (await self._request("GET", "/api/v1/expense-reports", params=params))["items"]

    async def create_report(self, owner_id: str, title: str, txn_ids: list[str]) -> dict:
        return await self._request("POST", "/api/v1/expense-reports",
                                   json={"owner_id": owner_id, "title": title, "txn_ids": txn_ids})

    async def get_report(self, report_id: str) -> dict:
        return await self._request("GET", f"/api/v1/expense-reports/{report_id}")

    async def submit_report(self, report_id: str, approver_id: str) -> dict:
        return await self._request("POST", f"/api/v1/expense-reports/{report_id}/submit",
                                   json={"approver_id": approver_id})

    async def decide_report(self, report_id: str, decision: str, comment: str) -> dict:
        return await self._request("POST", f"/api/v1/expense-reports/{report_id}/decision",
                                   json={"decision": decision, "comment": comment})
