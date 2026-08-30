"""Unit tests for the blueprint provisioner — fake run_sql, no live services.
Run: cd app/backend && ../../.venv-test/bin/python tests/test_provisioner.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from provisioner import loader, provision  # noqa: E402


@pytest.fixture(autouse=True)
def _no_lakebase(monkeypatch):
    """create_project no-ops (Lakebase fallback) during provisioner tests.
    Scoped + auto-restored so it never leaks LAKEBASE_ENABLED to other modules
    (test_lakebase sets it truthy at import and must keep it)."""
    monkeypatch.delenv("LAKEBASE_ENABLED", raising=False)


class FakeSQL:
    def __init__(self, exists=False):
        self.queries = []
        self._exists = exists

    def __call__(self, q, *a, **k):
        self.queries.append(q)
        if "SELECT 1 FROM" in q and "domain_configs" in q:
            return [{"1": 1}] if self._exists else []
        return []

    def joined(self):
        return "\n".join(self.queries)


def test_blueprints_load_and_list():
    ids = {b["id"] for b in loader.list_blueprints()}
    assert {"supplier_performance", "ap_three_way_match", "blank"} <= ids, ids
    bp = loader.load_blueprint("supplier_performance")
    assert bp["reconciliation"]["subject_types"] == ["invoice"]


def test_blueprint_ref_resolution():
    bp = loader.load_blueprint("supplier_performance")
    steps = loader.resolve_blueprint_refs(bp["starter_workflow"]["steps"], bp)
    reconcile = next(s for s in steps if s["id"] == "reconcile")
    # $blueprint.reconciliation.checks must resolve to the literal list
    assert reconcile["inputs_map"]["checks"] == bp["reconciliation"]["checks"]
    assert reconcile["inputs_map"]["subject_types"] == ["invoice"]
    assert reconcile["inputs_map"]["documents"] == "$docs.items"


def test_dry_run_writes_nothing():
    fake = FakeSQL()
    res = provision.provision(blueprint_id="supplier_performance",
                              use_case_id="sp_demo", run_sql=fake, dry_run=True)
    assert res["ok"] and res["use_case_id"] == "sp_demo"
    assert all(s["status"] == "planned" for s in res["steps"])
    assert fake.queries == [], "dry_run must not execute SQL"


def test_provision_new_use_case():
    fake = FakeSQL(exists=False)
    res = provision.provision(blueprint_id="supplier_performance",
                              use_case_id="sp_demo", name="SP Demo", run_sql=fake)
    assert res["ok"], res["steps"]
    assert res["starter_workflow"] == "supplier_scorecard"
    j = fake.joined()
    assert "INSERT INTO jai_docintel.platform.domain_configs" in j
    assert "CREATE SCHEMA IF NOT EXISTS jai_docintel.sp_demo" in j
    assert "CREATE VOLUME IF NOT EXISTS jai_docintel.sp_demo.documents" in j
    assert "workflow_templates" in j          # starter workflow seeded
    assert "status='active'" in j             # marked active
    # the seeded template must carry the resolved checks list, not the $blueprint ref
    assert "price_variance" in j and "$blueprint" not in j


def test_provision_existing_updates():
    fake = FakeSQL(exists=True)
    res = provision.provision(blueprint_id="ap_three_way_match",
                              use_case_id="ap_demo", run_sql=fake)
    assert res["ok"], res["steps"]
    j = fake.joined()
    assert "UPDATE jai_docintel.platform.domain_configs SET" in j
    assert "INSERT INTO jai_docintel.platform.domain_configs" not in j


def test_unknown_blueprint():
    res = provision.provision(blueprint_id="nope", use_case_id="x", run_sql=FakeSQL())
    assert res["ok"] is False and "unknown blueprint" in res["error"]


# ── pipeline-job fold (create_domain_job.py) — no live services ────────────────

class FakeJob:
    def __init__(self, job_id):
        self.job_id = job_id


class FakeWS:
    """Records jobs.create / update_permissions / files.upload calls."""
    def __init__(self):
        self.created = None
        self.grants = []
        self.uploads = []
        outer = self

        class _Jobs:
            def create(self, **kw):
                outer.created = kw
                return FakeJob(4242)

            def update_permissions(self, job_id, access_control_list):
                outer.grants.append((job_id, access_control_list))

        class _Files:
            def upload(self, path, data, overwrite=False):
                outer.uploads.append(path)

        self.jobs = _Jobs()
        self.files = _Files()


def test_build_tasks_shape():
    from provisioner import pipeline_job as pj
    tasks = pj.build_tasks("sp_demo", "sp_demo", "documents", "jai_docintel",
                           nb_base="/nb")
    keys = [t.task_key for t in tasks]
    assert keys == ["workflow_prepare", "workflow_parse", "workflow_extract",
                    "idp_pipeline", "ontology_mapping", "agent"]
    # schema is baked into the notebook params, not hardcoded
    prep = tasks[0].notebook_task.base_parameters
    assert prep["schema"] == "sp_demo"
    assert prep["source_volume_path"] == "/Volumes/jai_docintel/sp_demo/documents/"
    assert tasks[0].notebook_task.notebook_path.startswith("/nb/")


def test_provision_with_pipeline_job():
    os.environ["DOCINTEL_APP_SP"] = "test-sp-0001"
    fake = FakeSQL(exists=False)
    ws = FakeWS()
    res = provision.provision(blueprint_id="ap_three_way_match", use_case_id="ap_demo",
                              run_sql=fake, create_pipeline_job=True, ws_client=ws)
    assert res["ok"], res["steps"]
    assert res["pipeline_job_id"] == 4242
    assert ws.created is not None and len(ws.created["tasks"]) == 6
    assert ws.grants, "app SP should be granted on the job"
    # job id registered back into analytics_config
    assert "pipeline_job_id" in fake.joined() and "4242" in fake.joined()
    assert any(s["step"] == "create_pipeline_job" and s["status"] == "ok"
               for s in res["steps"])


def test_pipeline_job_skipped_without_client():
    fake = FakeSQL(exists=False)
    res = provision.provision(blueprint_id="blank", use_case_id="b_demo",
                              run_sql=fake, create_pipeline_job=True)  # no ws_client
    assert res["ok"] and res["pipeline_job_id"] is None
    assert not any(s["step"] == "create_pipeline_job" for s in res["steps"])


if __name__ == "__main__":
    for fn in [test_blueprints_load_and_list, test_blueprint_ref_resolution,
               test_dry_run_writes_nothing, test_provision_new_use_case,
               test_provision_existing_updates, test_unknown_blueprint,
               test_build_tasks_shape, test_provision_with_pipeline_job,
               test_pipeline_job_skipped_without_client]:
        fn()
        print(f"  ok: {fn.__name__}")
    print("test_provisioner: all passed")
