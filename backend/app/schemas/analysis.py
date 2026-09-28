"""Pydantic schemas for analysis, prediction, evaluation, and mastery."""

from datetime import datetime
from pydantic import BaseModel


# ── Analysis schemas ──

class TopicFrequencyItem(BaseModel):
    unit: str
    count: int
    pct_of_total: float


class MarkWeightItem(BaseModel):
    unit: str
    total_marks: float
    pct_of_total_marks: float


class YearTrendItem(BaseModel):
    unit: str
    year: int
    count: int
    mark_share_pct: float
    trend: str  # "rising", "declining", "stable"


class TwistedPair(BaseModel):
    question_id_a: str
    question_id_b: str
    similarity: float
    verdict: str  # "near-duplicate", "twisted_rewording"
    reasoning: str | None = None


class ClusterItem(BaseModel):
    cluster_id: int
    label: str  # "define", "derive", "numerical", "diagram", etc.
    question_ids: list[str]


class AnalysisResults(BaseModel):
    """Full analysis output from pattern agent (7.3)."""
    subject: str
    frequency: list[TopicFrequencyItem]
    mark_weights: list[MarkWeightItem]
    trends: list[YearTrendItem]
    clusters: list[ClusterItem]
    twisted_pairs: list[TwistedPair]


# ── Prediction schemas ──

class PredictionRequest(BaseModel):
    subject: str
    target_marks: int = 100
    variant_count: int = 2  # Number of alternate papers to generate


class RubricItem(BaseModel):
    point: str
    weight: float


class PredictedQuestionOut(BaseModel):
    question_no: str
    unit: str
    text: str
    marks: float
    source: str
    similarity_flag: str | None = None
    rubric: list[RubricItem] | None = None


class PredictedPaperOut(BaseModel):
    predicted_paper_id: str
    subject: str
    target_marks: int
    variant: int
    questions: list[PredictedQuestionOut]
    generated_at: datetime

    model_config = {"from_attributes": True}


# ── Evaluation schemas ──

class AttemptScoreOut(BaseModel):
    question_id: str
    marks_awarded: float
    max_marks: float
    missing_points: list[str] | None = None
    reasoning: str
    low_confidence: bool

    model_config = {"from_attributes": True}


class AttemptOut(BaseModel):
    attempt_id: str
    predicted_paper_id: str
    student_id: str
    ocr_status: str
    total_marks_awarded: float | None = None
    total_max_marks: float | None = None
    scores: list[AttemptScoreOut] = []
    submitted_at: datetime

    model_config = {"from_attributes": True}


# ── Mastery schemas ──

class MasteryItem(BaseModel):
    unit: str
    score_pct: float
    bucket: str  # "weak", "partial", "clear"
    attempt_count: int
    last_updated: datetime


class MasteryMapOut(BaseModel):
    student_id: str
    subject: str
    topic_mastery: list[MasteryItem]


# ── Pipeline status ──

class PipelineEvent(BaseModel):
    agent: str
    stage: str
    progress: int  # 0-100
    detail: str = ""
    timestamp: datetime
