"""Models package — re-exports all ORM models for convenient import."""

from app.models.paper import Paper, Question, QuestionTopic
from app.models.syllabus import SyllabusNode
from app.models.prediction import PredictedPaper, PredictedQuestion
from app.models.attempt import Attempt, AttemptScore
from app.models.mastery import MasteryMap
from app.models.catalog import Course, CourseModule, CourseTopic
from app.models.acquisition import SourceCandidate, SourceDocument
from app.models.jobs import AnalysisSnapshot, Job, JobEvent
from app.models.student import AcademicRecord, CurriculumCourse, StudentProfile
from app.models.study import Lesson, MockPaper

__all__ = [
    "Paper",
    "Question",
    "QuestionTopic",
    "SyllabusNode",
    "PredictedPaper",
    "PredictedQuestion",
    "Attempt",
    "AttemptScore",
    "MasteryMap",
    "Course",
    "CourseModule",
    "CourseTopic",
    "SourceCandidate",
    "SourceDocument",
    "AnalysisSnapshot",
    "Job",
    "JobEvent",
    "AcademicRecord",
    "CurriculumCourse",
    "StudentProfile",
    "Lesson",
    "MockPaper",
]
