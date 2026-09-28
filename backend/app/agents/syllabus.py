"""
PYQ Analyzer — Syllabus Correlation Agent.

Maps extracted exam questions to syllabus units and topics using:
- ChromaDB semantic similarity search
- nomic-embed-text vector embeddings
- gemma4:12b candidate verification and confidence scoring
- Automated human-in-the-loop review queue flagging
"""

import logging
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.config import settings
from app.models.paper import Paper, Question
from app.models.syllabus import SyllabusNode
from app.services.ollama import ollama_service
from app.services.vector_store import vector_store

logger = logging.getLogger(__name__)

SYLLABUS_VERIFY_PROMPT = """You are an academic curriculum coordinator.
Given an exam question and top candidate syllabus topics, determine the most accurate unit/topic match.

Respond ONLY with a JSON object:
{
  "best_unit": "Unit 2: Linear Algebra",
  "best_topic": "Eigenvalues and Eigenvectors",
  "confidence": 0.95,
  "reasoning": "Direct question asking to compute characteristic roots and eigenvectors of a 3x3 matrix."
}
If none of the candidates match, set confidence lower than 0.5 and explain in reasoning.
"""


class SyllabusCorrelationAgent(BaseAgent):
    """Agent that maps each Question to its syllabus unit/topic."""

    name: str = "SyllabusCorrelationAgent"

    async def run(self, paper_id: str, **kwargs) -> dict[str, Any]:
        await self.emit_progress("syllabus", 10, f"Starting syllabus correlation for paper {paper_id}")

        # 1. Fetch paper and questions
        paper_res = await self.db.execute(select(Paper).where(Paper.paper_id == paper_id))
        paper = paper_res.scalar_one_or_none()
        if not paper:
            return {"status": "failed", "error": f"Paper {paper_id} not found"}

        q_res = await self.db.execute(select(Question).where(Question.paper_id == paper_id))
        questions = q_res.scalars().all()

        if not questions:
            await self.emit_progress("syllabus", 100, f"No questions found for paper {paper_id}")
            return {"status": "complete", "mapped_count": 0, "flagged_count": 0}

        total_q = len(questions)
        mapped_count = 0
        flagged_count = 0

        # Check if syllabus nodes exist for this subject
        node_check = await self.db.execute(
            select(SyllabusNode).where(SyllabusNode.subject == paper.subject).limit(1)
        )
        has_syllabus_nodes = node_check.scalar_one_or_none() is not None

        for idx, q in enumerate(questions):
            pct = 15 + int(((idx + 1) / total_q) * 80)
            await self.emit_progress(
                "syllabus",
                pct,
                f"Correlating Q{q.question_no} ({idx + 1}/{total_q}) to syllabus",
            )

            candidates: list[dict[str, Any]] = []
            if has_syllabus_nodes:
                try:
                    candidates = await vector_store.search_syllabus(
                        query_text=q.text,
                        subject=paper.subject,
                        top_k=settings.syllabus_similarity_top_k,
                    )
                except Exception as e:
                    self.logger.warning(f"Vector search failed for Q{q.question_id}: {e}")

            if candidates:
                cand_summary = "\n".join([
                    f"- Unit: {c['unit']} | Topic: {c['topic']} | Sub-topic: {c.get('sub_topic', '')} (Sim: {c['similarity']})"
                    for c in candidates[:4]
                ])

                prompt = f"""Subject: {paper.subject}
Question: {q.text}

Candidate Syllabus Topics:
{cand_summary}
"""
                try:
                    res = await ollama_service.generate_json(
                        prompt=prompt,
                        system=SYLLABUS_VERIFY_PROMPT,
                        model=settings.ollama_syllabus_model,
                        temperature=0.1,
                    )
                    best_unit = res.get("best_unit") or candidates[0]["unit"]
                    conf = float(res.get("confidence", candidates[0]["similarity"]))
                    reasoning = res.get("reasoning", "Semantic match to syllabus topic.")
                except Exception as llm_err:
                    self.logger.warning(f"LLM verification failed for Q{q.question_id}: {llm_err}")
                    best_unit = candidates[0]["unit"]
                    conf = float(candidates[0]["similarity"])
                    reasoning = f"Vector search top match ({candidates[0]['topic']})"

            else:
                # Syllabus not yet indexed for subject — infer unit using gemma4:12b
                prompt = f"""Subject: {paper.subject}
Question: {q.text}

Identify which unit or core module of {paper.subject} this question belongs to.
Respond ONLY with JSON:
{{
  "best_unit": "Unit Name",
  "confidence": 0.70,
  "reasoning": "Concept analysis"
}}
"""
                try:
                    res = await ollama_service.generate_json(
                        prompt=prompt,
                        model=settings.ollama_syllabus_model,
                        temperature=0.1,
                    )
                    best_unit = res.get("best_unit", "General")
                    conf = float(res.get("confidence", 0.70))
                    reasoning = res.get("reasoning", "Inferred by model")
                except Exception:
                    best_unit = "General"
                    conf = 0.50
                    reasoning = "Default assignment (no syllabus index)"

            # Apply thresholds
            q.unit_guess = best_unit
            q.unit_confidence = round(conf, 3)
            q.reasoning = reasoning

            if conf < settings.syllabus_confidence_threshold:
                q.needs_review = True
                q.review_reason = (
                    f"Low syllabus correlation confidence ({int(conf * 100)}% < "
                    f"{int(settings.syllabus_confidence_threshold * 100)}%). Requires human verification."
                )
                flagged_count += 1
            else:
                mapped_count += 1

        await self.db.commit()
        await self.emit_progress(
            "syllabus",
            100,
            f"Correlation complete. {mapped_count} mapped with high confidence, {flagged_count} flagged for review.",
        )

        return {
            "status": "complete",
            "paper_id": paper_id,
            "total_questions": total_q,
            "mapped_count": mapped_count,
            "flagged_count": flagged_count,
        }
