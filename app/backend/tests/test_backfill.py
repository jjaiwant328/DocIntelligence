import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import contextmanager

from scripts import backfill_spine_to_lakebase as bf


def test_doc_row_shape():
    row = bf._doc_row("supply_chain", {
        "doc_id": "a.txt", "doc_type": "invoice", "source_file": "/Volumes/jai_docintel/raw/documents/a.txt",
    })
    assert row["external_document_id"] == "a.txt"
    assert row["source_id"] == "uc_volume"
    assert row["domain_id"] == "supply_chain"
    assert row["web_url"] == "/Volumes/jai_docintel/raw/documents/a.txt"
    assert row["status"] == "indexed"
    assert row["doc_type"] == "invoice"


def test_field_row_shape():
    f = bf._field_row("a.txt", {"field_name": "total", "field_value": "$5"})
    assert f == {"field_name": "total", "field_value": "$5", "page": None,
                 "bbox": None, "source_text": "", "confidence": None}


def test_chunk_row_carries_embedding():
    c = bf._chunk_row("supply_chain", "a.txt", {
        "doc_id": "a.txt", "chunk_position": 0,
        "chunk_to_retrieve": "hello world", "embedding": [0.1, 0.2],
    })
    assert c["external_document_id"] == "a.txt"
    assert c["chunk_id"] == "a.txt:0"
    assert c["domain_id"] == "supply_chain"
    assert c["project_id"] == "default"
    assert c["ordinal"] == 0
    assert c["embedding"] == [0.1, 0.2]
    assert c["snippet"] == "hello world"


def test_chunk_row_parses_string_embedding():
    # SQL statement-execution returns ARRAY columns as JSON strings, with the
    # elements themselves quoted — normalize to floats.
    c = bf._chunk_row("supply_chain", "a.txt", {
        "doc_id": "a.txt", "chunk_position": 3,
        "chunk_to_retrieve": "x", "embedding": '["0.5", "0.25"]',
    })
    assert c["chunk_id"] == "a.txt:3"
    assert c["embedding"] == [0.5, 0.25]

    c2 = bf._chunk_row("supply_chain", "a.txt", {
        "doc_id": "a.txt", "chunk_position": 4,
        "chunk_to_retrieve": "x", "embedding": ["0.5", "0.25"],
    })
    assert c2["embedding"] == [0.5, 0.25]


def test_backfill_updates_doc_type(monkeypatch):
    executed = []

    class _Cur:
        def execute(self, sql, params=None):
            executed.append((sql, params))

    class _Conn:
        def cursor(self):
            return _Cur()

    @contextmanager
    def _fake_connection():
        yield _Conn()

    monkeypatch.setattr(bf.lakebase, "connection", _fake_connection)
    monkeypatch.setattr(bf, "_sql", lambda w, wh, stmt: (
        [{"doc_id": "a.txt", "doc_type": "invoice", "source_file": "/v/a.txt"}]
        if "gold_documents" in stmt else []))
    monkeypatch.setattr(bf.external_docs_repo, "upsert_metadata", lambda conn, row: None)
    monkeypatch.setattr(bf.extracted_fields_repo, "replace_for_doc", lambda conn, did, fields: 0)
    monkeypatch.setattr(bf.chunks_repo, "replace_chunks", lambda conn, did, chunks: 0)

    counts = bf.backfill_domain(None, "wh", "supply_chain")

    assert counts["docs"] == 1
    updates = [e for e in executed
               if e[0].startswith("UPDATE external_documents SET doc_type")]
    assert updates == [(
        "UPDATE external_documents SET doc_type=%s WHERE external_document_id=%s",
        ("invoice", "a.txt"),
    )]
