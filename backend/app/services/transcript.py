"""
Transcript schema shared by every extraction provider (local OCR parser, agy reader,
manual edits). Providers produce a Transcript; the validator and the DB writer only
ever see this shape.
"""

from pydantic import BaseModel, Field


class TranscriptHeader(BaseModel):
    course_code: str | None = None
    course_name: str | None = None
    exam_title: str | None = None
    month: int | None = None  # 1-12
    year: int | None = None
    scheme: str | None = None
    qp_code: str | None = None
    max_marks: int | None = None
    duration: str | None = None
    cohorts: list[str] = Field(default_factory=list)


class TranscriptQuestion(BaseModel):
    part: str | None = None  # "A" / "B"
    number: int
    sub: str | None = None  # "a", "b", "c" or None
    marks: float | None = None
    text: str
    options: list[str] | None = None  # MCQ papers: the printed choices, in order (a, b, c, d)
    module: int | None = None  # module heading printed on the paper, if any
    has_diagram: bool = False
    legibility: str = "clear"  # clear / partly_unclear / unclear
    marks_inferred: bool = False  # filled from the template (e.g. 14 - other part), not read
    page: int | None = None
    bbox: list[float] | None = None  # [x1, y1, x2, y2] in the provider's page coordinates
    provider: str | None = None


class Transcript(BaseModel):
    header: TranscriptHeader = Field(default_factory=TranscriptHeader)
    questions: list[TranscriptQuestion] = Field(default_factory=list)
    provider: str = "unknown"
    model: str | None = None
    notes: str | None = None
    pages: int | None = None


class Issue(BaseModel):
    code: str
    level: str  # error / warn / info
    message: str
    number: int | None = None
    sub: str | None = None
