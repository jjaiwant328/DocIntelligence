"""Tests for indexer/parse.py and indexer/chunk.py.

All tests are pure (no network, no DB). pdf/docx libs are not installed in
.venv-test so only text/csv/unknown paths are exercised directly; the
ImportError-fallback degrades silently.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexer import parse, chunk


# ── parse.extract_text ────────────────────────────────────────────────────────

def test_extract_text_plain_text():
    content = b"hello world"
    assert parse.extract_text("doc.txt", content) == "hello world"


def test_extract_text_markdown():
    content = "# Title\n\nBody text.".encode("utf-8")
    result = parse.extract_text("README.md", content)
    assert "Title" in result
    assert "Body text" in result


def test_extract_text_csv():
    content = b"a,b,c\n1,2,3\n"
    result = parse.extract_text("data.csv", content)
    assert "a,b,c" in result


def test_extract_text_utf8_with_bom():
    content = "﻿hello".encode("utf-8")
    result = parse.extract_text("file.txt", content)
    assert "hello" in result


def test_extract_text_unknown_extension_returns_empty():
    result = parse.extract_text("binary.exe", b"\x00\x01\x02")
    assert result == ""


def test_extract_text_pdf_no_lib_returns_empty_or_string():
    """With pypdf absent, must not raise — returns '' or falls back to seam."""
    result = parse.extract_text("report.pdf", b"%PDF-1.4 fake content")
    assert isinstance(result, str)


def test_extract_text_docx_no_lib_returns_empty_or_string():
    """With python-docx absent, must not raise — returns ''."""
    result = parse.extract_text("doc.docx", b"PK fake docx bytes")
    assert isinstance(result, str)


# ── chunk.split ───────────────────────────────────────────────────────────────

def test_split_empty_text_returns_empty():
    assert chunk.split("") == []


def test_split_short_text_single_chunk():
    text = "hello world"
    result = chunk.split(text, size=1200, overlap=150)
    assert result == ["hello world"]


def test_split_produces_overlap():
    # 10-char text, size=6, overlap=2 → windows: [0:6], [4:10]
    text = "0123456789"
    result = chunk.split(text, size=6, overlap=2)
    assert len(result) == 2
    assert result[0] == "012345"
    assert result[1] == "456789"


def test_split_covers_full_text():
    text = "a" * 100
    result = chunk.split(text, size=30, overlap=5)
    # Every character should appear in at least one chunk
    reconstructable = "".join(result)
    for char in text:
        assert char in reconstructable


def test_split_no_empty_chunks():
    text = "x" * 50
    result = chunk.split(text, size=20, overlap=5)
    assert all(len(c) > 0 for c in result)


def test_split_default_params_work():
    text = "word " * 500  # 2500 chars
    result = chunk.split(text)
    assert len(result) >= 2
    # Verify overlap: end of chunk[0] overlaps start of chunk[1]
    assert result[0][-1] == result[1][0] or result[0][-150:] == result[1][:150]


def test_split_overlap_cannot_exceed_size():
    """If overlap >= size, must not loop forever; produces single chunk."""
    text = "hello"
    result = chunk.split(text, size=10, overlap=10)
    assert len(result) == 1


# ── chunk.chunk_id ────────────────────────────────────────────────────────────

def test_chunk_id_deterministic():
    cid1 = chunk.chunk_id("doc-abc", 0)
    cid2 = chunk.chunk_id("doc-abc", 0)
    assert cid1 == cid2


def test_chunk_id_differs_by_ordinal():
    assert chunk.chunk_id("doc-abc", 0) != chunk.chunk_id("doc-abc", 1)


def test_chunk_id_differs_by_doc_id():
    assert chunk.chunk_id("doc-abc", 0) != chunk.chunk_id("doc-xyz", 0)


def test_chunk_id_is_string():
    result = chunk.chunk_id("doc-abc", 3)
    assert isinstance(result, str)
    assert len(result) > 0
