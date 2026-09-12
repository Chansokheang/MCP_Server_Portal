"""Gateway authentication: bearer tokens issued by the onboarding portal.

Over HTTP every MCP request must carry `Authorization: Bearer <token>`.
The token is looked up in the shared portal state, and the verified user
id, role, and company become the caller's identity for the whole request.

Over stdio (Claude Desktop launching the server locally) there is no HTTP
layer, so the identity falls back to BIZPLAY_USER_ID. That is acceptable
for a local demo only.
"""

from __future__ import annotations

import os
import time

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from . import policy_store


class PortalTokenVerifier(TokenVerifier):
    """Verifies gateway bearer tokens against the portal's token store."""

    def __init__(self) -> None:
        super().__init__(required_scopes=["bizplay:read"])

    async def verify_token(self, token: str) -> AccessToken | None:
        state = policy_store.load()
        record = policy_store.find_agent_token(state, token)
        if record is None:
            return None
        record["last_used_at"] = time.time()
        policy_store.save(state)
        return AccessToken(
            token=token,
            client_id=record["agent"],
            scopes=record["scopes"],
            expires_at=int(record["expires_at"]),
            subject=record["sub"],
            claims={"sub": record["sub"], "role": record["role"], "company": record["company"],
                    "token_id": record["id"], "agent": record["agent"]},
        )


class Principal:
    """Who is calling, and how we know."""

    def __init__(self, user_id: str, source: str, claims: dict | None = None) -> None:
        self.user_id = user_id
        self.source = source  # "bearer" | "env"
        self.claims = claims or {}


def current_principal() -> Principal:
    token = get_access_token()
    if token is not None and token.subject:
        return Principal(token.subject, "bearer", token.claims)
    # Local demo fallback (stdio): identity from environment variables.
    claims = {k: v for k, v in {
        "role": os.environ.get("BIZPLAY_ROLE"),
        "company": os.environ.get("BIZPLAY_COMPANY"),
    }.items() if v}
    return Principal(os.environ.get("BIZPLAY_USER_ID", "emp001"), "env", claims)
