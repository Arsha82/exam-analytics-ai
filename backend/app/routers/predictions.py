"""Predictions router — generate, list, download predicted papers."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.prediction import PredictedPaper, PredictedQuestion
from app.agents.prediction import PredictionAgent
from app.schemas.analysis import PredictedPaperOut, PredictedQuestionOut

router = APIRouter()


@router.post("/generate")
async def generate_prediction(
    subject: str,
    target_marks: int = 100,
    variant_count: int = 1,
    student_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate one or more variants of a predicted paper with rubrics."""
    agent = PredictionAgent(db=db)
    generated_papers = []

    primary_id = None
    for v in range(1, variant_count + 1):
        res = await agent.run(
            subject=subject,
            target_marks=target_marks,
            variant=v,
            parent_paper_id=primary_id,
            student_id=student_id,
        )
        if v == 1:
            primary_id = res["predicted_paper_id"]
        generated_papers.append(res)

    return {
        "status": "complete",
        "subject": subject,
        "variants_generated": len(generated_papers),
        "papers": generated_papers,
    }


@router.get("")
async def list_predictions(
    subject: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List generated predicted papers."""
    query = select(PredictedPaper).order_by(PredictedPaper.generated_at.desc())
    if subject:
        query = query.where(PredictedPaper.subject == subject)

    res = await db.execute(query)
    papers = res.scalars().all()

    items = []
    for p in papers:
        q_count = (
            await db.execute(
                select(func.count()).where(PredictedQuestion.predicted_paper_id == p.predicted_paper_id)
            )
        ).scalar() or 0
        items.append({
            "predicted_paper_id": p.predicted_paper_id,
            "subject": p.subject,
            "target_marks": p.target_marks,
            "variant": p.variant,
            "parent_paper_id": p.parent_paper_id,
            "question_count": q_count,
            "generated_at": p.generated_at.isoformat() if p.generated_at else None,
        })

    return {"predictions": items, "total": len(items)}


@router.get("/{predicted_paper_id}")
async def get_prediction(
    predicted_paper_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single predicted paper with its full questions and checklist rubrics."""
    query = (
        select(PredictedPaper)
        .options(selectinload(PredictedPaper.questions))
        .where(PredictedPaper.predicted_paper_id == predicted_paper_id)
    )
    res = await db.execute(query)
    paper = res.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Predicted paper not found")

    questions_out = [
        {
            "question_no": q.question_no,
            "unit": q.unit,
            "text": q.text,
            "marks": q.marks,
            "source": q.source,
            "similarity_flag": q.similarity_flag,
            "rubric": q.rubric,
        }
        for q in sorted(paper.questions, key=lambda x: int(x.question_no) if x.question_no.isdigit() else 0)
    ]

    return {
        "predicted_paper_id": paper.predicted_paper_id,
        "subject": paper.subject,
        "target_marks": paper.target_marks,
        "variant": paper.variant,
        "parent_paper_id": paper.parent_paper_id,
        "generated_at": paper.generated_at.isoformat() if paper.generated_at else None,
        "questions": questions_out,
    }


@router.get("/{predicted_paper_id}/download")
async def download_prediction(
    predicted_paper_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Generate printable clean HTML view for export / printing."""
    query = (
        select(PredictedPaper)
        .options(selectinload(PredictedPaper.questions))
        .where(PredictedPaper.predicted_paper_id == predicted_paper_id)
    )
    res = await db.execute(query)
    paper = res.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Predicted paper not found")

    q_html = ""
    for q in sorted(paper.questions, key=lambda x: int(x.question_no) if x.question_no.isdigit() else 0):
        rubric_items = "".join([
            f"<li>{r.get('point', '')} <span style='color:#666'>({r.get('weight', 1)} Marks)</span></li>"
            for r in (q.rubric or [])
        ])
        q_html += f"""
        <div style="margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #e2e8f0;">
            <div style="display:flex; justify-content:space-between; font-weight:600; margin-bottom: 8px;">
                <span>Q{q.question_no}. [{q.unit}]</span>
                <span>[{q.marks} Marks]</span>
            </div>
            <p style="font-size: 16px; line-height: 1.6; margin: 0 0 12px 0;">{q.text}</p>
            <details style="background: #f8fafc; padding: 8px 12px; border-radius: 6px; font-size: 13px;">
                <summary style="cursor:pointer; color:#475569; font-weight:500;">Grading Rubric Checklist</summary>
                <ul style="margin: 8px 0 0 16px; padding: 0;">{rubric_items}</ul>
            </details>
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <title>{paper.subject} - Predicted Exam Paper (v{paper.variant})</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #1e293b; }}
            .header {{ text-align: center; border-bottom: 2px solid #0f172a; padding-bottom: 16px; margin-bottom: 28px; }}
            .header h1 {{ margin: 0 0 8px 0; font-size: 24px; }}
            .meta {{ display: flex; justify-content: space-between; font-size: 14px; color: #64748b; }}
            @media print {{ details {{ display: none !important; }} }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>PREDICTED EXAMINATION PAPER</h1>
            <div style="font-size: 18px; font-weight: 600; color: #3b82f6;">{paper.subject}</div>
            <div class="meta" style="margin-top: 12px;">
                <span>Variant {paper.variant}</span>
                <span>Max Marks: {paper.target_marks}</span>
                <span>Time Allowed: 3 Hours</span>
            </div>
        </div>
        <div>
            {q_html}
        </div>
        <script>window.print();</script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
