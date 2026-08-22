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
from .repositories import projects_repo, runs_repo, tags_repo

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
