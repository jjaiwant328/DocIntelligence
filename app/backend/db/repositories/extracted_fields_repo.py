"""extracted_fields rows: evidence-linked field values per document."""
from __future__ import annotations
import json
from typing import Any

_COLS = ["field_name", "field_value", "page", "bbox", "source_text", "confidence"]


def _dicts(cur: Any) -> list[dict]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def replace_for_doc(conn: Any, doc_id: str, fields: list[dict]) -> int:
    cur = conn.cursor()
    cur.execute("DELETE FROM extracted_fields WHERE doc_id=%s", (doc_id,))
    for f in fields:
        cur.execute(
            """INSERT INTO extracted_fields
               (doc_id, field_name, field_value, page, bbox, source_text, confidence)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (doc_id, f["field_name"], f.get("field_value", ""), f.get("page"),
             json.dumps(f.get("bbox")) if f.get("bbox") is not None else None,
             f.get("source_text", ""), f.get("confidence")),
        )
    return len(fields)


def list_for_doc(conn: Any, doc_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        f"SELECT {', '.join(_COLS)} FROM extracted_fields WHERE doc_id=%s ORDER BY field_name",
        (doc_id,),
    )
    return _dicts(cur)


def set_confidence(conn: Any, doc_id: str, field_name: str, confidence: float) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE extracted_fields SET confidence=%s, updated_at=now() WHERE doc_id=%s AND field_name=%s",
        (confidence, doc_id, field_name),
    )
