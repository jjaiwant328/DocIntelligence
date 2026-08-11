"""Tests for skill_runtime.loader."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.loader import load_registry  # noqa: E402
from skill_runtime.models import _ALLOWED_ADAPTERS  # noqa: E402

SLICE = {
    "create_work_object", "extract_requirements", "find_supporting_evidence",
    "assess_requirement", "identify_gap", "assess_risk",
    "generate_recommendation", "create_action",
}


def test_registry_loads_and_validates():
    reg = load_registry()
    assert reg.validate() == [], reg.validate()


def test_enabled_ids_are_the_slice():
    reg = load_registry()
    assert set(reg.enabled_ids()) == SLICE


def test_every_enabled_has_contract_with_known_adapter():
    reg = load_registry()
    for sid in reg.enabled_ids():
        c = reg.get(sid)
        assert c.adapter in _ALLOWED_ADAPTERS
        assert c.id == sid and c.version


def test_list_all_includes_stubs():
    reg = load_registry()
    all_rows = reg.list(enabled_only=False)
    enabled = reg.list(enabled_only=True)
    assert len(all_rows) > len(enabled)   # stubs present
    assert len(enabled) == 8


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
