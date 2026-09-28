"""
PYQ Analyzer — Document Boundary Agent.

Uses Gemma 4 intelligence to inspect multi-page documents and determine whether
a PDF represents:
1. A single continuous exam paper spanning multiple pages, or
2. A merged collection of multiple past year exam papers scanned/concatenated back-to-back.

Detects paper boundaries by analyzing exam headers, university titles, semester dates,
month sessions (e.g. May/June vs Nov/Dec), question numbering restarts, and total marks.
"""

import json
import logging
import re
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.config import settings
from app.models.paper import Paper
from app.services.ollama import ollama_service

logger = logging.getLogger(__name__)

BOUNDARY_DETECTION_SYSTEM = """You are an expert academic document boundary and exam structure analyst.
Your task is to analyze multi-page examination documents and determine whether the document is:
A) A SINGLE continuous examination paper spanning multiple pages, OR
B) A MERGED COLLECTION of multiple past year question papers scanned or concatenated back-to-back (e.g. May 2021, Nov 2021, and May 2022 merged into one PDF).

Key indicators of a new exam paper boundary:
1. Header restart: New university/college title, semester/course code, or exam title (e.g., "MAY/JUNE 2021", "NOVEMBER 2022", "SUPPLEMENTARY EXAM", "END SEMESTER").
2. Question numbering reset: Questions suddenly jump back to Question 1, Q1, or Section A after high numbers on preceding pages.
3. New administrative block: New "Time Allowed: 3 Hours", "Maximum Marks: 100" or "Max Marks: 70", instructions block ("Answer any 5 questions").
4. Completion markers: "END OF QUESTION PAPER", "***", or blank layout before a fresh title.

You must respond ONLY with a JSON object in this exact schema:
{
  "is_merged_collection": true or false,
  "confidence": 0.95,
  "reasoning": "Detailed explanation of boundary points and header markers found",
  "detected_papers": [
    {
      "start_page": 1,
      "end_page": 3,
      "subject": "Mathematics",
      "year": 2021,
      "session_month": "May",
      "total_marks": 100,
      "confidence": 0.95,
      "boundary_evidence": "Page 1 has 'MAY 2021 EXAMINATIONS' with Q1-Q5 ending on Page 3"
    }
  ]
}
"""


