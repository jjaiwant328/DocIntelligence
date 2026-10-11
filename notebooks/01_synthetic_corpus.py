# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Synthetic Document Corpus (parameterized)
# MAGIC
# MAGIC Single generator for every domain. Document content lives in
# MAGIC `domains/<domain>/sample_data.py` (`DOCS` + `VOLUME_PATH`); this notebook
# MAGIC is only the write engine. Set the `domain_id` widget (default `supply_chain`).

# COMMAND ----------

import os

try:
    dbutils.widgets.text("domain_id", "supply_chain")  # noqa: F821
    DOMAIN_ID = dbutils.widgets.get("domain_id")  # noqa: F821
except NameError:  # plain-script run
    DOMAIN_ID = os.environ.get("DOMAIN_ID", "supply_chain")

# COMMAND ----------

import importlib
import os
import sys

# Make the repo root importable whether this runs as a bundle notebook
# (cwd = notebooks/) or a plain script from the repo root.
_here = os.getcwd()
for cand in (_here, os.path.join(_here, "..")):
    if os.path.isdir(os.path.join(cand, "domains")):
        sys.path.insert(0, os.path.abspath(cand))
        break

sd = importlib.import_module(f"domains.{DOMAIN_ID}.sample_data")
VOLUME_PATH = os.environ.get("DOCINTEL_CORPUS_OUT", sd.VOLUME_PATH)
DOCS = sd.DOCS
print(f"Domain: {DOMAIN_ID} — {len(DOCS)} documents → {VOLUME_PATH}")

# COMMAND ----------

os.makedirs(VOLUME_PATH, exist_ok=True)

for filename, content in DOCS:
    path = os.path.join(VOLUME_PATH, filename)
    with open(path, "w") as f:
        f.write(content.strip())
    print(f"Written: {filename}")

# COMMAND ----------

print(f"\n✓ {len(DOCS)} documents written to {VOLUME_PATH}")
for f in sorted(os.listdir(VOLUME_PATH)):
    size = os.path.getsize(os.path.join(VOLUME_PATH, f))
    print(f"  {f} ({size} bytes)")
