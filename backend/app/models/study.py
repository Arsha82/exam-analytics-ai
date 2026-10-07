"""ORM models for practice and learning: mock papers and narrated lessons."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MockPaper(Base):
    """A practice paper assembled from real PYQs; always passes the exam-template validator."""

    __tablename__ = "mock_papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.code", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    items: Mapped[list] = mapped_column(JSON, nullable=False)  # [{slot, number, sub, question_id, ...}]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Lesson(Base):
    """A narrated slide lesson for one topic (deck JSON; optional rendered MP4)."""

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.code", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")  # queued/ready/failed
    deck: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # rendering/ready/failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
