"""
ORM models for the course catalog (v2) — course, modules, topic taxonomy.

A course is loaded from a catalog definition (app/catalog/<university>/<code>.json)
and owns the closed topic list that questions are tagged against.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Course(Base):
    """A university course (subject) the student is preparing for."""

    __tablename__ = "courses"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    university: Mapped[str] = mapped_column(String(64), nullable=False)
    scheme: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slot: Mapped[str | None] = mapped_column(String(8), nullable=True)
    credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    auto_refresh: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CourseModule(Base):
    """A syllabus module of a course (KTU courses have five)."""

    __tablename__ = "course_modules"

    course_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.code", ondelete="CASCADE"), primary_key=True
    )
    module_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)


class CourseTopic(Base):
    """A leaf topic in a module — the closed label set for tagging."""

    __tablename__ = "course_topics"

    topic_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    course_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.code", ondelete="CASCADE"), nullable=False, index=True
    )
    module_no: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
