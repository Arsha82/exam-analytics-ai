"""
ORM model for the mastery map — per-student, per-topic competency tracking.

Updated by the mastery engine after each graded attempt.
Read by the prediction agent (7.6) for weak_topic_boost weighting.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MasteryMap(Base):
    """
    Rolling-average mastery score per student per topic.

    Bucket classification:
    - clear: score_pct >= 80%
    - partial: 40% <= score_pct < 80%
    - weak: score_pct < 40%
    """

    __tablename__ = "mastery_map"

    student_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(String(64), primary_key=True)
    unit: Mapped[str] = mapped_column(String(128), primary_key=True)
    score_pct: Mapped[float] = mapped_column(Float, nullable=False)
    bucket: Mapped[str] = mapped_column(String(16), nullable=False)  # weak/partial/clear
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Mastery {self.student_id}/{self.unit}: {self.score_pct}% ({self.bucket})>"
