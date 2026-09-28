"""Attempts router — upload handwritten attempt, get scores and evaluation breakdown."""

import asyncio
import uuid
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session_factory, get_db
from app.models.attempt import Attempt, AttemptScore
from app.models.prediction import PredictedPaper
from app.agents.evaluation import EvaluationAgent

router = APIRouter()


async def _run_eval_background(attempt_id: str, student_id: str):
    async with async_session_factory() as db:
        agent = EvaluationAgent(db=db)
        await agent.run(attempt_id=attempt_id, student_id=student_id)


@router.post("/upload", status_code=201)
async def upload_attempt(
    predicted_paper_id: str = Form(...),
    student_id: str = Form("default"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload scanned handwritten or typed attempt and trigger evaluation pipeline."""
    # Verify predicted paper exists
    pred_res = await db.execute(
        select(PredictedPaper).where(PredictedPaper.predicted_paper_id == predicted_paper_id)
    )
    if not pred_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Predicted paper not found")

    attempt_id = f"att_{predicted_paper_id}_{uuid.uuid4().hex[:6]}"
    file_path = settings.upload_dir / f"{attempt_id}_{file.filename}"
    content = await file.read()
    file_path.write_bytes(content)

    attempt = Attempt(
        attempt_id=attempt_id,
        predicted_paper_id=predicted_paper_id,
        student_id=student_id,
        source_file=str(file_path),
        ocr_status="processing",
    )
    db.add(attempt)
    await db.commit()

    # Trigger evaluation agent in background task
    asyncio.create_task(_run_eval_background(attempt_id, student_id))

    return {
        "status": "processing",
        "attempt_id": attempt_id,
        "predicted_paper_id": predicted_paper_id,
        "student_id": student_id,
        "message": "Answer sheet uploaded and rubric evaluation started",
    }


@router.get("")
async def list_attempts(
    student_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """List attempts for a student."""
    query = (
        select(Attempt)
        .where(Attempt.student_id == student_id)
        .order_by(Attempt.submitted_at.desc())
    )
    res = await db.execute(query)
    attempts = res.scalars().all()

    items = []
    for att in attempts:
        items.append({
            "attempt_id": att.attempt_id,
            "predicted_paper_id": att.predicted_paper_id,
            "student_id": att.student_id,
            "ocr_status": att.ocr_status,
            "total_marks_awarded": att.total_marks_awarded,
            "total_max_marks": att.total_max_marks,
            "score_pct": (
                round((att.total_marks_awarded / att.total_max_marks) * 100, 1)
                if att.total_max_marks and att.total_marks_awarded is not None
                else None
            ),
            "submitted_at": att.submitted_at.isoformat() if att.submitted_at else None,
        })

    return {"attempts": items, "total": len(items)}


@router.get("/{attempt_id}")
async def get_attempt(
    attempt_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get attempt detail with per-question scores, reasoning, and missing points."""
    query = (
        select(Attempt)
        .options(selectinload(Attempt.scores))
        .where(Attempt.attempt_id == attempt_id)
    )
    res = await db.execute(query)
    attempt = res.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    scores_out = [
        {
            "id": s.id,
            "question_id": s.question_id,
            "marks_awarded": s.marks_awarded,
            "max_marks": s.max_marks,
            "missing_points": s.missing_points,
            "checklist_results": s.checklist_results,
            "reasoning": s.reasoning,
            "low_confidence": s.low_confidence,
        }
        for s in attempt.scores
    ]

    return {
        "attempt_id": attempt.attempt_id,
        "predicted_paper_id": attempt.predicted_paper_id,
        "student_id": attempt.student_id,
        "ocr_status": attempt.ocr_status,
        "total_marks_awarded": attempt.total_marks_awarded,
        "total_max_marks": attempt.total_max_marks,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "scores": scores_out,
    }


@router.post("/{attempt_id}/re-evaluate")
async def re_evaluate_attempt(
    attempt_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Re-trigger evaluation for an attempt."""
    att = await db.get(Attempt, attempt_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attempt not found")

    att.ocr_status = "processing"
    await db.commit()

    asyncio.create_task(_run_eval_background(attempt_id, att.student_id))
    return {"status": "processing", "message": f"Re-evaluating attempt {attempt_id}"}
