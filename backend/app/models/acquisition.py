"""
ORM models for paper acquisition (v2) — discovered candidates and fetched documents.

Candidates are URLs found by connectors or agy web searches; they are never
trusted until downloaded, magic-checked and identified. Documents are stored
content-addressed by sha256, so the same file found twice is stored once.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SourceCandidate(Base):
    """A URL that might be a question paper, with how it was found."""

    __tablename__ = "source_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_code: Mapped[str | None] = mapped_column(  # NULL: in the library inbox, subject not known yet
        String(32), ForeignKey("courses.code", ondelete="CASCADE"), nullable=True, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    found_by: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="paper", server_default="paper")
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # new / fetched / duplicate / failed / skipped
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SourceDocument(Base):
    """A downloaded or uploaded file, stored once per content hash."""

    __tablename__ = "source_documents"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    course_code: Mapped[str | None] = mapped_column(  # NULL: in the library inbox, subject not known yet
        String(32), ForeignKey("courses.code", ondelete="CASCADE"), nullable=True, index=True
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[str] = mapped_column(String(128), nullable=False)
    label_claimed: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # paper / notes / syllabus / curriculum / grade_card
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="paper", server_default="paper", index=True)
    module_no: Mapped[int | None] = mapped_column(Integer, nullable=True)  # notes: module they cover
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # fetched / identified / duplicate / rejected / transcribed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="fetched")
    identified: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    transcript: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    paper_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
