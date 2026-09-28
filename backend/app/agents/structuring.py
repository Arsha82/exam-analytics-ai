"""
PYQ Analyzer — Structuring Agent.

Converts raw OCR text into canonical Question records using:
- gemma4:12b for structured JSON parsing
- Heuristic mark and section segmentation
- Mark balance verification against paper target
- Vector embedding of extracted questions
"""

import json
import logging
import re
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.config import settings
from app.models.paper import Paper, Question
from app.services.ollama import ollama_service
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)

STRUCTURING_SYSTEM_PROMPT = """You are an expert exam paper structure analyzer.
Given the raw OCR text of an examination paper, segment and extract every individual question into a structured JSON array.
Follow these rules strictly:
1. Extract question_no (e.g. "1(a)", "1(b)", "2", "3").
2. Extract the complete, clean text of the question.
3. Extract marks as a number (e.g. 2, 5, 10). If not explicitly stated, estimate reasonably based on context (e.g. 5 or 10).
4. has_diagram: true if the question refers to a diagram, figure, circuit, or graph; otherwise false.
5. or_choice_group: if question is part of an 'OR' choice (e.g. Q2 OR Q3), group label like "Q2_OR_Q3", otherwise null.

Respond ONLY with a JSON object in this format:
{
  "questions": [
    {
      "question_no": "1(a)",
      "text": "State and prove Green's theorem in a plane.",
      "marks": 5.0,
      "has_diagram": false,
      "or_choice_group": null
    }
  ]
}
"""


class StructuringAgent(BaseAgent):
    """Agent that parses raw OCR text into structured Question DB records."""

    name: str = "StructuringAgent"

    async def run(self, paper_id: str, raw_text: str | None = None, **kwargs) -> dict[str, Any]:
        await self.emit_progress("structuring", 10, f"Starting structuring for paper {paper_id}")

        # 1. Fetch paper record
        paper_res = await self.db.execute(select(Paper).where(Paper.paper_id == paper_id))
        paper = paper_res.scalar_one_or_none()
        if not paper:
            return {"status": "failed", "error": f"Paper {paper_id} not found"}

        if not raw_text:
            # If not passed directly, look for existing text or re-read
            return {"status": "failed", "error": "No OCR raw text provided for structuring"}

        await self.emit_progress("structuring", 30, f"Sending raw text to gemma4:12b for question segmentation")

        prompt = f"""Subject: {paper.subject}
Year: {paper.year}
Total Marks Expected: {paper.total_marks}

Exam Paper Raw Text:
{raw_text[:12000]}
"""

        try:
            parsed = await ollama_service.generate_json(
                prompt=prompt,
                system=STRUCTURING_SYSTEM_PROMPT,
                model=settings.ollama_structuring_model,
                temperature=0.1,
            )

            raw_questions = []
            if isinstance(parsed, dict) and "questions" in parsed:
                raw_questions = parsed["questions"]
            elif isinstance(parsed, list):
                raw_questions = parsed
            else:
                self.logger.warning(f"Unexpected response structure: {type(parsed)}")

            await self.emit_progress("structuring", 60, f"Extracted {len(raw_questions)} questions, validating marks")

            # Fallback regex parser if LLM failed to return questions
            if not raw_questions:
                self.logger.info("Using regex fallback parser for question segmentation")
                pattern = r"(?:^|\n)(?:Q\.?\s*(\d+[a-z]?)|(\d+)\.|\((\w+)\))\s*(.*?)(?=(?:\nQ\.?\s*\d+|\n\d+\.|\n\([a-z]\))|\Z)"
                matches = re.findall(pattern, raw_text, re.DOTALL | re.IGNORECASE)
                for idx, m in enumerate(matches):
                    q_num = m[0] or m[1] or m[2] or str(idx + 1)
                    q_text = m[3].strip()
                    if len(q_text) > 10:
                        raw_questions.append({
                            "question_no": str(q_num),
                            "text": q_text[:500],
                            "marks": 10.0,
                            "has_diagram": "diagram" in q_text.lower() or "figure" in q_text.lower(),
                            "or_choice_group": None,
                        })

            # Delete existing questions for this paper if re-running
            existing_q = await self.db.execute(select(Question).where(Question.paper_id == paper_id))
            for eq in existing_q.scalars().all():
                await self.db.delete(eq)

            total_parsed_marks = 0.0
            created_questions: list[Question] = []
            q_dicts_for_vector: list[dict[str, Any]] = []

            for idx, q_data in enumerate(raw_questions):
                q_no = str(q_data.get("question_no", f"{idx + 1}"))
                text = str(q_data.get("text", "")).strip()
                marks = float(q_data.get("marks", 5.0))
                has_diag = bool(q_data.get("has_diagram", False))
                or_group = q_data.get("or_choice_group")

                total_parsed_marks += marks
                question_id = f"{paper_id}_q{idx + 1}"

                q_obj = Question(
                    question_id=question_id,
                    paper_id=paper_id,
                    year=paper.year,
                    question_no=q_no,
                    text=text,
                    marks=marks,
                    has_diagram=has_diag,
                    or_choice_group=or_group,
                    needs_review=False,
                )
                self.db.add(q_obj)
                created_questions.append(q_obj)
                q_dicts_for_vector.append({
                    "question_id": question_id,
                    "paper_id": paper_id,
                    "year": paper.year,
                    "marks": marks,
                    "text": text,
                    "unit_guess": None,
                })

            # Check marks balance
            marks_diff = abs(total_parsed_marks - paper.total_marks)
            if marks_diff > (paper.total_marks * 0.15) and len(created_questions) > 0:
                paper.needs_review = True
                for q in created_questions:
                    q.needs_review = True
                    q.review_reason = f"Marks total mismatch: paper expects {paper.total_marks}m, parsed questions sum to {total_parsed_marks}m."

            await self.db.commit()

            await self.emit_progress("structuring", 85, f"Indexing {len(created_questions)} questions into vector store")

            # Index questions into vector store
            if q_dicts_for_vector:
                try:
                    await vector_store.upsert_questions(q_dicts_for_vector)
                except Exception as embed_err:
                    self.logger.warning(f"Vector store question embedding failed: {embed_err}")

            await self.emit_progress("structuring", 100, f"Successfully structured {len(created_questions)} questions")

            return {
                "status": "complete",
                "paper_id": paper_id,
                "questions_count": len(created_questions),
                "total_marks_parsed": total_parsed_marks,
                "needs_review": paper.needs_review,
            }

        except Exception as e:
            self.logger.error(f"Structuring failed for {paper_id}: {e}", exc_info=True)
            paper.needs_review = True
            await self.db.commit()
            await self.emit_progress("structuring", 100, f"Structuring error: {str(e)}")
            return {"status": "failed", "error": str(e)}
