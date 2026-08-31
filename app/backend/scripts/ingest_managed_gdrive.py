#!/usr/bin/env python
"""User-context Google Drive → Lakebase ingest via the managed MCP.

Runs AS the calling user (Databricks profile), so the managed
system.ai.google_drive MCP sees the user's own Drive with no OAuth client and
no elevated credentials. Reads text-readable files, chunks + embeds them, and
writes vectors + reference metadata into Lakebase — NO file is copied into a UC
volume. Reuses the connector-first indexer leaf modules (parse/chunk/embed) and
repos, so the result is identical to the connector-first pipeline.

Usage:
    DATABRICKS_CONFIG_PROFILE=jai-az-ws \
      python scripts/ingest_managed_gdrive.py \
        --folder 12sSEQcg-1TtC9C8ewfpomsTRknChwyGq \
        --domain compliance_due_diligence --project gdrive_docintel
"""
import argparse
import base64
import json
import os

WORKSPACE = "https://adb-4101016551133680.0.azuredatabricks.net"
MANAGED_URL = f"{WORKSPACE}/ai-gateway/mcp-services/system.ai.google_drive?o=4101016551133680"


def _set_lakebase_env(user: str):
    """db/lakebase.py reads these at import time — set BEFORE importing it."""
    os.environ.setdefault("LAKEBASE_ENABLED", "true")
    os.environ.setdefault("LAKEBASE_ENDPOINT", "projects/docintel/branches/production/endpoints/primary")
    os.environ.setdefault("LAKEBASE_HOST", "ep-shy-block-e3xwzxuz.database.westus.azuredatabricks.net")
    os.environ.setdefault("LAKEBASE_DB", "docintel")
    os.environ.setdefault("LAKEBASE_SCHEMA", "app")
    os.environ["LAKEBASE_USER"] = user           # connect as the user, not the SP
    os.environ.setdefault("EMBED_MODEL", "databricks-gte-large-en")
    os.environ.setdefault("EMBED_DIM", "1024")


def _make_call_tool(profile: str):
    from databricks_mcp import DatabricksMCPClient
    from databricks.sdk import WorkspaceClient
    wc = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    mc = DatabricksMCPClient(server_url=MANAGED_URL, workspace_client=wc)

    def call_tool(tool: str, args: dict) -> dict:
        r = mc.call_tool(tool, args)
        joined = "".join(getattr(c, "text", "") for c in (getattr(r, "content", []) or []))
        return json.loads(joined) if joined else {}

    return call_tool, wc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True, help="Drive folder id to ingest")
    ap.add_argument("--domain", default="compliance_due_diligence")
    ap.add_argument("--project", default="gdrive_docintel")
    ap.add_argument("--profile", default=os.getenv("DATABRICKS_CONFIG_PROFILE", "jai-az-ws"))
    ap.add_argument("--source-id", default="gdrive_managed")
    ap.add_argument("--provider", default="gdrive")
    args = ap.parse_args()

    call_tool, wc = _make_call_tool(args.profile)
    user = wc.current_user.me().user_name
    print(f"→ ingesting as {user}  (domain={args.domain}, project={args.project})")

    _set_lakebase_env(user)

    # Import AFTER env is set. None of these import mcp_sources.
    from db import lakebase
    from db.repositories import external_docs_repo as docs_repo
    from db.repositories import chunks_repo
    from indexer import parse as parse_mod
    from indexer import chunk as chunk_mod
    from indexer import embed as embed_mod
    from indexer.managed_gdrive import ManagedDriveSource, is_text_readable

    src = ManagedDriveSource(call_tool, root_folder_id=args.folder)

    with lakebase.connection() as conn:
        # ── Crawl: metadata only, upsert one external_documents row per file ──
        seen: list[dict] = []

        def walk(folder_id: str, depth: int = 0):
            if depth > 8:
                return
            for it in src.list_children(folder_id):
                if it["is_folder"]:
                    walk(it["item_id"], depth + 1)
                    continue
                doc_id = docs_repo.stable_doc_id(args.provider, "", args.source_id, it["item_id"])
                docs_repo.upsert_metadata(conn, {
                    "external_document_id": doc_id,
                    "source_id": args.source_id,
                    "source_item_id": it["item_id"],
                    "domain_id": args.domain,
                    "project_id": args.project,
                    "name": it["name"],
                    "mime_type": it["mime_type"],
                    "size_bytes": it["size"],
                    "web_url": it["web_url"],          # reference back to the Drive doc
                    "etag": it["etag"],
                    "owner": it["owner"],
                    "source_modified_at": it["modified_at"] or None,
                    "status": "pending",
                    "included": True,
                })
                seen.append({**it, "external_document_id": doc_id})

        walk(args.folder)
        print(f"  crawled: {len(seen)} file(s) (metadata only, no content copied)")

        # ── Index: fetch → parse → chunk → embed → store vectors in Lakebase ──
        embed_model = os.environ["EMBED_MODEL"]
        embedded = skipped = failed = 0
        for d in seen:
            doc_id = d["external_document_id"]
            if not is_text_readable(d["mime_type"]):
                skipped += 1
                print(f"  · skip (binary/non-text): {d['name']} [{d['mime_type']}]")
                continue
            try:
                fr = src.fetch_document(d["item_id"])
                text = parse_mod.extract_text(fr["filename"], base64.b64decode(fr["content_b64"]))
                if not text.strip():
                    docs_repo.set_status(conn, doc_id, "failed", "empty text")
                    failed += 1
                    continue
                snippets = chunk_mod.split(text)
                chunks = [{
                    "chunk_id": chunk_mod.chunk_id(doc_id, i),
                    "external_document_id": doc_id,
                    "domain_id": args.domain,
                    "project_id": args.project,
                    "ordinal": i,
                    "location": f"chunk:{i}",
                    "snippet": s,
                    "source_version": d["etag"],
                    "index_version": 1,
                } for i, s in enumerate(snippets)]
                for c, vec in zip(chunks, embed_mod.embed_texts([c["snippet"] for c in chunks])):
                    c["embedding"] = vec
                chunks_repo.replace_chunks(conn, doc_id, chunks)
                docs_repo.mark_indexed(conn, doc_id, index_version=1,
                                       embedding_model=embed_model, etag=d["etag"],
                                       chunk_count=len(chunks))
                embedded += 1
                print(f"  ✓ indexed {d['name']}: {len(chunks)} chunk(s) → Lakebase vectors")
            except Exception as e:
                docs_repo.set_status(conn, doc_id, "failed", str(e)[:200])
                failed += 1
                print(f"  ✗ {d['name']}: {type(e).__name__}: {str(e)[:150]}")

        print(f"\nDONE  embedded={embedded} skipped={skipped} failed={failed}")

        # ── Verify: what's now in Lakebase for this project ──
        rows = docs_repo.list_for_project(conn, args.domain, args.project)
        print(f"\nLakebase external_documents ({len(rows)} rows, references only):")
        for r in rows:
            print(f"  - {r.get('name'):40s} chunks={r.get('chunk_count',0):<3} "
                  f"status={r.get('status')}  → {r.get('web_url','')}")


if __name__ == "__main__":
    main()
