"""Synthetic Google Drive — seeded, realistic documents so the whole flow
(source → Volume → pipeline → reconcile skills) works with no OAuth. The figures
are intentionally inconsistent so reconcile_documents finds real discrepancies
(overbilling, late delivery, SLA breach, over-quantity, duplicate invoice)."""
from __future__ import annotations

import base64

from .base import Connector

# folder -> list of (doc_ref, name, doc_type_hint, text)
_DOCS: list[dict] = [
    # ── Supplier Performance ────────────────────────────────────────────────
    {"doc_ref": "syn/supplier/acme_master_contract.txt", "folder": "Supplier Performance",
     "name": "ACME_Master_Contract.txt", "doc_type_hint": "master_contract",
     "text": (
         "MASTER SUPPLY AGREEMENT\n"
         "Supplier: ACME Components Inc.   Contract No: MC-ACME-2026\n"
         "Effective: 2026-01-01 to 2026-12-31\n"
         "SKU WIDGET-A: agreed unit price $10.00\n"
         "Agreed lead time: 5 days\n"
         "On-time delivery SLA: 95%\n"
         "Late-delivery penalty: 2% of line value per day late\n")},
    {"doc_ref": "syn/supplier/acme_delivery_schedule.txt", "folder": "Supplier Performance",
     "name": "ACME_Delivery_Schedule.txt", "doc_type_hint": "delivery_schedule",
     "text": (
         "DELIVERY SCHEDULE  Supplier: ACME Components Inc.  PO: PO-8801\n"
         "Line 1  SKU WIDGET-A  qty 100  promised 2026-02-01  actual 2026-02-05\n"
         "Line 2  SKU WIDGET-A  qty 100  promised 2026-02-10  actual 2026-02-10\n"
         "Line 3  SKU WIDGET-A  qty 100  promised 2026-02-20  actual 2026-02-27\n")},
    {"doc_ref": "syn/supplier/acme_invoice_INV1001.txt", "folder": "Supplier Performance",
     "name": "ACME_Invoice_INV-1001.txt", "doc_type_hint": "invoice",
     "text": (
         "INVOICE  No: INV-1001   Supplier: ACME Components Inc.   PO: PO-8801\n"
         "Date: 2026-03-01\n"
         "SKU WIDGET-A  qty 300  unit price $11.00  total $3,300.00\n"
         "(Contract unit price is $10.00 — billed $1.00/unit over on 300 units.)\n")},
    # ── AP 3-Way Match ──────────────────────────────────────────────────────
    {"doc_ref": "syn/ap/po_5001.txt", "folder": "AP 3-Way Match",
     "name": "PO-5001.txt", "doc_type_hint": "purchase_order",
     "text": (
         "PURCHASE ORDER  PO No: PO-5001   Vendor: Globex Supply Co.\n"
         "SKU BOLT-M8  qty 500  unit price $2.00  total $1,000.00\n")},
    {"doc_ref": "syn/ap/grn_5001.txt", "folder": "AP 3-Way Match",
     "name": "GRN-5001.txt", "doc_type_hint": "goods_receipt",
     "text": (
         "GOODS RECEIPT NOTE  GRN No: GRN-5001   PO No: PO-5001\n"
         "SKU BOLT-M8  quantity received 450   received 2026-02-15\n")},
    {"doc_ref": "syn/ap/invoice_2001.txt", "folder": "AP 3-Way Match",
     "name": "INV-2001.txt", "doc_type_hint": "invoice",
     "text": (
         "INVOICE  No: INV-2001   Vendor: Globex Supply Co.   PO No: PO-5001\n"
         "Date: 2026-02-20\n"
         "SKU BOLT-M8  qty 500  unit price $2.20  total $1,100.00\n"
         "(PO price $2.00 — overbilled; billed 500 vs 450 received.)\n")},
    {"doc_ref": "syn/ap/invoice_2002.txt", "folder": "AP 3-Way Match",
     "name": "INV-2002.txt", "doc_type_hint": "invoice",
     "text": (
         "INVOICE  No: INV-2002   Vendor: Globex Supply Co.   PO No: PO-5001\n"
         "Date: 2026-02-21\n"
         "SKU BOLT-M8  qty 500  unit price $2.20  total $1,100.00\n"
         "(Duplicate of INV-2001 — same PO, SKU, and amount.)\n")},
]


class SyntheticDriveConnector(Connector):
    id = "gdrive"
    name = "Google Drive"

    def describe(self) -> dict:
        return {"id": self.id, "name": self.name, "mode": "synthetic",
                "connected": True, "note": "Seeded demo data — set Google OAuth secrets for live Drive."}

    def list_documents(self, folder_id: str = "", query: str = "") -> dict:
        q = (query or "").lower()
        items = []
        for d in _DOCS:
            if folder_id and d["folder"] != folder_id:
                continue
            if q and q not in d["name"].lower() and q not in d["doc_type_hint"]:
                continue
            items.append({
                "doc_ref": d["doc_ref"], "name": d["name"], "mime_type": "text/plain",
                "size": len(d["text"]), "modified": "2026-03-01T00:00:00Z",
                "folder": d["folder"], "doc_type_hint": d["doc_type_hint"],
            })
        return {"items": items}

    def fetch_document(self, doc_ref: str) -> dict:
        for d in _DOCS:
            if d["doc_ref"] == doc_ref:
                return {"doc_ref": doc_ref, "name": d["name"], "filename": d["name"],
                        "mime_type": "text/plain",
                        "content_b64": base64.b64encode(d["text"].encode("utf-8")).decode("ascii")}
        raise ValueError(f"unknown doc_ref: {doc_ref}")
