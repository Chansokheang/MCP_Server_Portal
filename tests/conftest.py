"""Wire the MCP gateway to the mock existing API in-process (no network)."""

import httpx
import pytest

from bizplay_mcp import policy_store, server
from bizplay_mcp.adapters import BizplayApiClient
from legacy_bizplay_api.app import app as legacy_app
from legacy_bizplay_api.store import store


@pytest.fixture(autouse=True)
def wiring(monkeypatch, tmp_path):
    store.reset()
    monkeypatch.setenv("BIZPLAY_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("BIZPLAY_PORTAL_STATE", str(tmp_path / "portal_state.json"))
    monkeypatch.setenv("BIZPLAY_USER_ID", "emp001")
    policy_store.reset()
    server.set_api_client(
        BizplayApiClient("http://legacy.test", transport=httpx.ASGITransport(app=legacy_app))
    )
    yield tmp_path / "audit.jsonl"


@pytest.fixture
def as_user(monkeypatch):
    def _switch(user_id: str) -> None:
        monkeypatch.setenv("BIZPLAY_USER_ID", user_id)
    return _switch
