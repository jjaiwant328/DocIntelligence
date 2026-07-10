#!/usr/bin/env python3
"""
convert_compliance_pdfs_local.py

Reads the .txt files that were written to /Volumes/jai_docintel/compliance/documents/
via the setup script, converts each to a PDF locally using reportlab, and uploads the
resulting PDFs back to the same volume using the Databricks Files API.

Run with: /usr/bin/python3 scripts/convert_compliance_pdfs_local.py
"""

import io
import sys
import tempfile
from pathlib import Path

# ── Imports ──────────────────────────────────────────────────────────────────
try:
    from databricks.sdk import WorkspaceClient
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.enums import TA_CENTER
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip3 install --user databricks-sdk reportlab")
    sys.exit(1)

PROFILE     = "jai-az-ws"
CATALOG     = "jai_docintel"
SCHEMA      = "compliance"
VOLUME_NAME = "documents"
VOLUME_BASE = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME_NAME}"


def txt_to_pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=inch, rightMargin=inch,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=9, leading=12, spaceAfter=4, fontName="Helvetica",
    )
    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"],
        fontSize=11, spaceAfter=6, fontName="Helvetica-Bold", alignment=TA_CENTER,
    )
    story = []
    for i, line in enumerate(text.split("\n")):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if i == 0 or (line.isupper() and 8 < len(line) < 90):
            story.append(Paragraph(line, title_style))
        else:
            story.append(Paragraph(line, body_style))
    doc.build(story)
    return buf.getvalue()


def main():
    print("=" * 60)
    print("DocIntelligence — Local PDF Conversion for Compliance Volume")
    print("=" * 60)

    w = WorkspaceClient(profile=PROFILE)

    # List .txt files in the volume
    print(f"\nListing files in {VOLUME_BASE}")
    txt_files = []
    for fi in w.files.list_directory_contents(VOLUME_BASE):
        if fi.name and fi.name.endswith(".txt"):
            txt_files.append(fi.name)

    print(f"Found {len(txt_files)} .txt files")

    # Check which PDFs already exist
    existing_pdfs = set()
    for fi in w.files.list_directory_contents(VOLUME_BASE):
        if fi.name and fi.name.endswith(".pdf"):
            existing_pdfs.add(fi.name)

    print(f"Existing PDFs: {len(existing_pdfs)}")

    converted = 0
    skipped = 0
    failed = 0

    for txt_name in sorted(txt_files):
        pdf_name = txt_name.replace(".txt", ".pdf")
        if pdf_name in existing_pdfs:
            print(f"  Skip (exists): {pdf_name}")
            skipped += 1
            continue

        print(f"  Converting: {txt_name} → {pdf_name}")
        try:
            # Download the txt file
            dl = w.files.download(f"{VOLUME_BASE}/{txt_name}")
            text = dl.contents.read().decode("utf-8")

            # Convert to PDF in memory
            pdf_bytes = txt_to_pdf_bytes(text)

            # Upload PDF to volume
            w.files.upload(
                f"{VOLUME_BASE}/{pdf_name}",
                io.BytesIO(pdf_bytes),
                overwrite=True,
            )
            converted += 1
        except Exception as e:
            print(f"  FAILED: {txt_name} — {e}")
            failed += 1

    print(f"\nDone: {converted} converted, {skipped} skipped, {failed} failed")
    print(f"Total PDFs in volume: {converted + len(existing_pdfs)}")


if __name__ == "__main__":
    main()
