"""Questions router — browse, filter, search, review queue."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.paper import Question
from app.schemas.paper import QuestionListOut, QuestionOut, QuestionUpdate

router = APIRouter()


@router.get("", response_model=QuestionListOut)
async def list_questions(
    subject: str | None = None,
    year: int | None = None,
    unit: str | None = None,
    needs_review: bool | None = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List questions with optional filters."""
    query = select(Question)

    if subject:
        from app.models.paper import Paper
        query = query.join(Paper).where(Paper.subject == subject)
    if year:
        query = query.where(Question.year == year)
    if unit:
        query = query.where(Question.unit_guess == unit)
    if needs_review is not None:
        query = query.where(Question.needs_review == needs_review)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(Question.year.desc(), Question.question_no)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    questions = result.scalars().all()

    return QuestionListOut(
        questions=[QuestionOut.model_validate(q) for q in questions],
        total=total,
    )


@router.get("/{question_id}", response_model=QuestionOut)
async def get_question(question_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single question by ID."""
    result = await db.execute(
        select(Question).where(Question.question_id == question_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return QuestionOut.model_validate(question)


@router.patch("/{question_id}", response_model=QuestionOut)
async def update_question(
    question_id: str,
    update: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Manual override for review resolution."""
    result = await db.execute(
        select(Question).where(Question.question_id == question_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(question, field, value)

    await db.commit()
    await db.refresh(question)
    return QuestionOut.model_validate(question)
