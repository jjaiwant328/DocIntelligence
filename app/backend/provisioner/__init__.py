"""Blueprint-driven use-case provisioner.

A Blueprint is a declarative spec for a whole use case — document types +
extraction schemas, entity types, enabled skills, a starter workflow, and a
reconciliation spec. `provision()` turns one into a live use case: registers its
domain config, creates its Lakehouse schema/volume + pipeline job, seeds its
starter workflow, and creates its project — no scripts, no redeploy. This is the
citizen-developer "build a use case on the fly" engine (folds the old manual
scripts/create_domain_job.py in).
"""
