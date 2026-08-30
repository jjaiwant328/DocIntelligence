"""Provider-parameterized OAuth (3-legged) + refresh-token cache for document source connectors.

Real mode activates when credentials are configured for a provider — resolved at runtime
from the Databricks secret scope `docintel_connectors` (env DOCINTEL_CONNECTOR_SCOPE,
default that name) via keys `{provider}_client_id/_client_secret/_redirect_uri/_scopes`,
with a short TTL cache (60 s) so new credentials are picked up without redeploy.

For google/gdrive, falls back to legacy env vars GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI
when the scope has nothing, so the existing env-based path keeps working.

GoogleOAuth is a thin backward-compatible subclass of ProviderOAuth("gdrive") so all
existing imports and usage (`_oauth = GoogleOAuth()`) keep working unchanged.
"""
import base64
import json
import os
import time
from typing import Optional

import requests

_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"

# Default scopes per provider, used when none is stored in the secret scope.
_DEFAULT_SCOPES = {
    "gdrive": "https://www.googleapis.com/auth/drive.readonly",
    "google": "https://www.googleapis.com/auth/drive.readonly",
}

# Module-level TTL credential cache:
#   {provider: (client_id, client_secret, redirect_uri, scopes, expiry_timestamp)}
_CRED_CACHE = {}
_CACHE_TTL = 60  # seconds


def _get_secret(scope_name: str, key: str) -> str:
    """Fetch one key from a Databricks secret scope.

    Returns "" on any error (scope absent, key absent, no Databricks auth, etc.)
    so the caller can fall through to the env-var path without crashing.
    The secret value is never logged.
    """
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        result = w.secrets.get_secret(scope=scope_name, key=key)
        if result.value:
            return base64.b64decode(result.value).decode("utf-8").strip()
        return ""
    except Exception:
        return ""


def _resolve(provider: str) -> tuple:
    """Resolve (client_id, client_secret, redirect_uri, scopes) for provider.

    Resolution order:
      1. Module-level TTL cache (60 s) — returns the cached tuple if fresh.
      2. Databricks secret scope `docintel_connectors` (env DOCINTEL_CONNECTOR_SCOPE).
      3. Legacy GOOGLE_OAUTH_* env vars (google/gdrive only) when the scope has nothing.

    Never raises — returns ("", "", "", "") if nothing is found anywhere.
    """
    now = time.time()
    cached = _CRED_CACHE.get(provider)
    if cached and now < cached[4]:
        return cached[:4]

    scope_name = os.environ.get("DOCINTEL_CONNECTOR_SCOPE", "docintel_connectors")
    client_id = _get_secret(scope_name, f"{provider}_client_id")
    client_secret = _get_secret(scope_name, f"{provider}_client_secret")
    redirect_uri = _get_secret(scope_name, f"{provider}_redirect_uri")
    scopes = _get_secret(scope_name, f"{provider}_scopes")

    # Env-var fallback for google/gdrive when the scope had nothing useful.
    if provider in ("google", "gdrive") and not (client_id and client_secret):
        env_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        env_sec = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        env_redir = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
        if env_id:
            client_id = env_id
        if env_sec:
            client_secret = env_sec
        if not redirect_uri and env_redir:
            redirect_uri = env_redir

    _CRED_CACHE[provider] = (client_id, client_secret, redirect_uri, scopes, now + _CACHE_TTL)
    return client_id, client_secret, redirect_uri, scopes


class ProviderOAuth:
    """Provider-parameterized OAuth handler.

    Credentials are resolved from the Databricks secret scope at property-access
    time (module-level TTL cache), so new credentials are picked up within 60 s of
    being written to the scope — no redeploy needed.
    """

    def __init__(self, provider: str) -> None:
        self._provider = provider
        # Per-provider token file prevents collisions when multiple providers run
        # on the same host.  GDRIVE_TOKEN_PATH env var overrides the default.
        self.token_path = os.environ.get(
            "GDRIVE_TOKEN_PATH",
            f"/tmp/oauth_token.{provider}.json",
        )
        self._access: Optional[str] = None
        self._access_exp: float = 0.0

    # ── credential properties (resolved via TTL cache) ───────────────────────

    @property
    def client_id(self) -> str:
        return _resolve(self._provider)[0]

    @property
    def client_secret(self) -> str:
        return _resolve(self._provider)[1]

    @property
    def redirect_uri(self) -> str:
        return _resolve(self._provider)[2]

    @property
    def scopes(self) -> str:
        return _resolve(self._provider)[3]

    @property
    def configured(self) -> bool:
        """True when client_id, client_secret, and redirect_uri are all present."""
        cid, csec, ruri, _ = _resolve(self._provider)
        return bool(cid and csec and ruri)

    # ── refresh-token persistence ─────────────────────────────────────────────

    def _load_refresh(self) -> Optional[str]:
        try:
            with open(self.token_path) as f:
                return json.load(f).get("refresh_token")
        except Exception:
            return None

    def _save_refresh(self, refresh_token: str) -> None:
        try:
            with open(self.token_path, "w") as f:
                json.dump({"refresh_token": refresh_token}, f)
        except Exception as e:
            print(f"[oauth] could not persist refresh token: {e}")

    @property
    def connected(self) -> bool:
        """True when configured AND a refresh token has been stored."""
        return self.configured and bool(self._load_refresh())

    # ── OAuth flow ────────────────────────────────────────────────────────────

    def start_url(self, state: str = "") -> str:
        from urllib.parse import urlencode
        scope_str = self.scopes or _DEFAULT_SCOPES.get(self._provider, "")
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": scope_str,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_AUTH}?{urlencode(params)}"

    def exchange_code(self, code: str) -> None:
        r = requests.post(_TOKEN, data={
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=30)
        r.raise_for_status()
        tok = r.json()
        if tok.get("refresh_token"):
            self._save_refresh(tok["refresh_token"])
        if tok.get("access_token"):
            self._access = tok["access_token"]
            self._access_exp = time.time() + int(tok.get("expires_in", 3000)) - 120

    def access_token(self) -> Optional[str]:
        if self._access and time.time() < self._access_exp:
            return self._access
        refresh = self._load_refresh()
        if not refresh:
            return None
        r = requests.post(_TOKEN, data={
            "refresh_token": refresh,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }, timeout=30)
        r.raise_for_status()
        tok = r.json()
        self._access = tok.get("access_token")
        self._access_exp = time.time() + int(tok.get("expires_in", 3000)) - 120
        return self._access


class GoogleOAuth(ProviderOAuth):
    """Backward-compatible alias: GoogleOAuth() == ProviderOAuth('gdrive').

    Existing imports (`from oauth import GoogleOAuth`) and usage
    (`_oauth = GoogleOAuth()`) keep working without any changes.
    """

    def __init__(self) -> None:
        super().__init__("gdrive")
