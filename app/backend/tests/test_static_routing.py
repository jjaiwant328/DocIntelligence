"""Static page routing: every exported Next.js page dir must be reachable, not
just a hardcoded subset. Regression for /playground //builder //workflow serving
the landing page. Uses a temp target_dir with fake exported pages."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve(target_dir, full_path):
    """Test the pure logic: given target_dir + path, which file is served?"""
    from static_routing import resolve_page_file
    return resolve_page_file(target_dir, full_path)


def _make_export(root, pages):
    for p in pages:
        os.makedirs(os.path.join(root, p), exist_ok=True)
        with open(os.path.join(root, p, "index.html"), "w") as f:
            f.write(f"<html>{p}</html>")
    with open(os.path.join(root, "index.html"), "w") as f:
        f.write("<html>LANDING</html>")


def test_new_pages_resolve_to_their_own_html():
    with tempfile.TemporaryDirectory() as d:
        _make_export(d, ["supply-chain", "playground", "builder", "workflow"])
        for page in ["playground", "builder", "workflow", "supply-chain"]:
            got = _resolve(d, page)
            assert got == os.path.join(d, page, "index.html"), f"{page} -> {got}"


def test_unknown_route_falls_back_to_landing():
    with tempfile.TemporaryDirectory() as d:
        _make_export(d, ["playground"])
        got = _resolve(d, "totally-unknown-route")
        assert got == os.path.join(d, "index.html")


def test_root_serves_landing():
    with tempfile.TemporaryDirectory() as d:
        _make_export(d, ["playground"])
        assert _resolve(d, "") == os.path.join(d, "index.html")


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
