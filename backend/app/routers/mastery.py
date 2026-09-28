"""Mastery router — get/reset mastery map, progression history, topic buckets."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.mastery import MasteryMap
from app.models.attempt import Attempt

router = APIRouter()


@router.get("")
async def get_mastery(
    student_id: str = "default",
    subject: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get student mastery map across units and topics."""
    query = select(MasteryMap).where(MasteryMap.student_id == student_id)
    if subject:
        query = query.where(MasteryMap.subject == subject)

    res = await db.execute(query.order_by(MasteryMap.score_pct.asc()))
    records = res.scalars().all()

    items = [
        {
            "unit": m.unit,
            "subject": m.subject,
            "score_pct": m.score_pct,
            "bucket": m.bucket,
            "attempt_count": m.attempt_count,
            "last_updated": m.last_updated.isoformat() if m.last_updated else None,
        }
        for m in records
    ]

    # Calculate overall subject readiness
    overall = round(sum(m.score_pct for m in records) / len(records), 1) if records else 0.0

    # Group into weak, partial, clear
    weak_topics = [m["unit"] for m in items if m["bucket"] == "weak"]
    partial_topics = [m["unit"] for m in items if m["bucket"] == "partial"]
    clear_topics = [m["unit"] for m in items if m["bucket"] == "clear"]

    return {
        "student_id": student_id,
        "subject": subject,
        "overall_readiness_pct": overall,
        "topic_mastery": items,
        "weak_topics": weak_topics,
        "partial_topics": partial_topics,
        "clear_topics": clear_topics,
        "recommended_focus": weak_topics[:2] if weak_topics else (partial_topics[:2] if partial_topics else []),
    }


@router.get("/history")
async def get_mastery_history(
    student_id: str = "default",
    subject: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get chronological attempts and score progression."""
    query = (
        select(Attempt)
        .where(Attempt.student_id == student_id)
        .order_by(Attempt.submitted_at.asc())
    )
    res = await db.execute(query)
    attempts = res.scalars().all()

    progression = []
    for att in attempts:
        if att.total_max_marks and att.total_marks_awarded is not None:
            pct = round((att.total_marks_awarded / att.total_max_marks) * 100, 1)
            progression.append({
                "attempt_id": att.attempt_id,
                "predicted_paper_id": att.predicted_paper_id,
                "score_pct": pct,
                "submitted_at": att.submitted_at.isoformat() if att.submitted_at else None,
            })

    return {"student_id": student_id, "subject": subject, "history": progression}


@router.post("/reset")
async def reset_mastery(
    student_id: str = "default",
    subject: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Reset mastery scores for testing or new syllabus cycle."""
    query = select(MasteryMap).where(MasteryMap.student_id == student_id)
    if subject:
        query = query.where(MasteryMap.subject == subject)
    res = await db.execute(query)
    for m in res.scalars().all():
        await db.delete(m)
    await db.commit()
    return {"status": "reset", "message": f"Mastery reset for {student_id}"}
