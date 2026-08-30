"""Tests for secret_store — injected fake WorkspaceClient, no live secret API."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import secret_store


# ── Fake plumbing ──────────────────────────────────────────────────────────────

class FakeSecrets:
    def __init__(self):
        self.puts: list = []
        self.deletes: list = []
        self._keys: list = []   # seed for list_secrets

    def put_secret(self, scope, key, string_value=None):
        self.puts.append((scope, key, string_value))

    def delete_secret(self, scope, key):
        self.deletes.append((scope, key))

    def list_secrets(self, scope):
        return [type("S", (), {"key": k})() for k in self._keys]


class FakeWS:
    def __init__(self):
        self.secrets = FakeSecrets()


# ── put_connector_credentials ──────────────────────────────────────────────────

def test_put_writes_secret_and_returns_ref_not_secret():
    """Canonical test from the brief."""
    calls = []

    class _Secrets:
        def put_secret(self, scope, key, string_value=None):
            calls.append((scope, key, string_value))

    class _WS:
        secrets = _Secrets()

    ref = secret_store.put_connector_credentials(
        "gdrive", "cid", "SHH", "uri", ["s"], client=_WS()
    )
    assert ("docintel_connectors", "gdrive_client_secret", "SHH") in calls
    assert "SHH" not in ref
    assert ref == "docintel_connectors/gdrive_client_secret"


def test_put_writes_all_four_keys():
    ws = FakeWS()
    secret_store.put_connector_credentials(
        "gdrive", "my_client_id", "my_secret",
        "https://example.com/cb", ["email", "openid"],
        client=ws,
    )
    keys_written = {c[1] for c in ws.secrets.puts}
    assert "gdrive_client_secret" in keys_written
    assert "gdrive_client_id" in keys_written
    assert "gdrive_redirect_uri" in keys_written
    assert "gdrive_scopes" in keys_written


def test_put_uses_correct_scope():
    ws = FakeWS()
    secret_store.put_connector_credentials(
        "gdrive", "cid", "sec", "uri", [], client=ws
    )
    scopes_used = {c[0] for c in ws.secrets.puts}
    assert scopes_used == {"docintel_connectors"}


def test_put_return_value_is_ref_string():
    ws = FakeWS()
    ref = secret_store.put_connector_credentials(
        "sharepoint", "cid", "sec", "uri", [], client=ws
    )
    assert ref == "docintel_connectors/sharepoint_client_secret"


# ── secret_configured ─────────────────────────────────────────────────────────

def test_secret_configured_true_when_key_present():
    ws = FakeWS()
    ws.secrets._keys = ["gdrive_client_secret", "gdrive_client_id"]
    assert secret_store.secret_configured("gdrive", client=ws) is True


def test_secret_configured_false_when_key_absent():
    ws = FakeWS()
    ws.secrets._keys = []
    assert secret_store.secret_configured("gdrive", client=ws) is False


def test_secret_configured_does_not_read_secret_value():
    """Listing keys must not call put_secret or return secret values."""
    ws = FakeWS()
    ws.secrets._keys = ["gdrive_client_secret"]
    secret_store.secret_configured("gdrive", client=ws)
    # list_secrets must have been called; put_secret must NOT
    assert ws.secrets.puts == []


# ── delete_connector_credentials ─────────────────────────────────────────────

def test_delete_removes_all_four_keys():
    ws = FakeWS()
    secret_store.delete_connector_credentials("gdrive", client=ws)
    deleted_keys = {d[1] for d in ws.secrets.deletes}
    assert "gdrive_client_secret" in deleted_keys
    assert "gdrive_client_id" in deleted_keys
    assert "gdrive_redirect_uri" in deleted_keys
    assert "gdrive_scopes" in deleted_keys


def test_delete_best_effort_no_raise_on_error():
    """delete_connector_credentials must not propagate exceptions."""
    class _ErrSecrets:
        def delete_secret(self, scope, key):
            raise RuntimeError("not found")

    class _ErrWS:
        secrets = _ErrSecrets()

    # Should not raise
    secret_store.delete_connector_credentials("gdrive", client=_ErrWS())


# ── secret_key helper ─────────────────────────────────────────────────────────

def test_secret_key_format():
    assert secret_store.secret_key("gdrive") == "gdrive_client_secret"
    assert secret_store.secret_key("sharepoint") == "sharepoint_client_secret"
