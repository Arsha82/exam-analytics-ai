"""Pydantic schemas for Paper and Question API request/response DTOs."""

from datetime import datetime
from pydantic import BaseModel, Field


# ── Paper schemas ──

class PaperCreate(BaseModel):
    """Schema for creating a paper record during upload."""
    subject: str = Field(..., min_length=1, max_length=64)
    year: int = Field(..., ge=1990, le=2030)
    total_marks: int = Field(..., ge=1)


class PaperOut(BaseModel):
    """Paper response DTO."""
    paper_id: str
    subject: str
    year: int
    total_marks: int
    source_file: str
    ocr_status: str
    needs_review: bool
    question_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class PaperListOut(BaseModel):
    """Paginated paper list response."""
    papers: list[PaperOut]
    total: int


# ── Question schemas ──

class QuestionOut(BaseModel):
    """Question response DTO."""
    question_id: str
    paper_id: str
    year: int
    question_no: str
    text: str
    marks: float
    has_diagram: bool
    diagram_ref: str | None = None
    or_choice_group: str | None = None
    unit_guess: str | None = None
    unit_confidence: float | None = None
    reasoning: str | None = None
    embedding_id: str | None = None
    needs_review: bool
    review_reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class QuestionUpdate(BaseModel):
    """Manual override fields for review resolution."""
    unit_guess: str | None = None
    marks: float | None = None
    needs_review: bool | None = None
    review_reason: str | None = None


class QuestionListOut(BaseModel):
    """Paginated question list response."""
    questions: list[QuestionOut]
    total: int
