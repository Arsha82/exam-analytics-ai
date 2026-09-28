"""Agents package init."""

from app.agents.base import BaseAgent
from app.agents.ocr import OcrAgent
from app.agents.boundary_detection import DocumentBoundaryAgent
from app.agents.structuring import StructuringAgent
from app.agents.syllabus import SyllabusCorrelationAgent
from app.agents.pattern_analysis import PatternAnalysisAgent
from app.agents.prediction import PredictionAgent
from app.agents.evaluation import EvaluationAgent

__all__ = [
    "BaseAgent",
    "OcrAgent",
    "DocumentBoundaryAgent",
    "StructuringAgent",
    "SyllabusCorrelationAgent",
    "PatternAnalysisAgent",
    "PredictionAgent",
    "EvaluationAgent",
]
