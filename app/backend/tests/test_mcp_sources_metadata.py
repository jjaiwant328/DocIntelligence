"""Tests for the metadata tools added to mcp_sources in Task 7.

All tests monkeypatch `mcp_sources._call` so no live MCP server is needed.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mcp_sources


class _FakeCall:
    """Captures calls to _call and returns a pre-set value."""

    def __init__(self, return_value):
        self.return_value = return_value
        self.calls: list[dict] = []

    async def __call__(self, tool: str, args: dict):
        self.calls.append({"tool": tool, "args": args})
        return self.return_value


def test_list_children_tool_and_args(monkeypatch):
    items = [
        {"item_id": "f1", "name": "FolderA", "is_folder": True},
        {"item_id": "i1", "name": "report.pdf", "is_folder": False},
    ]
    fake = _FakeCall(items)
    monkeypatch.setattr(mcp_sources, "_call", fake)

    result = asyncio.run(mcp_sources.list_children("gdrive", "root123"))

    assert len(fake.calls) == 1
    c = fake.calls[0]
    assert c["tool"] == "list_children"
    assert c["args"]["source"] == "gdrive"
    assert c["args"]["folder_id"] == "root123"
    assert result == items


def test_list_children_default_folder_id(monkeypatch):
    fake = _FakeCall([])
    monkeypatch.setattr(mcp_sources, "_call", fake)
    asyncio.run(mcp_sources.list_children("gdrive"))
    assert fake.calls[0]["args"]["folder_id"] == ""


def test_get_file_metadata_tool_and_args(monkeypatch):
    meta = {"item_id": "i1", "name": "report.pdf", "is_folder": False, "size": 500}
    fake = _FakeCall(meta)
    monkeypatch.setattr(mcp_sources, "_call", fake)

    result = asyncio.run(mcp_sources.get_file_metadata("gdrive", "i1"))

    assert fake.calls[0]["tool"] == "get_file_metadata"
    assert fake.calls[0]["args"] == {"source": "gdrive", "item_id": "i1"}
    assert result == meta


def test_get_changes_tool_and_args(monkeypatch):
    payload = {"items": [{"item_id": "x", "name": "updated.pdf"}], "next_token": "tok42"}
    fake = _FakeCall(payload)
    monkeypatch.setattr(mcp_sources, "_call", fake)

    result = asyncio.run(mcp_sources.get_changes("gdrive", "prev_token"))

    assert fake.calls[0]["tool"] == "get_changes"
    assert fake.calls[0]["args"] == {"source": "gdrive", "since_token": "prev_token"}
    assert result == payload


def test_get_changes_default_since_token(monkeypatch):
    fake = _FakeCall({"items": [], "next_token": ""})
    monkeypatch.setattr(mcp_sources, "_call", fake)
    asyncio.run(mcp_sources.get_changes("gdrive"))
    assert fake.calls[0]["args"]["since_token"] == ""


def test_check_access_tool_and_args(monkeypatch):
    payload = {"can_read": True, "can_download": True}
    fake = _FakeCall(payload)
    monkeypatch.setattr(mcp_sources, "_call", fake)

    result = asyncio.run(mcp_sources.check_access("gdrive", "item99"))

    assert fake.calls[0]["tool"] == "check_access"
    assert fake.calls[0]["args"] == {"source": "gdrive", "item_id": "item99"}
    assert result == payload


def test_get_source_url_returns_string_directly(monkeypatch):
    """When the MCP tool returns a bare string, it passes through unchanged."""
    url = "https://drive.google.com/file/d/abc123"
    fake = _FakeCall(url)
    monkeypatch.setattr(mcp_sources, "_call", fake)

    result = asyncio.run(mcp_sources.get_source_url("gdrive", "abc123"))

    assert fake.calls[0]["tool"] == "get_source_url"
    assert fake.calls[0]["args"] == {"source": "gdrive", "item_id": "abc123"}
    assert result == url


def test_get_source_url_extracts_from_dict(monkeypatch):
    """When the MCP tool returns a dict, the URL is extracted."""
    fake = _FakeCall({"url": "https://drive.google.com/file/d/abc123"})
    monkeypatch.setattr(mcp_sources, "_call", fake)

    result = asyncio.run(mcp_sources.get_source_url("gdrive", "abc123"))
    assert result == "https://drive.google.com/file/d/abc123"


def test_get_source_url_extracts_webviewlink(monkeypatch):
    """Google Drive returns webViewLink — must be recognised."""
    fake = _FakeCall({"webViewLink": "https://docs.google.com/file/d/abc"})
    monkeypatch.setattr(mcp_sources, "_call", fake)

    result = asyncio.run(mcp_sources.get_source_url("gdrive", "abc"))
    assert result == "https://docs.google.com/file/d/abc"


def test_get_source_url_returns_empty_for_missing_key(monkeypatch):
    """Dict with no URL-like key must return '' not the string 'None'."""
    fake = _FakeCall({"some_other_key": "not_a_url"})
    monkeypatch.setattr(mcp_sources, "_call", fake)

    result = asyncio.run(mcp_sources.get_source_url("gdrive", "x"))
    assert result == "", f"expected empty string, got {result!r}"


def test_get_source_url_none_payload_returns_empty(monkeypatch):
    """None payload must return '' not 'None'."""
    fake = _FakeCall(None)
    monkeypatch.setattr(mcp_sources, "_call", fake)

    result = asyncio.run(mcp_sources.get_source_url("gdrive", "x"))
    assert result == "", f"expected empty string, got {result!r}"
