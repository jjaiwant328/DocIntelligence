# Databricks notebook source
# MAGIC %md
# MAGIC # DocIntelligence — Generate PDF Documents
# MAGIC
# MAGIC Reads the 13 synthetic `.txt` documents already in the UC Volume and converts
# MAGIC each to a PDF using `reportlab`.  PDFs are written to the same volume path so
# MAGIC that the `unstructured_workflow` pipeline (`ai_parse_document`) can process them.
# MAGIC
# MAGIC `/Volumes/jai_docintel/raw/documents/<doc>.txt  →  <doc>.pdf`

# COMMAND ----------

# MAGIC %pip install reportlab
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER

CATALOG     = "jai_docintel"
SCHEMA_RAW  = "raw"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA_RAW}/documents"

# COMMAND ----------

def txt_to_pdf(txt_path: str, pdf_path: str) -> int:
    """Convert a plain-text supply chain document to a formatted PDF.

    Returns the number of pages written.
    """
    with open(txt_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=11,
        spaceAfter=4,
        spaceBefore=0,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    heading_style = ParagraphStyle(
        "DocHeading",
        parent=styles["Normal"],
        fontSize=9,
        spaceAfter=2,
        spaceBefore=6,
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        spaceAfter=2,
        fontName="Courier",
    )

    def safe(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = []
    lines = text.split("\n")
    title_done = False

    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            story.append(Spacer(1, 3))
            continue

        safe_line = safe(stripped)

        if not title_done:
            story.append(Paragraph(safe_line, title_style))
            story.append(HRFlowable(width="100%", thickness=0.75, spaceAfter=6))
            title_done = True
        elif stripped.isupper() and len(stripped) > 4 and not stripped.startswith(" "):
            story.append(Paragraph(safe_line, heading_style))
        else:
            story.append(Paragraph(safe_line, body_style))

    doc.build(story)
    return getattr(doc, "page", 1)

# COMMAND ----------

txt_files = sorted(f for f in os.listdir(VOLUME_PATH) if f.endswith(".txt"))

if not txt_files:
    raise RuntimeError(f"No .txt files found in {VOLUME_PATH}. Run 01_synthetic_corpus.py first.")

print(f"Found {len(txt_files)} .txt files to convert\n")
results = []

for fname in txt_files:
    txt_path = f"{VOLUME_PATH}/{fname}"
    pdf_name = fname.replace(".txt", ".pdf")
    pdf_path = f"{VOLUME_PATH}/{pdf_name}"
    txt_to_pdf(txt_path, pdf_path)
    size = os.path.getsize(pdf_path)
    results.append((pdf_name, size))
    print(f"  ✓  {pdf_name}  ({size:,.0f} bytes)")

print(f"\n✓ Generated {len(results)} PDFs in {VOLUME_PATH}")
print("\nPDF manifest:")
for name, sz in results:
    print(f"  {name}  ({sz:,} bytes)")
