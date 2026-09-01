import os
import pytest
import obo

class FakeReq:
    def __init__(self, headers): self.headers = headers

def test_missing_header_raises_401():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        obo.user_ai_gateway_token(FakeReq({}))
    assert ei.value.status_code == 401

def test_uses_exchanger_and_returns_token():
    seen = {}
    def fake_exch(subject, **kw):
        seen["subject"] = subject
        return "AI_GW_TOKEN"
    tok = obo.user_ai_gateway_token(FakeReq({"x-forwarded-access-token": "USER_TOK"}),
                                    exchanger=fake_exch)
    assert tok == "AI_GW_TOKEN"
    assert seen["subject"] == "USER_TOK"

def test_exchange_payload_shape():
    captured = {}
    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"access_token": "X"}
    def fake_post(url, data=None, auth=None, timeout=None):
        captured["url"] = url; captured["data"] = data; captured["auth"] = auth
        return Resp()
    out = obo._exchange_token("USER_TOK", post=fake_post)
    assert out == "X"
    assert captured["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert captured["data"]["subject_token"] == "USER_TOK"
    assert captured["data"]["requested_token_type"] == "urn:ietf:params:oauth:token-type:access_token"
    assert captured["data"]["scope"] == "ai-gateway"
    assert captured["url"].endswith("/oidc/v1/token")
    assert captured["auth"] == (os.environ.get("DATABRICKS_CLIENT_ID", ""), os.environ.get("DATABRICKS_CLIENT_SECRET", ""))


def test_exchange_failure_raises_403():
    """A non-2xx exchange response must raise HTTPException 403, not propagate as 500."""
    from fastapi import HTTPException
    class BadResp:
        status_code = 400
        def json(self): return {}
    def fake_post(url, data=None, auth=None, timeout=None):
        return BadResp()
    with pytest.raises(HTTPException) as ei:
        obo._exchange_token("SECRET_TOKEN", post=fake_post)
    assert ei.value.status_code == 403
    # Token must never appear in the error detail
    assert "SECRET_TOKEN" not in (ei.value.detail or "")
