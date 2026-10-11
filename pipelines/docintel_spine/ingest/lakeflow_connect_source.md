# Ingestion source — Lakeflow Connect (T6)

The `docintel_spine` pipeline reads documents **in place** from whatever
`source_volume_path` points at (a config param — no code change to switch source).
This decouples *how documents land* from *how they're processed*.

## Source options

| Source | How docs land | Copy? | `source_volume_path` |
|---|---|---|---|
| **Object storage** (S3/ADLS/GCS) | UC **External Location / external Volume** over the bucket | **No — read in place** | the external volume path |
| **SaaS: Google Drive / SharePoint** | **Lakeflow Connect managed connector** ingests incrementally into a UC managed Volume/table | One governed hop (SaaS has no zero-copy) | the Connect landing volume |
| **Demo / offline** | synthetic corpus already in a Volume | n/a | e.g. `/Volumes/jai_docintel/raw/documents/` (current) |

## Setting up the SaaS connector (requires workspace admin + source OAuth)

> **Requires the document owner to authorize OAuth** to the Google Drive / SharePoint
> account. Confirm the managed connector is enabled in this Azure workspace first
> (GA/Preview varies by cloud).

1. **Create a UC connection** to the source:
   - Catalog Explorer → External Data → Connections → *Create connection* →
     type **Google Drive** (or **SharePoint**) → complete the OAuth consent.
2. **Create the ingestion pipeline** (Lakeflow Connect): choose the connection, select
   the folder(s)/site(s), and set the destination to a UC Volume in this catalog, e.g.
   `/Volumes/jai_docintel/template/landing/`. Enable **incremental** ingestion.
3. **Point the spine at the landing volume** — set in the pipeline config
   (`resources/docintel_spine.pipeline.yml`):
   ```yaml
   configuration:
     source_volume_path: /Volumes/jai_docintel/template/landing/
   ```
   No transformation code changes; Auto Loader picks up new files incrementally.

## Why this replaces the old path

The legacy app fetched bytes via bespoke Google OAuth (`app/mcp-server/connectors/gdrive.py`,
`oauth.py`), landed them in a managed Volume, then **cleaned and re-uploaded every run**.
Lakeflow Connect is a single, governed, permission-aware, incremental hop — the bespoke
OAuth/fetch/clean code is retired once the connector lands data end to end.

## Offline fallback

The synthetic connector / existing corpus volume remains the demo default, so the spine
runs with no external credentials. Switching sources is purely a config change.
