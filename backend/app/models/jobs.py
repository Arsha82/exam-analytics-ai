"""
ORM models for the persisted job system (v2) and analysis snapshots.

Every long-running action (acquire, process, insights) is a Job with an
append-only event log, so progress is visible, survives page reloads and
can be inspected after failures.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # queued / running / succeeded / failed / cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    course_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    level: Mapped[str] = mapped_column(String(8), nullable=False, default="info")
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AnalysisSnapshot(Base):
    """Cached insights + backtest for a course, recomputed after data changes."""

    __tablename__ = "analysis_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.code", ondelete="CASCADE"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    results: Mapped[dict] = mapped_column(JSON, nullable=False)
