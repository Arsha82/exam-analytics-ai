"""
ORM models for Paper and Question — the core structured data tables.

These are the single source of truth. Every agent reads/writes through
these models rather than passing files between each other.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Paper(Base):
    """A scanned previous-year question paper."""

    __tablename__ = "papers"

    paper_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    total_marks: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file: Mapped[str] = mapped_column(Text, nullable=False)
    ocr_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # ── v2: course-aware identity (filled by the process job) ──
    course_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    session_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exam_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    cohorts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    qp_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scheme: Mapped[str | None] = mapped_column(String(32), nullable=True)
    primary_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extraction_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issues: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Relationships
    questions: Mapped[list["Question"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Paper {self.paper_id} ({self.year})>"


class Question(Base):
    """
    A single extracted question — the canonical record.

    Every downstream agent (pattern analysis, syllabus correlation,
    prediction, evaluation) reads from and writes back to this table.
    """

    __tablename__ = "questions"

    question_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    paper_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("papers.paper_id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    question_no: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)  # MCQ papers: choices a-d
    marks: Mapped[float] = mapped_column(Float, nullable=False)
    has_diagram: Mapped[bool] = mapped_column(Boolean, default=False)
    diagram_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    or_choice_group: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Filled by syllabus correlation agent (7.4)
    unit_guess: Mapped[str | None] = mapped_column(String(128), nullable=True)
    unit_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Filled by embedding service
    embedding_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Review flag
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # ── v2: structural position (exam template) and classification ──
    part: Mapped[str | None] = mapped_column(String(4), nullable=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sub: Mapped[str | None] = mapped_column(String(8), nullable=True)
    module_no: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    legibility: Mapped[str | None] = mapped_column(String(32), nullable=True)
    marks_inferred: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)

    # Relationships
    paper: Mapped["Paper"] = relationship(back_populates="questions")
    topics: Mapped[list["QuestionTopic"]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Question {self.question_id} ({self.marks}m)>"


class QuestionTopic(Base):
    """Multi-label link between a question and a course topic (v2 taxonomy)."""

    __tablename__ = "question_topics"

    question_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("questions.question_id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("course_topics.topic_id", ondelete="CASCADE"), primary_key=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(16), default="agy")  # agy/local/human

    question: Mapped["Question"] = relationship(back_populates="topics")
