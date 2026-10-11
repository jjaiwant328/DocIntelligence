"""Offline E2E for the consolidated synthetic corpus generator.

Runs notebooks/01_synthetic_corpus.py as a plain script (widget fallback) per
domain into a temp dir and asserts the emitted files match the domain's
sample_data module exactly — land step of land→parse→extract→search→evidence.
"""
import importlib
import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GENERATOR = os.path.join(REPO_ROOT, "notebooks", "01_synthetic_corpus.py")

DOMAINS = ["supply_chain", "compliance", "compliance_due_diligence"]


def _run_generator(domain: str, out_dir: str):
    env = dict(os.environ, DOMAIN_ID=domain, DOCINTEL_CORPUS_OUT=out_dir)
    r = subprocess.run([sys.executable, GENERATOR], env=env, capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode == 0, f"{domain}: {r.stderr[-500:]}"


def test_all_domains_generate_verbatim(tmp_path):
    for domain in DOMAINS:
        out = tmp_path / domain
        _run_generator(domain, str(out))
        sd = importlib.import_module(f"domains.{domain}.sample_data")
        assert len(os.listdir(out)) == len(sd.DOCS), domain
        for filename, content in sd.DOCS:
            emitted = (out / filename).read_text()
            assert emitted == content.strip(), f"{domain}/{filename} diverged"


def test_unknown_domain_fails_loudly(tmp_path):
    env = dict(os.environ, DOMAIN_ID="does_not_exist", DOCINTEL_CORPUS_OUT=str(tmp_path))
    r = subprocess.run([sys.executable, GENERATOR], env=env, capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode != 0
    assert "does_not_exist" in (r.stderr + r.stdout)
