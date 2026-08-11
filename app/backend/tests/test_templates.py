"""All workflow templates load and reference only enabled skills."""
import os
import sys
import glob

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.loader import load_registry  # noqa: E402
from workflow_engine.engine import DEFAULT_TEMPLATES_DIR  # noqa: E402  # defined in engine.py

EXPECTED = {"due_diligence", "investigation", "compliance_audit", "change_monitoring"}


def _templates():
    return glob.glob(os.path.join(DEFAULT_TEMPLATES_DIR, "*.yaml"))


def test_all_expected_templates_present():
    ids = set()
    for p in _templates():
        with open(p) as f:
            ids.add(yaml.safe_load(f)["id"])
    assert EXPECTED <= ids, EXPECTED - ids


def test_templates_reference_only_enabled_skills():
    enabled = set(load_registry().enabled_ids())
    for p in _templates():
        with open(p) as f:
            tmpl = yaml.safe_load(f)
        for step in tmpl["steps"]:
            assert step["skill"] in enabled, f"{tmpl['id']}: {step['skill']} not enabled"


def test_templates_have_version_and_steps():
    for p in _templates():
        with open(p) as f:
            tmpl = yaml.safe_load(f)
        assert tmpl.get("version") and tmpl.get("steps")
        for step in tmpl["steps"]:
            assert "id" in step and "skill" in step


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
