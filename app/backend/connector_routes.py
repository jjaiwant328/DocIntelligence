"""App-managed connector credential config routes.

  GET    /api/connectors                          list connectors (no secrets)
  POST   /api/connectors                          upsert connector + optional secret
  DELETE /api/connectors/{provider}               remove connector + secrets (best effort)
  GET    /api/connectors/{provider}/authorize-url OAuth start URL

Security contract:
- client_secret and secret_ref NEVER appear in any HTTP response.
- GET returns client_id_last4 only — not the full client_id.
- POST without client_secret in body preserves the existing secret; put is NOT called.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

import secret_store
from db import operational as opstore

router = APIRouter(prefix="/api", tags=["Connectors"])

_DEFAULT_REDIRECT_BASE = (
    "https://docintel-sources-4101016551133680.0.azure.databricksapps.com"
)


class ConnectorUpsertRequest(BaseModel):
    provider: str
    display_name: str = ""
    client_id: str = ""
    client_secret: Optional[str] = None   # absent = keep existing secret
    redirect_uri: Optional[str] = None    # None = use default
    scopes: Optional[list[str]] = None


def _strip(row: Optional[dict]) -> Optional[dict]:
    """Return only public fields — no secret_ref, no full client_id."""
    if not row:
        return row
    cid = row.get("client_id", "")
    return {
        "provider": row.get("provider", ""),
        "display_name": row.get("display_name", ""),
        "client_id_last4": cid[-4:] if cid else "",
        "status": row.get("status", ""),
        "redirect_uri": row.get("redirect_uri", ""),
        "scopes": row.get("scopes", []),
    }


@router.get("/connectors")
def list_connectors():
    rows = opstore.list_connectors()
    return {"connectors": [_strip(r) for r in rows]}


@router.post("/connectors")
def upsert_connector(req: ConnectorUpsertRequest):
    redirect = req.redirect_uri or (
        f"{_DEFAULT_REDIRECT_BASE}/oauth/{req.provider}/callback"
    )
    scopes = req.scopes or []

    if req.client_secret:
        # New secret supplied — write to scope and update ref.
        ref = secret_store.put_connector_credentials(
            req.provider, req.client_id, req.client_secret,
            redirect, scopes,
        )
        status = "configured"
    else:
        # No new secret — preserve whatever is already stored.
        existing = opstore.get_connector(req.provider)
        ref = existing.get("secret_ref", "") if existing else ""
        status = existing.get("status", "unconfigured") if existing else "unconfigured"
        # Propagate non-secret field edits to scope so the sources app stays in sync.
        secret_store.put_connector_config(req.provider, req.client_id, redirect, scopes)

    row = opstore.upsert_connector(
        provider=req.provider,
        display_name=req.display_name or req.provider,
        client_id=req.client_id,
        redirect_uri=redirect,
        scopes=scopes,
        secret_ref=ref,
        status=status,
        updated_by="app_user",
    )
    return {"connector": _strip(row)}


@router.delete("/connectors/{provider}")
def delete_connector(provider: str):
    opstore.delete_connector(provider)
    try:
        secret_store.delete_connector_credentials(provider)
    except Exception:
        pass
    return {"provider": provider, "deleted": True}


@router.get("/connectors/{provider}/authorize-url")
def get_authorize_url(provider: str):
    base = os.getenv("DOCINTEL_MCP_SOURCES_URL", "").rstrip("/")
    return {"auth_url": f"{base}/oauth/{provider}/start" if base else ""}
