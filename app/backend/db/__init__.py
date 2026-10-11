"""Lakebase (managed Postgres) data-access layer for the app's operational state.

Hot, low-latency operational tables (projects, document tags, workflow runs,
templates, skill executions, actions) live here instead of the Lakehouse SQL
warehouse, so UI reads return in milliseconds instead of 15-50s.

`lakebase` owns the connection/token lifecycle; `repositories` hold typed CRUD
per table. Analytical data (parsed documents, entities, vectors, gold tables)
stays in the Lakehouse and is still reached via `docintel_routes.run_sql`.
"""
