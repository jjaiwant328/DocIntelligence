"""Intent router tests (offline; injected chat_completion)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime.intent import classify, Intent, CONSEQUENTIAL_SKILLS  # noqa: E402

TEMPLATES = ["due_diligence"]
SKILLS = ["create_work_object", "assess_requirement", "create_action"]


def _fixed(resp):
    return lambda prompt: resp


def test_workflow_run_intent():
    r = classify("Run due diligence for Store 1827",
                 _fixed('{"kind":"workflow_run","template":"due_diligence","project":"Store 1827","confirm_action":false}'),
                 TEMPLATES, SKILLS)
    assert r.kind == "workflow_run" and r.template == "due_diligence"
    assert r.project == "Store 1827" and r.requires_confirmation is False


def test_create_action_requires_confirmation():
    r = classify("Create the required actions",
                 _fixed('{"kind":"skill_invoke","skill":"create_action","confirm_action":true}'),
                 TEMPLATES, SKILLS)
    assert r.kind == "skill_invoke" and r.skill == "create_action"
    assert r.requires_confirmation is True


def test_consequential_skill_forces_confirmation_even_if_llm_forgets():
    r = classify("log the actions",
                 _fixed('{"kind":"skill_invoke","skill":"create_action","confirm_action":false}'),
                 TEMPLATES, SKILLS)
    assert r.requires_confirmation is True  # forced by CONSEQUENTIAL_SKILLS


def test_conversational_intent():
    r = classify("What is a zoning permit?",
                 _fixed('{"kind":"conversational","template":null,"skill":null,"confirm_action":false}'),
                 TEMPLATES, SKILLS)
    assert r.kind == "conversational" and r.requires_confirmation is False


def test_malformed_llm_defaults_conversational():
    r = classify("hello", _fixed("not json at all"), TEMPLATES, SKILLS)
    assert r.kind == "conversational"


def test_invalid_kind_coerced():
    r = classify("x", _fixed('{"kind":"delete_everything"}'), TEMPLATES, SKILLS)
    assert r.kind == "conversational"


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
