"""template_store round-trip with a fake in-memory run_sql (offline)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skill_runtime import template_store as ts  # noqa: E402


class FakeSQL:
    """Minimal fake: supports the exact CREATE/DELETE/INSERT/UPDATE/SELECT this
    module emits, backed by a list of row dicts."""
    def __init__(self):
        self.rows = []

    def __call__(self, sql):
        s = sql.strip()
        if s.startswith("CREATE TABLE"):
            return []
        if s.startswith("DELETE"):
            did = _m(r"domain_id = '([^']*)'", s); tid = _m(r"template_id = '([^']*)'", s)
            self.rows = [r for r in self.rows if not (r["domain_id"] == did and r["template_id"] == tid)]
            return []
        if s.startswith("INSERT"):
            vals = re.search(r"VALUES\s*\((.*)\)", s, re.DOTALL).group(1)
            # naive positional parse of our known column order
            parts = _split_vals(vals)
            self.rows.append({
                "template_id": parts[0], "domain_id": parts[1], "name": parts[2],
                "description": parts[3], "version": parts[4], "status": parts[5],
                "approval_before": None if parts[6] == "NULL" else parts[6],
                "steps_json": parts[7],
            })
            return []
        if s.startswith("UPDATE"):
            did = _m(r"domain_id = '([^']*)'", s); tid = _m(r"template_id = '([^']*)'", s)
            for r in self.rows:
                if r["domain_id"] == did and r["template_id"] == tid:
                    r["status"] = "archived"
            return []
        if s.startswith("SELECT"):
            did = _m(r"domain_id = '([^']*)'", s)
            tid = _m(r"template_id = '([^']*)'", s)
            out = [r for r in self.rows if r["domain_id"] == did and r.get("status") != "archived"]
            if tid:
                out = [r for r in out if r["template_id"] == tid]
            return out
        return []


def _m(pat, s):
    m = re.search(pat, s)
    return m.group(1) if m else None


def _split_vals(vals):
    # our INSERT uses '...'/NULL/TIMESTAMP '...'; grab quoted strings + NULL in order
    toks = re.findall(r"NULL|TIMESTAMP '[^']*'|'((?:[^']|'')*)'", vals)
    # re.findall with a group returns the group for quoted, '' for NULL/timestamp
    out = []
    for full, grp in zip(re.finditer(r"NULL|TIMESTAMP '[^']*'|'(?:[^']|'')*'", vals), toks):
        t = full.group(0)
        if t == "NULL":
            out.append("NULL")
        elif t.startswith("TIMESTAMP"):
            out.append("<ts>")
        else:
            out.append(t[1:-1].replace("''", "'"))
    return out


STEPS = [{"id": "s1", "skill": "create_work_object", "inputs_map": {"domain": "$input.domain"}}]


def test_save_list_get_delete_roundtrip():
    sql = FakeSQL()
    ts.save_template(sql, "compliance", "my_tpl", "My Template", STEPS,
                     approval_before="create_action")
    lst = ts.list_templates(sql, "compliance")
    assert len(lst) == 1 and lst[0]["id"] == "my_tpl"
    assert lst[0]["approval_before"] == "create_action"
    assert lst[0]["steps"][0]["skill"] == "create_work_object"

    got = ts.get_template(sql, "compliance", "my_tpl")
    assert got and got["name"] == "My Template"

    ts.delete_template(sql, "compliance", "my_tpl")
    assert ts.list_templates(sql, "compliance") == []


def test_domain_isolation():
    sql = FakeSQL()
    ts.save_template(sql, "compliance", "t", "T", STEPS)
    ts.save_template(sql, "supply_chain", "t", "T2", STEPS)
    assert len(ts.list_templates(sql, "compliance")) == 1
    assert ts.list_templates(sql, "supply_chain")[0]["name"] == "T2"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as e:
            import traceback; traceback.print_exc()
            failed += 1; print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
