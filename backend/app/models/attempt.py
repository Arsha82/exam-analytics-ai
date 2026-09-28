"""
ORM models for student attempts and per-question scoring.

Written by the evaluation agent (7.7) after grading a
handwritten answer sheet against a checklist rubric.
"""

from datetime import datetime

from sqlalchemy import (
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
from sqlalchemy import JSON

from app.database import Base


class Attempt(Base):
    """A student's handwritten attempt at a predicted paper."""

    __tablename__ = "attempts"

    attempt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    predicted_paper_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("predicted_papers.predicted_paper_id"),
        nullable=False,
    )
    student_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    source_file: Mapped[str] = mapped_column(Text, nullable=False)
    ocr_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )
    total_marks_awarded: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_max_marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    scores: Mapped[list["AttemptScore"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Attempt {self.attempt_id}>"


class AttemptScore(Base):
    """
    Per-question grading result from the evaluation agent.

    Each row corresponds to one question in the attempt,
    graded against a checklist rubric.
    """

    __tablename__ = "attempt_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("attempts.attempt_id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[str] = mapped_column(String(128), nullable=False)
    marks_awarded: Mapped[float] = mapped_column(Float, nullable=False)
    max_marks: Mapped[float] = mapped_column(Float, nullable=False)

    # Detailed grading output
    missing_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    checklist_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    attempt: Mapped["Attempt"] = relationship(back_populates="scores")

    def __repr__(self) -> str:
        return f"<AttemptScore {self.question_id}: {self.marks_awarded}/{self.max_marks}>"