class DocumentBoundaryAgent(BaseAgent):
    """
    Agent that analyzes multi-page OCR output to detect merged multi-paper boundaries
    using Gemma 4 intelligence.
    """

    name: str = "DocumentBoundaryAgent"

    def _build_page_summaries(self, pages: list[str]) -> str:
        """Build a condensed structural outline of each page for LLM reasoning."""
        summaries = []
        for idx, page_text in enumerate(pages, 1):
            lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
            header_snippet = "\n".join(lines[:8])[:450]
            footer_snippet = "\n".join(lines[-4:])[:200] if len(lines) > 8 else ""

            # Find question markers on this page
            q_numbers = re.findall(r"(?:^|\n)(?:Q\.?\s*(\d+[a-z]?)|(\d+)\.|\bQuestion\s*(\d+))", page_text, re.IGNORECASE)
            q_found = [q[0] or q[1] or q[2] for q in q_numbers[:6]]

            summary = (
                f"--- [PAGE {idx}] ---\n"
                f"HEADER PREVIEW:\n{header_snippet}\n"
                f"QUESTIONS FOUND: {', '.join(q_found) if q_found else 'None detected'}\n"
            )
            if footer_snippet:
                summary += f"FOOTER PREVIEW:\n{footer_snippet}\n"
            summaries.append(summary)

        return "\n\n".join(summaries)

    def _heuristic_boundary_check(
        self, pages: list[str], default_subject: str, default_year: int, default_marks: int
    ) -> dict[str, Any]:
        """Deterministic heuristic fallback when LLM is unavailable."""
        boundaries = [1]
        header_pattern = re.compile(
            r"(?:university|examination|b\.?\s*tech|b\.?\s*e|maximum\s*marks|max\s*marks|time\s*allowed|end\s*semester)",
            re.IGNORECASE,
        )
        q1_pattern = re.compile(r"(?:^|\n)(?:Q\.?\s*1[a-z]?|1\.\s+|Question\s*1\b)", re.IGNORECASE)

        for i in range(1, len(pages)):
            page_text = pages[i]
            first_lines = "\n".join(page_text.splitlines()[:10])
            has_header = bool(header_pattern.search(first_lines))
            has_q1 = bool(q1_pattern.search(first_lines))

            if has_header and has_q1:
                boundaries.append(i + 1)

        is_merged = len(boundaries) > 1
        detected = []
        for idx, start_p in enumerate(boundaries):
            end_p = boundaries[idx + 1] - 1 if idx + 1 < len(boundaries) else len(pages)
            detected.append({
                "start_page": start_p,
                "end_page": end_p,
                "subject": default_subject,
                "year": default_year,
                "session_month": None,
                "total_marks": default_marks,
                "confidence": 0.70 if is_merged else 1.0,
                "boundary_evidence": f"Heuristic boundary detected at page {start_p}",
            })

        return {
            "is_merged_collection": is_merged,
            "confidence": 0.70 if is_merged else 1.0,
            "reasoning": f"Heuristic analysis detected {len(detected)} paper boundary(ies).",
            "detected_papers": detected,
        }

    async def run(
        self,
        paper_id: str,
        pages: list[str],
        default_subject: str = "General",
        default_year: int = 2024,
        default_marks: int = 100,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Analyze document pages for single vs. merged exam paper structure.
        """
        num_pages = len(pages)
        if num_pages <= 1:
            return {
                "is_merged_collection": False,
                "confidence": 1.0,
                "reasoning": "Single page document; cannot be a merged multi-paper collection.",
                "detected_papers": [
                    {
                        "start_page": 1,
                        "end_page": max(num_pages, 1),
                        "subject": default_subject,
                        "year": default_year,
                        "session_month": None,
                        "total_marks": default_marks,
                        "confidence": 1.0,
                        "boundary_evidence": "Single page document",
                    }
                ],
            }

        await self.emit_progress(
            "boundary_analysis",
            20,
            f"Analyzing {num_pages} pages with Gemma 4 for multi-paper boundary detection",
        )

        page_outline = self._build_page_summaries(pages)
        prompt = (
            f"Document has {num_pages} total pages.\n"
            f"Default Metadata: Subject={default_subject}, Year={default_year}, Marks={default_marks}\n\n"
            f"Page structural summaries:\n"
            f"{page_outline}\n\n"
            f"Analyze if this document contains multiple merged exam papers or is one single continuous exam paper.\n"
            f"Respond ONLY with a valid JSON object matching the requested schema. No markdown fences or text outside JSON."
        )

        try:
            result = await ollama_service.generate_json(
                prompt=prompt,
                system=BOUNDARY_DETECTION_SYSTEM,
                model=settings.ollama_structuring_model,
                temperature=0.1,
            )
            self.logger.info(f"Gemma 4 boundary analysis output: {result}")

            if isinstance(result, dict) and "detected_papers" in result:
                is_merged = bool(result.get("is_merged_collection", False))
                raw_detected = result.get("detected_papers", [])

                # Validate and sanitize detected papers
                sanitized_papers = []
                last_end = 0

                for dp in raw_detected:
                    start_p = int(dp.get("start_page", last_end + 1))
                    end_p = int(dp.get("end_page", num_pages))
                    start_p = max(1, min(start_p, num_pages))
                    end_p = max(start_p, min(end_p, num_pages))

                    # Parse year safely
                    year_val = dp.get("year")
                    try:
                        year_val = int(year_val) if year_val and 1990 <= int(year_val) <= 2035 else default_year
                    except (ValueError, TypeError):
                        year_val = default_year

                    # Parse marks safely
                    marks_val = dp.get("total_marks")
                    try:
                        marks_val = int(marks_val) if marks_val and 1 <= int(marks_val) <= 500 else default_marks
                    except (ValueError, TypeError):
                        marks_val = default_marks

                    sanitized_papers.append({
                        "start_page": start_p,
                        "end_page": end_p,
                        "subject": dp.get("subject") or default_subject,
                        "year": year_val,
                        "session_month": dp.get("session_month"),
                        "total_marks": marks_val,
                        "confidence": float(dp.get("confidence", 0.85)),
                        "boundary_evidence": str(dp.get("boundary_evidence", "")),
                    })
                    last_end = end_p

                # Ensure papers cover all pages without gaps
                if sanitized_papers:
                    sanitized_papers[0]["start_page"] = 1
                    sanitized_papers[-1]["end_page"] = num_pages

                if len(sanitized_papers) > 1 and is_merged:
                    await self.emit_progress(
                        "boundary_analysis",
                        90,
                        f"Gemma 4 detected {len(sanitized_papers)} distinct papers in merged collection",
                    )
                    return {
                        "is_merged_collection": True,
                        "confidence": float(result.get("confidence", 0.90)),
                        "reasoning": result.get("reasoning", "Multiple exam papers detected across pages."),
                        "detected_papers": sanitized_papers,
                    }

            self.logger.info("Gemma 4 determined document is a single continuous exam paper.")
            return {
                "is_merged_collection": False,
                "confidence": float(result.get("confidence", 0.95)) if isinstance(result, dict) else 0.9,
                "reasoning": result.get("reasoning", "Single continuous exam paper.") if isinstance(result, dict) else "Single continuous exam paper.",
                "detected_papers": [
                    {
                        "start_page": 1,
                        "end_page": num_pages,
                        "subject": default_subject,
                        "year": default_year,
                        "session_month": None,
                        "total_marks": default_marks,
                        "confidence": 1.0,
                        "boundary_evidence": "Single continuous exam paper spanning pages",
                    }
                ],
            }

        except Exception as e:
            self.logger.warning(f"Gemma 4 boundary analysis failed ({e}), falling back to heuristic detector")
            return self._heuristic_boundary_check(pages, default_subject, default_year, default_marks)
