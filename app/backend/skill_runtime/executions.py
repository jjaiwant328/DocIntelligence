"""platform.skill_executions — per-invocation observability (ADR-007, spec §5).

Idempotent DDL + a logger that writes one row per skill invocation. Logging
failures never break a run (they are swallowed and printed)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

CATALOG_DEFAULT = "jai_docintel"


def executions_table(catalog: str = CATALOG_DEFAULT) -> str:
    return f"{catalog}.platform.skill_executions"


def ensure_table(run_sql: Callable[[str], Any], catalog: str = CATALOG_DEFAULT) -> None:
    run_sql(f"""
        CREATE TABLE IF NOT EXISTS {executions_table(catalog)} (
            execution_id     STRING,
            skill_id         STRING,
            skill_version    STRING,
            workflow_id      STRING,
            workflow_version STRING,
            work_object_id   STRING,
            start_time       TIMESTAMP,
            end_time         TIMESTAMP,
            status           STRING,
            error            STRING,
            model            STRING,
            evidence_count   INT,
            inputs_digest    STRING
        ) USING DELTA
    """)


@dataclass
class ExecutionRecord:
    skill_id: str
    skill_version: str = ""
    workflow_id: str = ""
    workflow_version: str = ""
    work_object_id: str = ""
    start_time: str = ""
    end_time: str = ""
    status: str = ""
    error: Optional[str] = None
    model: Optional[str] = None
    evidence_count: int = 0
    inputs_digest: str = ""
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _sql_lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


class ExecutionLogger:
    """Writes ExecutionRecords. In-memory `records` always captured (used by tests
    and by the engine to build per-run history); SQL write is best-effort."""

    def __init__(self, run_sql: Optional[Callable[[str], Any]] = None,
                 catalog: str = CATALOG_DEFAULT):
        self.run_sql = run_sql
        self.catalog = catalog
        self.records: list = []

    def log(self, rec: ExecutionRecord) -> None:
        self.records.append(rec)
        if self.run_sql is None:
            return
        try:
            self.run_sql(f"""
                INSERT INTO {executions_table(self.catalog)} VALUES (
                    {_sql_lit(rec.execution_id)}, {_sql_lit(rec.skill_id)},
                    {_sql_lit(rec.skill_version)}, {_sql_lit(rec.workflow_id)},
                    {_sql_lit(rec.workflow_version)}, {_sql_lit(rec.work_object_id)},
                    {_ts(rec.start_time)}, {_ts(rec.end_time)},
                    {_sql_lit(rec.status)}, {_sql_lit(rec.error)},
                    {_sql_lit(rec.model)}, {rec.evidence_count},
                    {_sql_lit(rec.inputs_digest)}
                )
            """)
        except Exception as e:  # never break a run on logging failure
            print(f"[skill_executions] log failed: {e}")


def _ts(iso: str) -> str:
    if not iso:
        return "NULL"
    return f"CAST('{iso}' AS TIMESTAMP)"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
