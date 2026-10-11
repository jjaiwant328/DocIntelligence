"""Facade the routes call for operational state. Uses Lakebase when available;
raises LakebaseUnavailable so the caller can fall back to the Lakehouse warehouse
path during cutover. Once each table is verified live, the warehouse fallback in
the route can be removed.

Schema is ensured once per process (cheap CREATE IF NOT EXISTS), guarded so we
don't round-trip on every request.
"""
from __future__ import annotations

import threading
from typing import Optional

from . import lakebase
from . import schema as _schema
from .lakebase import LakebaseUnavailable
from .repositories import (
    projects_repo, runs_repo, tags_repo,
    sources_repo, use_cases_repo, index_jobs_repo,
    external_docs_repo, chunks_repo, connectors_repo,
)

_ensured = False
_ensure_lock = threading.Lock()


def _ensure() -> None:
    global _ensured
    if _ensured:
        return
    with _ensure_lock:
        if _ensured:
            return
        with lakebase.connection() as conn:
            _schema.ensure_schema(conn)
        _ensured = True


def available() -> bool:
    """True if the operational store is reachable (and schema ensured)."""
    try:
        _ensure()
        return True
    except LakebaseUnavailable:
        return False
    except Exception:
        return False


# ── Projects ──────────────────────────────────────────────────────────────────
def list_projects(domain_id: str) -> list[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return projects_repo.list_projects(conn, domain_id)


def name_exists(domain_id: str, name: str) -> bool:
    _ensure()
    with lakebase.connection() as conn:
        return projects_repo.name_exists(conn, domain_id, name)


def create_project(*, domain_id: str, project_id: str, name: str,
                   municipality: str = "", state: str = "", owner: str = "") -> None:
    _ensure()
    with lakebase.connection() as conn:
        projects_repo.create_project(
            conn, domain_id=domain_id, project_id=project_id, name=name,
            municipality=municipality, state=state, owner=owner,
        )


def update_members(*, domain_id: str, project_id: str,
                   owner: Optional[str] = None, collaborators: Optional[list] = None) -> None:
    _ensure()
    with lakebase.connection() as conn:
        projects_repo.update_members(
            conn, domain_id=domain_id, project_id=project_id,
            owner=owner, collaborators=collaborators,
        )


def delete_project(*, domain_id: str, project_id: str) -> None:
    _ensure()
    with lakebase.connection() as conn:
        projects_repo.delete_project(conn, domain_id=domain_id, project_id=project_id)


# ── Document tags ───────────────────────────────────────────────────────────────
def add_tags(*, domain_id: str, project_id: str, doc_ids: list, tagged_by: str = "app_user") -> int:
    _ensure()
    n = 0
    with lakebase.connection() as conn:
        for did in doc_ids or []:
            tags_repo.add_tag(conn, domain_id=domain_id, project_id=project_id,
                              doc_id=str(did), tagged_by=tagged_by)
            n += 1
    return n


def remove_tags(*, domain_id: str, project_id: str, doc_ids: list) -> int:
    _ensure()
    n = 0
    with lakebase.connection() as conn:
        for did in doc_ids or []:
            tags_repo.remove_tag(conn, domain_id=domain_id, project_id=project_id, doc_id=str(did))
            n += 1
    return n


def doc_ids_for_project(*, domain_id: str, project_id: str) -> list[str]:
    _ensure()
    with lakebase.connection() as conn:
        return tags_repo.doc_ids_for_project(conn, domain_id=domain_id, project_id=project_id)


# ── Workflow runs (lossless, auto-saved) ────────────────────────────────────────
def record_run(*, domain_id: str, project_id: str, run: dict, label: str = "") -> str:
    _ensure()
    with lakebase.connection() as conn:
        return runs_repo.record_run(conn, domain_id=domain_id, project_id=project_id,
                                    run=run, label=label)


def list_runs(*, domain_id: str, project_id=None, limit: int = 200) -> list[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return runs_repo.list_runs(conn, domain_id=domain_id, project_id=project_id, limit=limit)


def get_run(*, run_id: str):
    _ensure()
    with lakebase.connection() as conn:
        return runs_repo.get_run(conn, run_id)


def delete_run(*, run_id: str) -> bool:
    _ensure()
    with lakebase.connection() as conn:
        return runs_repo.delete_run(conn, run_id)


def rename_run(*, run_id: str, label: str) -> bool:
    _ensure()
    with lakebase.connection() as conn:
        return runs_repo.rename_run(conn, run_id, label)


# ── Sources ────────────────────────────────────────────────────────────────────
def list_sources() -> list[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return sources_repo.list_sources(conn)


def get_source(source_id: str) -> Optional[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return sources_repo.get_source(conn, source_id)


def upsert_source(source_id: str, provider: str, display_name: str,
                  auth_mode: str, credential_ref: str, site: str,
                  mode: str) -> dict:
    _ensure()
    with lakebase.connection() as conn:
        return sources_repo.upsert_source(
            conn, source_id, provider, display_name,
            auth_mode, credential_ref, site, mode,
        )


def set_source_status(source_id: str, status: str, last_error: str = "") -> None:
    _ensure()
    with lakebase.connection() as conn:
        sources_repo.set_status(conn, source_id, status, last_error)


# ── Use cases ──────────────────────────────────────────────────────────────────
def list_use_cases() -> list[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return use_cases_repo.list_use_cases(conn)


def get_use_case(use_case_id: str) -> Optional[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return use_cases_repo.get_use_case(conn, use_case_id)


def upsert_use_case(use_case_id: str, **fields) -> dict:
    _ensure()
    with lakebase.connection() as conn:
        return use_cases_repo.upsert_use_case(conn, use_case_id, **fields)


# ── Index jobs ─────────────────────────────────────────────────────────────────
def create_index_job(job_id: str, domain_id: str, project_id: str,
                     scope: str, scope_ref: str, requested_by: str) -> dict:
    _ensure()
    with lakebase.connection() as conn:
        return index_jobs_repo.create_job(conn, job_id, domain_id, project_id,
                                          scope, scope_ref, requested_by)


def get_index_job(job_id: str) -> Optional[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return index_jobs_repo.get_job(conn, job_id)


def list_index_jobs(domain_id: str, project_id: str) -> list[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return index_jobs_repo.list_jobs(conn, domain_id, project_id)


def start_index_job(job_id: str) -> None:
    _ensure()
    with lakebase.connection() as conn:
        index_jobs_repo.start(conn, job_id)


def bump_index_job(job_id: str, **counts: int) -> None:
    _ensure()
    with lakebase.connection() as conn:
        index_jobs_repo.bump(conn, job_id, **counts)


def finish_index_job(job_id: str, status: str, error_summary: str = "") -> None:
    _ensure()
    with lakebase.connection() as conn:
        index_jobs_repo.finish(conn, job_id, status, error_summary)


# ── External documents ────────────────────────────────────────────────────────
def upsert_doc_metadata(doc: dict) -> None:
    _ensure()
    with lakebase.connection() as conn:
        external_docs_repo.upsert_metadata(conn, doc)


def list_docs_for_project(domain_id: str, project_id: str,
                          statuses: Optional[list] = None) -> list[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return external_docs_repo.list_for_project(conn, domain_id, project_id, statuses)


def set_doc_status(external_document_id: str, status: str,
                   last_error: str = "") -> None:
    _ensure()
    with lakebase.connection() as conn:
        external_docs_repo.set_status(conn, external_document_id, status, last_error)


def set_doc_included(external_document_id: str, included: bool) -> None:
    _ensure()
    with lakebase.connection() as conn:
        external_docs_repo.set_included(conn, external_document_id, included)


def mark_doc_indexed(external_document_id: str, index_version: int,
                     embedding_model: str, etag: str, chunk_count: int) -> None:
    _ensure()
    with lakebase.connection() as conn:
        external_docs_repo.mark_indexed(conn, external_document_id, index_version,
                                        embedding_model, etag, chunk_count)


def doc_ids_missing_from(domain_id: str, project_id: str,
                         seen_ids: set) -> list[str]:
    _ensure()
    with lakebase.connection() as conn:
        return external_docs_repo.ids_missing_from(conn, domain_id, project_id, seen_ids)


# ── Chunks ────────────────────────────────────────────────────────────────────
def replace_chunks(external_document_id: str, chunks: list[dict]) -> int:
    _ensure()
    with lakebase.connection() as conn:
        return chunks_repo.replace_chunks(conn, external_document_id, chunks)


def delete_chunks_for_doc(external_document_id: str) -> int:
    _ensure()
    with lakebase.connection() as conn:
        return chunks_repo.delete_for_doc(conn, external_document_id)


def list_chunks_for_doc(external_document_id: str) -> list[dict]:
    """Snippets for one indexed document — used to build the engine doc-set text.

    Callers are responsible for catching LakebaseUnavailable; this function does
    not suppress it.
    """
    _ensure()
    with lakebase.connection() as conn:
        return chunks_repo.list_for_doc(conn, external_document_id)


def hybrid_search(domain_id: str, project_id: str, query_embedding: list,
                  query_text: str, k: int = 10, folder: str = "",
                  types: Optional[list] = None) -> list[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return chunks_repo.hybrid_search(conn, domain_id, project_id,
                                         query_embedding, query_text,
                                         k=k, folder=folder, types=types)


# ── Connectors ─────────────────────────────────────────────────────────────────

def list_connectors() -> list[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return connectors_repo.list_connectors(conn)


def get_connector(provider: str) -> Optional[dict]:
    _ensure()
    with lakebase.connection() as conn:
        return connectors_repo.get_connector(conn, provider)


def upsert_connector(provider: str, display_name: str, client_id: str,
                     redirect_uri: str, scopes: list, secret_ref: str,
                     status: str, updated_by: str) -> dict:
    _ensure()
    with lakebase.connection() as conn:
        return connectors_repo.upsert_connector(
            conn, provider, display_name, client_id,
            redirect_uri, scopes, secret_ref, status, updated_by,
        )


def set_connector_status(provider: str, status: str) -> None:
    _ensure()
    with lakebase.connection() as conn:
        connectors_repo.set_status(conn, provider, status)


def delete_connector(provider: str) -> None:
    _ensure()
    with lakebase.connection() as conn:
        connectors_repo.delete_connector(conn, provider)
