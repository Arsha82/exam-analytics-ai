"""
ORM models for the student layer: profile, scheme curriculum, academic record.

No credentials are stored. Subjects come from the official curriculum for the chosen
branch/semester; grades come from a grade card the student imports themselves.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StudentProfile(Base):
    __tablename__ = "student_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    university: Mapped[str] = mapped_column(String(32), nullable=False, default="KTU")
    scheme: Mapped[str] = mapped_column(String(16), nullable=False, default="2019")
    branch: Mapped[str | None] = mapped_column(String(16), nullable=True)  # CE, EEE, ECE, ME, MR, CSE...
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_cgpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CurriculumCourse(Base):
    """One course of a branch's semester-wise curriculum (parsed from the official PDF)."""

    __tablename__ = "curriculum_courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scheme: Mapped[str] = mapped_column(String(16), nullable=False)
    branch: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    slot: Mapped[str | None] = mapped_column(String(8), nullable=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    ltp: Mapped[str | None] = mapped_column(String(16), nullable=True)
    credits: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AcademicRecord(Base):
    """A course result (one attempt) from an imported grade card or entered by hand."""

    __tablename__ = "academic_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credits: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade: Mapped[str] = mapped_column(String(8), nullable=False)
    session_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # grade_card / manual
    source_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
