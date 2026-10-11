"""Write-only handler for connector OAuth credentials in Databricks secret scopes.

Design constraints:
- put_connector_credentials NEVER returns the secret value — only the ref string.
- Secrets are written via an INJECTABLE client (default lazily builds WorkspaceClient).
- delete_connector_credentials is best-effort: per-key exceptions are swallowed.
- secret_configured checks key existence via list_secrets — no value is read.
"""
from __future__ import annotations

import json
import os

SCOPE = os.getenv("DOCINTEL_CONNECTOR_SCOPE", "docintel_connectors")


def secret_key(provider: str) -> str:
    """Return the secret scope key name for a provider's client secret."""
    return f"{provider}_client_secret"


def put_connector_credentials(
    provider: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scopes: list,
    *,
    client=None,
) -> str:
    """Write OAuth credentials to the Databricks secret scope.

    Writes four keys: client_secret, client_id, redirect_uri, scopes.
    Returns the secret_ref string (e.g. 'docintel_connectors/gdrive_client_secret').
    The secret value is NEVER returned.
    """
    if client is None:
        from databricks.sdk import WorkspaceClient
        client = WorkspaceClient()

    secrets = client.secrets
    secrets.put_secret(SCOPE, f"{provider}_client_id", string_value=client_id)
    secrets.put_secret(SCOPE, secret_key(provider), string_value=client_secret)
    secrets.put_secret(SCOPE, f"{provider}_redirect_uri", string_value=redirect_uri)
    secrets.put_secret(SCOPE, f"{provider}_scopes", string_value=json.dumps(scopes))

    return f"{SCOPE}/{secret_key(provider)}"


def put_connector_config(
    provider: str,
    client_id: str,
    redirect_uri: str,
    scopes: list,
    *,
    client=None,
) -> str:
    """Write non-secret OAuth config keys to the Databricks secret scope.

    Writes three keys: client_id, redirect_uri, scopes.
    Does NOT write or delete client_secret.
    Returns the secret_ref string (same convention as put_connector_credentials).
    """
    if client is None:
        from databricks.sdk import WorkspaceClient
        client = WorkspaceClient()

    secrets = client.secrets
    secrets.put_secret(SCOPE, f"{provider}_client_id", string_value=client_id)
    secrets.put_secret(SCOPE, f"{provider}_redirect_uri", string_value=redirect_uri)
    secrets.put_secret(SCOPE, f"{provider}_scopes", string_value=json.dumps(scopes))

    return f"{SCOPE}/{secret_key(provider)}"


def secret_configured(provider: str, *, client=None) -> bool:
    """Return True if a client_secret exists for the provider (no value read)."""
    if client is None:
        from databricks.sdk import WorkspaceClient
        client = WorkspaceClient()

    try:
        keys = [s.key for s in client.secrets.list_secrets(SCOPE)]
        return secret_key(provider) in keys
    except Exception:
        return False


def delete_connector_credentials(provider: str, *, client=None) -> None:
    """Delete all credential keys for provider from the secret scope. Best-effort."""
    if client is None:
        from databricks.sdk import WorkspaceClient
        client = WorkspaceClient()

    for key in [
        secret_key(provider),
        f"{provider}_client_id",
        f"{provider}_redirect_uri",
        f"{provider}_scopes",
    ]:
        try:
            client.secrets.delete_secret(SCOPE, key)
        except Exception:
            pass
