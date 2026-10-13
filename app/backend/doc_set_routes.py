"""Doc-set assembly: pinned + query-defined sets over Lakebase documents."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import lakebase
from db.repositories import doc_sets_repo

router = APIRouter(prefix="/api/doc-sets", tags=["doc-sets"])


class DocSetCreate(BaseModel):
    domain_id: str
    name: str
    kind: str = "pinned"
    filter_json: dict = {}


class PinRequest(BaseModel):
    doc_ids: list[str]


@router.get("")
def list_sets(domain_id: str):
    with lakebase.connection() as conn:
        return {"doc_sets": doc_sets_repo.list_for_domain(conn, domain_id)}


@router.post("")
def create_set(req: DocSetCreate):
    if req.kind not in ("pinned", "query"):
        raise HTTPException(status_code=400, detail="kind must be pinned|query")
    set_id = uuid.uuid4().hex[:12]
    with lakebase.connection() as conn:
        return doc_sets_repo.create(conn, set_id=set_id, domain_id=req.domain_id,
                                    name=req.name, kind=req.kind,
                                    filter_json=req.filter_json)


@router.delete("/{set_id}")
def delete_set(set_id: str):
    with lakebase.connection() as conn:
        if not doc_sets_repo.get(conn, set_id):
            raise HTTPException(status_code=404, detail=f"no doc-set '{set_id}'")
        doc_sets_repo.delete(conn, set_id)
    return {"deleted": set_id}


def _resolve_query_set(conn, filter_json: dict) -> list[dict]:
    wheres, params = ["TRUE"], []
    if filter_json.get("source_ids"):
        wheres.append("source_id = ANY(%s)")
        params.append(filter_json["source_ids"])
    if filter_json.get("doc_types"):
        wheres.append("mime_type = ANY(%s)")
        params.append(filter_json["doc_types"])
    if filter_json.get("text"):
        wheres.append("(name ILIKE %s OR path ILIKE %s)")
        like = f"%{filter_json['text']}%"
        params += [like, like]
    cur = conn.cursor()
    cur.execute(
        f"""SELECT external_document_id, name, path, web_url, mime_type, doc_type, status
            FROM external_documents WHERE {' AND '.join(wheres)}
            ORDER BY name LIMIT 500""",
        params,
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


@router.get("/{set_id}/docs")
def set_docs(set_id: str):
    with lakebase.connection() as conn:
        s = doc_sets_repo.get(conn, set_id)
        if not s:
            raise HTTPException(status_code=404, detail=f"no doc-set '{set_id}'")
        if s["kind"] == "pinned":
            ids = doc_sets_repo.pinned_ids(conn, set_id)
            if not ids:
                return {"documents": []}
            cur = conn.cursor()
            cur.execute(
                """SELECT external_document_id, name, path, web_url, mime_type, doc_type, status
                   FROM external_documents WHERE external_document_id = ANY(%s)""",
                (ids,),
            )
            cols = [c[0] for c in cur.description]
            return {"documents": [dict(zip(cols, row)) for row in cur.fetchall()]}
        fj = s["filter_json"]
        if isinstance(fj, str):
            fj = json.loads(fj)
        return {"documents": _resolve_query_set(conn, fj)}


@router.post("/{set_id}/pin")
def pin(set_id: str, req: PinRequest):
    with lakebase.connection() as conn:
        s = doc_sets_repo.get(conn, set_id)
        if not s:
            raise HTTPException(status_code=404, detail=f"no doc-set '{set_id}'")
        if s["kind"] != "pinned":
            raise HTTPException(status_code=400, detail="cannot pin into a query set")
        for did in req.doc_ids:
            doc_sets_repo.pin(conn, set_id, did)
    return {"pinned": len(req.doc_ids)}


@router.delete("/{set_id}/pin/{doc_id}")
def unpin(set_id: str, doc_id: str):
    with lakebase.connection() as conn:
        doc_sets_repo.unpin(conn, set_id, doc_id)
    return {"unpinned": doc_id}
