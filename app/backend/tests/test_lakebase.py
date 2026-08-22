"""Unit tests for db.lakebase token/pool lifecycle — no live database.

We inject a fake token_provider and pool_factory to prove:
  - a valid cached token is reused (no re-mint)
  - a near-expiry token triggers a re-mint AND a pool rebuild (old pool closed)
Run: cd app/backend && ../../.venv-test/bin/python tests/test_lakebase.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["LAKEBASE_ENABLED"] = "true"
os.environ["LAKEBASE_HOST"] = "fake-host"

from db import lakebase  # noqa: E402


class FakePool:
    def __init__(self, token):
        self.token = token
        self.closed = False

    def close(self):
        self.closed = True


def test_token_cached_while_valid():
    mints = {"n": 0}

    def provider():
        mints["n"] += 1
        return f"tok{mints['n']}", time.time() + 3600  # far from expiry

    pools = []

    def factory(token):
        p = FakePool(token)
        pools.append(p)
        return p

    m = lakebase._Manager(token_provider=provider, pool_factory=factory,
                          user_resolver=lambda: "u")
    p1 = m.get_pool()
    p2 = m.get_pool()
    assert p1 is p2, "pool should be reused while token valid"
    assert mints["n"] == 1, "token should be minted once"
    assert len(pools) == 1


def test_expiring_token_rebuilds_pool():
    state = {"n": 0}

    def provider():
        state["n"] += 1
        # first token already within the refresh skew → forces re-mint next call
        ttl = 1 if state["n"] == 1 else 3600
        return f"tok{state['n']}", time.time() + ttl

    pools = []

    def factory(token):
        p = FakePool(token)
        pools.append(p)
        return p

    m = lakebase._Manager(token_provider=provider, pool_factory=factory,
                          user_resolver=lambda: "u")
    p1 = m.get_pool()
    p2 = m.get_pool()
    assert p1 is not p2, "near-expiry token must rebuild the pool"
    assert p1.closed is True, "old pool must be closed on rebuild"
    assert state["n"] == 2 and len(pools) == 2


def test_disabled_raises():
    os.environ["LAKEBASE_ENABLED"] = "false"
    try:
        m = lakebase._Manager(token_provider=lambda: ("t", time.time() + 99),
                              pool_factory=lambda t: FakePool(t),
                              user_resolver=lambda: "u")
        raised = False
        try:
            m.get_pool()
        except lakebase.LakebaseUnavailable:
            raised = True
        assert raised, "get_pool must raise LakebaseUnavailable when disabled"
    finally:
        os.environ["LAKEBASE_ENABLED"] = "true"


if __name__ == "__main__":
    test_token_cached_while_valid()
    test_expiring_token_rebuilds_pool()
    test_disabled_raises()
    print("test_lakebase: all passed")
