"""
PYQ Analyzer — Pipeline Runner.

Coordinates the multi-agent closed-loop pipeline asynchronously:
Stage 1: OcrAgent (PDF/image -> raw text and page streams)
Stage 1.5: DocumentBoundaryAgent (Gemma 4 intelligence boundary detection for merged PDFs)
Stage 2: StructuringAgent (raw text -> structured Question DB records)
Stage 3: SyllabusCorrelationAgent (questions -> syllabus unit mapping & review flagging)
Stage 4: PatternAnalysisAgent (updates statistical trends and duplicate detection)
"""

import asyncio
import logging
from typing import Any
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ocr import OcrAgent
from app.agents.boundary_detection import DocumentBoundaryAgent
from app.agents.structuring import StructuringAgent
from app.agents.syllabus import SyllabusCorrelationAgent
from app.agents.pattern_analysis import PatternAnalysisAgent
from app.database import async_session_factory
from app.models.paper import Paper

logger = logging.getLogger(__name__)


async def run_paper_pipeline(paper_id: str):
    """
    Execute the full question paper analysis pipeline in the background.
    Supports intelligence-driven splitting of merged multi-exam PDFs.
    """
    logger.info(f"Pipeline triggered for paper {paper_id}")

    async with async_session_factory() as db:
        try:
            # 1. OCR Agent
            ocr_agent = OcrAgent(db=db)
            ocr_res = await ocr_agent.run(paper_id=paper_id)
            if ocr_res.get("status") == "failed":
                logger.error(f"Pipeline halted at OCR stage for {paper_id}")
                return

            raw_text = ocr_res.get("raw_text", "")
            pages = ocr_res.get("pages", [raw_text])

            paper = await db.get(Paper, paper_id)
            if not paper:
                logger.error(f"Paper {paper_id} not found in database")
                return

            # 1.5 Intelligence Boundary Detection (Gemma 4)
            # Evaluates if multi-page PDF contains multiple merged exam papers
            if len(pages) > 1:
                boundary_agent = DocumentBoundaryAgent(db=db)
                boundary_res = await boundary_agent.run(
                    paper_id=paper_id,
                    pages=pages,
                    default_subject=paper.subject,
                    default_year=paper.year,
                    default_marks=paper.total_marks,
                )

                if boundary_res.get("is_merged_collection") and len(boundary_res.get("detected_papers", [])) > 1:
                    detected_papers = boundary_res["detected_papers"]
                    logger.info(
                        f"Gemma 4 boundary agent detected {len(detected_papers)} merged papers in {paper_id}!"
                    )

                    created_sub_paper_ids = []
                    for idx, dp in enumerate(detected_papers):
                        start_p = dp["start_page"]
                        end_p = dp["end_page"]
                        sub_text = "\n\n".join(pages[start_p - 1 : end_p])

                        sub_subject = dp.get("subject") or paper.subject
                        sub_year = dp.get("year") or paper.year
                        sub_marks = dp.get("total_marks") or paper.total_marks
                        sub_session = dp.get("session_month")

                        session_slug = f"_{sub_session.lower()}" if sub_session else ""
                        sub_id = f"{sub_year}_{sub_subject.lower().replace(' ', '_')}{session_slug}_{uuid.uuid4().hex[:6]}"

                        low_conf = float(dp.get("confidence", 1.0)) < 0.80
                        sub_paper = Paper(
                            paper_id=sub_id,
                            subject=sub_subject,
                            year=sub_year,
                            total_marks=sub_marks,
                            source_file=f"{paper.source_file}#pages={start_p}-{end_p}",
                            ocr_status="completed",
                            needs_review=low_conf,
                        )
                        db.add(sub_paper)
                        await db.commit()
                        created_sub_paper_ids.append((sub_id, sub_text, sub_subject))

                    # Mark parent container as 'split' so it doesn't duplicate in listings
                    paper.ocr_status = "split"
                    await db.commit()

                    # Now execute downstream agents for each discrete split paper
                    for sub_id, sub_text, sub_subj in created_sub_paper_ids:
                        logger.info(f"Processing split paper component {sub_id}...")
                        struct_agent = StructuringAgent(db=db)
                        await struct_agent.run(paper_id=sub_id, raw_text=sub_text)

                        syl_agent = SyllabusCorrelationAgent(db=db)
                        await syl_agent.run(paper_id=sub_id)

                        pattern_agent = PatternAnalysisAgent(db=db)
                        await pattern_agent.run(subject=sub_subj)

                    logger.info(
                        f"Merged PDF {paper_id} successfully split and analyzed into {len(created_sub_paper_ids)} papers."
                    )
                    return

            # 2. Structuring Agent (Single continuous paper)
            struct_agent = StructuringAgent(db=db)
            struct_res = await struct_agent.run(paper_id=paper_id, raw_text=raw_text)
            if struct_res.get("status") == "failed":
                logger.error(f"Pipeline halted at Structuring stage for {paper_id}")
                return

            # 3. Syllabus Correlation Agent
            syl_agent = SyllabusCorrelationAgent(db=db)
            syl_res = await syl_agent.run(paper_id=paper_id)
            logger.info(f"Syllabus correlation completed for {paper_id}: {syl_res}")

            # 4. Pattern Analysis
            pattern_agent = PatternAnalysisAgent(db=db)
            await pattern_agent.run(subject=paper.subject)

            logger.info(f"Pipeline finished successfully for paper {paper_id}")

        except Exception as e:
            logger.error(f"Unhandled error in paper pipeline for {paper_id}: {e}", exc_info=True)


def trigger_paper_pipeline_async(paper_id: str):
    """Fire-and-forget background task launcher for paper pipeline."""
    asyncio.create_task(run_paper_pipeline(paper_id))
