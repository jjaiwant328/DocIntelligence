"""On-behalf-of-user token helper for calling managed AI-Gateway MCP services.

The Databricks Apps proxy forwards the user's token as X-Forwarded-Access-Token.
We exchange it (RFC 8693) for an `ai-gateway`-scoped token using the app service
principal's client credentials, and use THAT to call system.ai.* MCP services as
the user. Tokens are never logged, persisted, or returned.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from fastapi import HTTPException

WORKSPACE_HOST = os.getenv(
    "DATABRICKS_HOST", "https://adb-4101016551133680.0.azuredatabricks.net"
).rstrip("/")


def _exchange_token(subject_token: str, *, post: Optional[Callable] = None) -> str:
    """Exchange a forwarded user token for an ai-gateway-scoped access token."""
    if post is None:
        import requests
        post = requests.post
    resp = post(
        f"{WORKSPACE_HOST}/oidc/v1/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": subject_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "scope": "ai-gateway",
        },
        auth=(os.environ.get("DATABRICKS_CLIENT_ID", ""),
              os.environ.get("DATABRICKS_CLIENT_SECRET", "")),
        timeout=30,
    )
    if not (200 <= resp.status_code < 300):
        raise HTTPException(
            status_code=403,
            detail=(
                f"user authorization for AI Gateway failed or expired "
                f"(status {resp.status_code}); re-authorize and retry"
            ),
        )
    return resp.json()["access_token"]


def user_ai_gateway_token(request, *, exchanger: Optional[Callable] = None) -> str:
    """Return an ai-gateway token for the request's user, or raise 401."""
    tok = request.headers.get("x-forwarded-access-token")
    if not tok:
        raise HTTPException(status_code=401,
                            detail="this action requires user authorization")
    return (exchanger or _exchange_token)(tok)
