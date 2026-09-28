"""
PYQ Analyzer — Pattern Analysis Agent.

Statistical & semantic pattern analysis across historical exam papers:
- Unit question frequency and weightage distribution
- Yearly trend detection (rising, stable, declining) using linear regression
- Duplicate and twisted question detection via cosine similarity
- Cognitive cluster classification (derive, numerical, define, etc.)
"""

import logging
from collections import defaultdict
from typing import Any
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.config import settings
from app.models.paper import Paper, Question
from app.schemas.analysis import (
    AnalysisResults,
    ClusterItem,
    MarkWeightItem,
    TopicFrequencyItem,
    TwistedPair,
    YearTrendItem,
)
from app.services.ollama import ollama_service

logger = logging.getLogger(__name__)


class PatternAnalysisAgent(BaseAgent):
    """Statistical and semantic analysis agent for question pattern intelligence."""

    name: str = "PatternAnalysisAgent"

    async def run(self, subject: str, **kwargs) -> dict[str, Any]:
        await self.emit_progress("analysis", 10, f"Beginning pattern analysis for subject {subject}")

        # 1. Fetch all questions for this subject across all papers
        query = (
            select(Question)
            .join(Paper, Question.paper_id == Paper.paper_id)
            .where(Paper.subject == subject)
            .order_by(Question.year.asc())
        )
        res = await self.db.execute(query)
        questions = res.scalars().all()

        if not questions:
            await self.emit_progress("analysis", 100, f"No questions found for subject {subject}")
            return {
                "status": "complete",
                "results": AnalysisResults(
                    subject=subject,
                    frequency=[],
                    mark_weights=[],
                    trends=[],
                    clusters=[],
                    twisted_pairs=[],
                ).model_dump(),
            }

        total_q_count = len(questions)
        total_marks_all = sum(q.marks for q in questions) or 1.0

        await self.emit_progress("analysis", 30, f"Computing frequency and weight distributions for {total_q_count} questions")

        # 2. Group by unit
        unit_counts: dict[str, int] = defaultdict(int)
        unit_marks: dict[str, float] = defaultdict(float)
        unit_yearly_marks: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        unit_yearly_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        years_set = set()

        for q in questions:
            unit = q.unit_guess or "Unclassified"
            unit_counts[unit] += 1
            unit_marks[unit] += q.marks
            unit_yearly_marks[unit][q.year] += q.marks
            unit_yearly_counts[unit][q.year] += 1
            years_set.add(q.year)

        years = sorted(list(years_set))

        # 3. Build TopicFrequencyItem and MarkWeightItem
        frequency_items = [
            TopicFrequencyItem(
                unit=unit,
                count=count,
                pct_of_total=round((count / total_q_count) * 100, 2),
            )
            for unit, count in sorted(unit_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        mark_weight_items = [
            MarkWeightItem(
                unit=unit,
                total_marks=round(marks, 1),
                pct_of_total_marks=round((marks / total_marks_all) * 100, 2),
            )
            for unit, marks in sorted(unit_marks.items(), key=lambda x: x[1], reverse=True)
        ]

        await self.emit_progress("analysis", 55, "Calculating yearly slope trends per unit")

        # 4. Yearly trends with slope analysis
        yearly_trends: list[YearTrendItem] = []
        for unit in unit_counts.keys():
            # Calculate slope over years
            yearly_vals = [unit_yearly_marks[unit][y] for y in years]
            if len(years) > 1 and max(yearly_vals) > 0:
                x = np.arange(len(years))
                y_arr = np.array(yearly_vals)
                slope, _ = np.polyfit(x, y_arr, 1)
                norm_slope = slope / (np.mean(y_arr) + 1e-5)
                if norm_slope > 0.10:
                    trend_label = "rising"
                elif norm_slope < -0.10:
                    trend_label = "declining"
                else:
                    trend_label = "stable"
            else:
                trend_label = "stable"

            for yr in years:
                cnt = unit_yearly_counts[unit][yr]
                yr_total_marks = sum(unit_yearly_marks[u][yr] for u in unit_counts.keys()) or 1.0
                share = (unit_yearly_marks[unit][yr] / yr_total_marks) * 100

                yearly_trends.append(
                    YearTrendItem(
                        unit=unit,
                        year=yr,
                        count=cnt,
                        mark_share_pct=round(share, 2),
                        trend=trend_label,
                    )
                )

        await self.emit_progress("analysis", 75, "Running duplicate and twisted question detection")

        # 5. Semantic similarity & duplicate detection
        twisted_pairs: list[TwistedPair] = []
        if len(questions) >= 2:
            texts = [q.text for q in questions]
            try:
                embeddings = await ollama_service.embed(texts)
                if embeddings and len(embeddings) == len(questions):
                    mat = np.array(embeddings)
                    # Normalize vectors
                    norms = np.linalg.norm(mat, axis=1, keepdims=True)
                    norms[norms == 0] = 1.0
                    normalized_mat = mat / norms
                    sim_matrix = np.dot(normalized_mat, normalized_mat.T)

                    for i in range(len(questions)):
                        for j in range(i + 1, len(questions)):
                            sim = float(sim_matrix[i, j])
                            qa = questions[i]
                            qb = questions[j]

                            if sim >= settings.duplicate_near_threshold:
                                twisted_pairs.append(
                                    TwistedPair(
                                        question_id_a=qa.question_id,
                                        question_id_b=qb.question_id,
                                        similarity=round(sim, 3),
                                        verdict="near-duplicate",
                                        reasoning=f"High semantic overlap ({round(sim*100)}%) between {qa.year} Q{qa.question_no} and {qb.year} Q{qb.question_no}",
                                    )
                                )
                            elif sim >= settings.duplicate_twisted_lower:
                                twisted_pairs.append(
                                    TwistedPair(
                                        question_id_a=qa.question_id,
                                        question_id_b=qb.question_id,
                                        similarity=round(sim, 3),
                                        verdict="twisted_rewording",
                                        reasoning=f"Concept reuse with modified parameters/wording ({round(sim*100)}%)",
                                    )
                                )
            except Exception as e:
                self.logger.warning(f"Similarity matrix computation skipped: {e}")

        # 6. Question type clusters
        clusters: list[ClusterItem] = []
        cluster_map: dict[str, list[str]] = {
            "Derivation / Proof": [],
            "Numerical / Computation": [],
            "Theory / Definition": [],
            "Diagram / Circuit": [],
        }

        for q in questions:
            t = q.text.lower()
            if any(k in t for k in ["derive", "prove", "show that", "deduce"]):
                cluster_map["Derivation / Proof"].append(q.question_id)
            elif any(k in t for k in ["calculate", "find", "determine", "evaluate", "solve", "compute"]):
                cluster_map["Numerical / Computation"].append(q.question_id)
            elif q.has_diagram or any(k in t for k in ["sketch", "draw", "diagram", "circuit", "graph"]):
                cluster_map["Diagram / Circuit"].append(q.question_id)
            else:
                cluster_map["Theory / Definition"].append(q.question_id)

        for c_id, (label, qids) in enumerate(cluster_map.items()):
            if qids:
                clusters.append(ClusterItem(cluster_id=c_id + 1, label=label, question_ids=qids))

        results = AnalysisResults(
            subject=subject,
            frequency=frequency_items,
            mark_weights=mark_weight_items,
            trends=yearly_trends,
            clusters=clusters,
            twisted_pairs=twisted_pairs,
        )

        await self.emit_progress("analysis", 100, f"Analysis complete for {subject}")

        return {
            "status": "complete",
            "results": results.model_dump(),
        }
