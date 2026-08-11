"""Skill test harness (docs Phase 6). Runs each enabled skill through five
fixture classes offline using a fake Context built from each fixture's `fake`
block. LLM skills assert on structure/invariants, not exact prose.

Usage (from app/backend/):
    python -m skill_runtime.test --skill assess_requirement
    python -m skill_runtime.test --all
"""
from __future__ import annotations

import argparse
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.adapters.base import Context  # noqa: E402
from skill_runtime.dispatcher import Dispatcher  # noqa: E402
from skill_runtime.loader import load_registry  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(os.path.dirname(_HERE), "tests", "skills")


def _build_ctx(fake: dict) -> Context:
    """Turn a fixture 'fake' block into injected seams."""
    return Context(
        vs_search=(lambda *a, **k: fake["rows"]) if "rows" in fake else None,
        run_sql=(lambda q: fake.get("sql_rows", [])) if "sql_rows" in fake else None,
        chat_completion=(lambda p: fake["model"]) if "model" in fake else None,
        resolve_model=lambda: "fake-model",
        internal={fake["internal_name"]: (lambda i, c: (fake["internal_out"], []))}
        if "internal_name" in fake else {},
    )


def _check(expect: dict, result) -> list:
    errs = []
    if "status" in expect and result.status != expect["status"]:
        errs.append(f"status {result.status!r} != {expect['status']!r}")
    if "error_contains" in expect:
        if not result.error or expect["error_contains"] not in result.error:
            errs.append(f"error {result.error!r} lacks {expect['error_contains']!r}")
    if "min_evidence" in expect and len(result.evidence) < expect["min_evidence"]:
        errs.append(f"evidence {len(result.evidence)} < {expect['min_evidence']}")
    if "output_has" in expect:
        for key in expect["output_has"]:
            if key not in result.outputs:
                errs.append(f"missing output key {key!r}")
    if "confidence_present" in expect and expect["confidence_present"]:
        if result.outputs.get("confidence") is None:
            errs.append("confidence missing")
    return errs


def run_skill(skill_id: str, registry) -> tuple:
    path = os.path.join(FIXTURES_DIR, skill_id, "fixtures.yaml")
    if not os.path.exists(path):
        return 0, [f"{skill_id}: no fixtures.yaml"]
    with open(path) as f:
        spec = yaml.safe_load(f)
    passed, failures = 0, []
    for case in spec.get("cases", []):
        name = case.get("name", "?")
        ctx = _build_ctx(case.get("fake", {}))
        d = Dispatcher(registry, ctx)
        result = d.invoke(skill_id, case.get("inputs", {}))
        errs = _check(case.get("expect", {}), result)
        if errs:
            failures.append(f"{skill_id}/{name}: " + "; ".join(errs))
        else:
            passed += 1
    return passed, failures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)

    registry = load_registry()
    skills = registry.enabled_ids() if args.all else [args.skill]
    if not skills or skills == [None]:
        print("specify --skill <id> or --all")
        return 2

    total_pass, total_fail = 0, []
    for sid in skills:
        p, f = run_skill(sid, registry)
        total_pass += p
        total_fail += f
        mark = "OK" if not f else "FAIL"
        print(f"{mark} {sid}: {p} passed, {len(f)} failed")
    for msg in total_fail:
        print("  -", msg)
    print(f"\n{total_pass} passed, {len(total_fail)} failed")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
