"""Lakebase connection + OAuth-token lifecycle.

The app runs as a Databricks service principal. It mints a short-lived Lakebase
OAuth credential in-process via the SDK (`w.postgres.generate_database_credential`)
and uses it as the Postgres password. Tokens last ~1h, so we cache one and rebuild
the connection pool with a fresh token before it expires; open connections keep
working (Postgres only checks auth at connect time), and pool `max_lifetime`
recycles them onto fresh tokens.

Everything talks to the `LAKEBASE_SCHEMA` schema (default `app`). The token
provider and pool factory are injectable so the token-refresh logic is unit
-testable without a live database (see tests/test_lakebase.py).
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Optional

# ── Config (env-driven; see app.yaml) ─────────────────────────────────────────
def _is_enabled() -> bool:
    return os.getenv("LAKEBASE_ENABLED", "").strip().lower() in ("1", "true", "yes")


LAKEBASE_ENDPOINT = os.getenv(
    "LAKEBASE_ENDPOINT", "projects/docintel/branches/production/endpoints/primary"
)
LAKEBASE_HOST = os.getenv("LAKEBASE_HOST", "")
LAKEBASE_PORT = int(os.getenv("LAKEBASE_PORT", "5432"))
LAKEBASE_DB = os.getenv("LAKEBASE_DB", "docintel")
LAKEBASE_SCHEMA = os.getenv("LAKEBASE_SCHEMA", "app")
# Postgres login user: the SP's client id in the app; a user email locally.
LAKEBASE_USER = os.getenv("LAKEBASE_USER", "")

# Refresh the token this many seconds before its stated expiry.
_TOKEN_SKEW_SECS = 600
# Fallback token lifetime when the credential response has no expiry.
_TOKEN_DEFAULT_TTL = 3600
# Recycle pooled connections before the token that opened them can expire.
_CONN_MAX_LIFETIME = 2700  # 45 min


class LakebaseUnavailable(RuntimeError):
    """Raised when Lakebase is disabled or cannot be reached — callers fall back."""


# ── Token provider ────────────────────────────────────────────────────────────
def _sdk_token_provider() -> tuple[str, float]:
    """Mint a Lakebase OAuth credential for the current identity via the SDK.

    Returns (token, expiry_epoch_secs). Used as the default; injectable in tests.
    """
    from databricks.sdk import WorkspaceClient

    cred = WorkspaceClient().postgres.generate_database_credential(
        endpoint=LAKEBASE_ENDPOINT
    )
    token = getattr(cred, "token", None)
    if not token:
        raise LakebaseUnavailable("credential response had no token")
    # DatabaseCredential.expire_time is an RFC3339 string when present.
    expiry = time.time() + _TOKEN_DEFAULT_TTL
    exp = getattr(cred, "expire_time", None)
    if exp:
        try:
            from datetime import datetime

            expiry = datetime.fromisoformat(str(exp).replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
    return token, expiry


class _Manager:
    """Owns the cached token and the pool built from it. Thread-safe, lazy."""

    def __init__(
        self,
        token_provider: Callable[[], tuple[str, float]] = _sdk_token_provider,
        pool_factory: Optional[Callable[[str], Any]] = None,
        user_resolver: Optional[Callable[[], str]] = None,
    ):
        self._token_provider = token_provider
        self._pool_factory = pool_factory or self._default_pool_factory
        self._user_resolver = user_resolver or _resolve_user
        self._lock = threading.Lock()
        self._token: str = ""
        self._token_expiry: float = 0.0
        self._pool: Any = None
        self._pool_token: str = ""

    # -- token --
    def _fresh_token(self) -> str:
        now = time.time()
        if self._token and now < (self._token_expiry - _TOKEN_SKEW_SECS):
            return self._token
        self._token, self._token_expiry = self._token_provider()
        return self._token

    # -- pool --
    def _default_pool_factory(self, token: str) -> Any:
        from psycopg_pool import ConnectionPool

        user = self._user_resolver()
        # search_path is set via the libpq `options` param at connect time (NOT a
        # SET statement in a configure callback — that opens a transaction the pool
        # then discards as INTRANS). autocommit is required: repo writes are single
        # statements with no explicit commit, and the pool rolls back on return.
        kwargs = dict(
            host=LAKEBASE_HOST,
            port=LAKEBASE_PORT,
            dbname=LAKEBASE_DB,
            user=user,
            password=token,
            sslmode="require",
            autocommit=True,
            options=f"-c search_path={LAKEBASE_SCHEMA},public",
        )
        return ConnectionPool(
            conninfo="",
            kwargs=kwargs,
            min_size=0,
            max_size=int(os.getenv("LAKEBASE_POOL_MAX", "8")),
            max_lifetime=_CONN_MAX_LIFETIME,
            timeout=float(os.getenv("LAKEBASE_POOL_TIMEOUT", "10")),
            open=True,
            name="docintel-lakebase",
        )

    def get_pool(self) -> Any:
        if not _is_enabled():
            raise LakebaseUnavailable("LAKEBASE_ENABLED is not truthy")
        if not LAKEBASE_HOST:
            raise LakebaseUnavailable("LAKEBASE_HOST is not set")
        with self._lock:
            token = self._fresh_token()
            if self._pool is None or token != self._pool_token:
                old = self._pool
                self._pool = self._pool_factory(token)
                self._pool_token = token
                if old is not None:
                    try:
                        old.close()
                    except Exception:
                        pass
            return self._pool

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                try:
                    self._pool.close()
                finally:
                    self._pool = None
                    self._pool_token = ""


def _resolve_user() -> str:
    """The Postgres login user. Prefer explicit config; else ask the SDK."""
    if LAKEBASE_USER:
        return LAKEBASE_USER
    try:
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient().current_user.me().user_name or ""
    except Exception as e:  # pragma: no cover - defensive
        raise LakebaseUnavailable(f"could not resolve Lakebase user: {e}")


# Module-level singleton manager (real deployment). Tests build their own.
_manager: Optional[_Manager] = None
_manager_lock = threading.Lock()


def _get_manager() -> _Manager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = _Manager()
    return _manager


@contextmanager
def connection():
    """Yield a pooled psycopg connection (search_path already set to the app schema).

    Raises LakebaseUnavailable if Lakebase is disabled/unreachable so callers can
    fall back to the warehouse path during cutover.
    """
    try:
        pool = _get_manager().get_pool()
    except LakebaseUnavailable:
        raise
    except Exception as e:
        raise LakebaseUnavailable(str(e))
    # Pool acquisition can fail (timeout, connection error) — surface as
    # LakebaseUnavailable so callers fall back to the warehouse instead of erroring.
    try:
        cm = pool.connection()
        conn = cm.__enter__()
    except Exception as e:
        raise LakebaseUnavailable(f"pool acquire failed: {e}")
    import sys as _sys
    try:
        yield conn
    except BaseException:
        if not cm.__exit__(*_sys.exc_info()):
            raise
    else:
        cm.__exit__(None, None, None)


def is_available() -> bool:
    """True if a trivial query succeeds against Lakebase; used for health/cutover."""
    try:
        with connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def close() -> None:
    if _manager is not None:
        _manager.close()
