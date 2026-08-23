"""Google OAuth (3-legged) + refresh-token cache for the Drive connector.

Real mode activates only when GOOGLE_OAUTH_CLIENT_ID/SECRET are set. The refresh
token is cached to a file (GDRIVE_TOKEN_PATH) — simple and self-contained; it is
lost on redeploy, so the user re-consents. (A UC/Lakebase-backed store is a
future hardening; noted in the README.)
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import requests

_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class GoogleOAuth:
    def __init__(self) -> None:
        self.client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        self.redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
        self.token_path = os.environ.get("GDRIVE_TOKEN_PATH", "/tmp/gdrive_token.json")
        self._access: Optional[str] = None
        self._access_exp: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    # ── token cache ─────────────────────────────────────────────────────────
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
        return self.configured and bool(self._load_refresh())

    # ── flow ──────────────────────────────────────────────────────────────
    def start_url(self, state: str = "") -> str:
        from urllib.parse import urlencode
        params = {
            "client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "response_type": "code", "scope": _SCOPE,
            "access_type": "offline", "prompt": "consent", "state": state,
        }
        return f"{_AUTH}?{urlencode(params)}"

    def exchange_code(self, code: str) -> None:
        r = requests.post(_TOKEN, data={
            "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri, "grant_type": "authorization_code",
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
            "refresh_token": refresh, "client_id": self.client_id,
            "client_secret": self.client_secret, "grant_type": "refresh_token",
        }, timeout=30)
        r.raise_for_status()
        tok = r.json()
        self._access = tok.get("access_token")
        self._access_exp = time.time() + int(tok.get("expires_in", 3000)) - 120
        return self._access
