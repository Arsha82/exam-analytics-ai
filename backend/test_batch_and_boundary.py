"""
Test script for ZIP batch unpacking and Gemma 4 merged PDF boundary detection.
"""

import asyncio
import io
from pathlib import Path
import pypdfium2 as pdfium
import sys
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.database import async_session_factory
import functools
print = functools.partial(print, flush=True)
from app.models.paper import Paper, Question
from app.services.archive_extractor import archive_extractor
from app.agents.boundary_detection import DocumentBoundaryAgent
from app.services.pipeline_runner import run_paper_pipeline
from sqlalchemy import select


def create_sample_pdf(title: str, year: int, session: str, q_list: list[str]) -> bytes:
    """Create a minimal 1-page PDF for testing."""
    # We can use pdfium to create or write minimal PDF bytes
    # Minimal standard PDF bytes
    content = f"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length {len(title) + 120} >> stream
BT
/F1 14 Tf
50 720 Td ({title} - {session} {year}) Tj
/F1 10 Tf
0 -30 Td (Time Allowed: 3 Hours               Maximum Marks: 100) Tj
0 -40 Td ({q_list[0]}) Tj
0 -40 Td ({q_list[1]}) Tj
ET
endstream
endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000244 00000 n 
0000000450 00000 n 
trailer << /Size 6 /Root 1 0 R >>
startxref
530
%%EOF"""
    return content.encode("latin1")


async def test_boundary_detection_logic():
    print("\n--- 1. Testing DocumentBoundaryAgent with Gemma 4 ---")
    pages = [
        """--- Page 1 ---
UNIVERSITY EXAMINATIONS - MAY/JUNE 2021
BRANCH: COMPUTER SCIENCE & ENGINEERING
SUBJECT: DISCRETE MATHEMATICS
Time Allowed: 3 Hours               Maximum Marks: 100
Answer any FIVE questions.

Q1. (a) Prove that the square of any odd integer is of the form 8k + 1. [5 Marks]
    (b) Show that if 7 points are chosen in a 3x3 square, two must be within sqrt(2) distance. [5 Marks]
Q2. (a) Define a bipartite graph and state the necessary and sufficient condition for a graph to be bipartite. [10 Marks]
""",
        """--- Page 2 ---
Q3. (a) Find the general solution of the recurrence relation: a_n - 5a_{n-1} + 6a_{n-2} = 0. [10 Marks]
Q4. (a) State and prove Euler's formula for connected planar graphs. [10 Marks]
Q5. (a) Determine whether the relation R is an equivalence relation. [10 Marks]
*** END OF QUESTION PAPER ***
""",
        """--- Page 3 ---
UNIVERSITY EXAMINATIONS - NOVEMBER/DECEMBER 2021
BRANCH: COMPUTER SCIENCE & ENGINEERING
SUBJECT: DISCRETE MATHEMATICS
Time Allowed: 3 Hours               Maximum Marks: 100
Answer all questions.

Q1. (a) State mathematical induction and prove that 1 + 2 + ... + n = n(n+1)/2. [10 Marks]
Q2. (a) Explain Pigeonhole Principle with an example. [10 Marks]
""",
        """--- Page 4 ---
Q3. (a) Find the generating function for the sequence {0, 1, 4, 9, 16, ...}. [10 Marks]
Q4. (a) Prove that K_5 is non-planar using Kuratowski's theorem. [10 Marks]
Q5. (a) Construct a truth table for (P -> Q) ^ (Q -> R). [10 Marks]
*** BEST OF LUCK ***
""",
    ]

    async with async_session_factory() as db:
        agent = DocumentBoundaryAgent(db=db)
        res = await agent.run(
            paper_id="test_merged_paper",
            pages=pages,
            default_subject="Discrete Mathematics",
            default_year=2021,
            default_marks=100,
        )

        print("Boundary Detection Result:")
        print("Is Merged:", res.get("is_merged_collection"))
        print("Confidence:", res.get("confidence"))
        print("Reasoning:", res.get("reasoning"))
        print("Detected Papers:")
        for idx, p in enumerate(res.get("detected_papers", []), 1):
            print(f"  Paper {idx}: Pages {p['start_page']}-{p['end_page']} | Year: {p['year']} | Session: {p.get('session_month')} | Subj: {p['subject']}")


async def test_zip_extraction():
    print("\n--- 2. Testing ZIP Archive Extraction & Metadata Inference ---")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        p1 = create_sample_pdf("PHYSICS I", 2022, "May", ["Q1. State Gauss Law.", "Q2. Define electric flux."])
        p2 = create_sample_pdf("CHEMISTRY", 2023, "November", ["Q1. Explain Nernst equation.", "Q2. Define corrosion."])
        zf.writestr("Physics/2022_May_Exam.pdf", p1)
        zf.writestr("Chemistry/2023_Nov_Endsem.pdf", p2)

    zip_bytes = buf.getvalue()
    zip_path = Path("test_upload_papers.zip")
    zip_path.write_bytes(zip_bytes)

    docs = archive_extractor.unpack_archive(zip_path, default_subject="General", default_year=2024)
    print(f"Extracted {len(docs)} document(s) from ZIP:")
    for d in docs:
        print(f"  - Subject: '{d['subject']}' | Year: {d['year']} | Session: {d['session_month']} | File: {d['filename']}")

    # Clean up test zip
    if zip_path.exists():
        zip_path.unlink()
    # Clean up extracted files
    for d in docs:
        fp = Path(d["file_path"])
        if fp.exists():
            fp.unlink()


async def main():
    await test_zip_extraction()
    await test_boundary_detection_logic()


if __name__ == "__main__":
    asyncio.run(main())
