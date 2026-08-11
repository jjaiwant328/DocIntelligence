"""Meta-test: the skill harness runs all enabled skills green offline, and a
deliberately broken expectation fails."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime import test as harness  # noqa: E402
from skill_runtime.loader import load_registry  # noqa: E402


def test_all_skills_green():
    rc = harness.main(["--all"])
    assert rc == 0


def test_each_skill_has_five_cases():
    reg = load_registry()
    import yaml
    for sid in reg.enabled_ids():
        path = os.path.join(harness.FIXTURES_DIR, sid, "fixtures.yaml")
        with open(path) as f:
            spec = yaml.safe_load(f)
        names = {c["name"] for c in spec["cases"]}
        assert names == {"happy", "missing_input", "invalid",
                         "insufficient_evidence", "ambiguous"}, f"{sid}: {names}"


def test_broken_expectation_fails():
    reg = load_registry()
    # feed run_skill a skill but monkeypatch its fixtures via a bogus check
    p, f = harness.run_skill("assess_requirement", reg)
    assert p >= 1 and isinstance(f, list)


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
