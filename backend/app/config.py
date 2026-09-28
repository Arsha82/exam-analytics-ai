"""
PYQ Analyzer — Configuration via Pydantic Settings.

All config is read from environment variables or a .env file.
Model routing, threshold values, and paths are centralized here.
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings — loaded from environment or .env file."""

    # ── App ──
    app_name: str = "PYQ Analyzer"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    # ── Database ──
    database_url: str = "sqlite+aiosqlite:///./pyq_analyzer.db"

    # ── Redis / Celery ──
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── File Storage ──
    upload_dir: Path = Path("./uploads")
    assets_dir: Path = Path("./assets")
    reports_dir: Path = Path("./reports")

    # ── Vector Store ──
    chroma_persist_dir: Path = Path("./chroma_data")
    embedding_model: str = "nomic-embed-text:latest"

    # ── Ollama (Local LLM & Vision) ──
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_ocr_model: str = "hf.co/sahilchachra/Unlimited-OCR-GGUF:Q4_K_M"
    ollama_vision_fallback_model: str = "moondream:latest"
    ollama_structuring_model: str = "huihui_ai/gemma-4-abliterated:e4b"
    ollama_syllabus_model: str = "huihui_ai/gemma-4-abliterated:e4b"
    ollama_prediction_model: str = "huihui_ai/gemma-4-abliterated:e4b"
    ollama_evaluation_model: str = "huihui_ai/gemma-4-abliterated:e4b"

    # ── Cloud LLM (Fallback / Quality-Critical) ──
    cloud_llm_provider: str = "none"  # "openai", "google", "anthropic", "none"
    cloud_llm_api_key: str = ""
    cloud_llm_model: str = ""

    # ── OCR ──
    tesseract_cmd: str = "tesseract"

    # ── Agent Thresholds ──
    ocr_confidence_threshold: float = 0.60
    syllabus_similarity_top_k: int = 5
    syllabus_confidence_threshold: float = 0.65
    syllabus_max_retries: int = 2
    duplicate_near_threshold: float = 0.92
    duplicate_twisted_lower: float = 0.80
    duplicate_twisted_upper: float = 0.92
    prediction_duplicate_threshold: float = 0.90
    prediction_wildcard_pct: float = 0.10
    prediction_unit_tolerance_pct: float = 0.10

    # ── Mastery ──
    mastery_alpha: float = 0.60
    mastery_clear_threshold: float = 80.0
    mastery_partial_threshold: float = 40.0

    # ── Trend Multipliers ──
    trend_rising_mult: float = 1.25
    trend_stable_mult: float = 1.0
    trend_declining_mult: float = 0.80

    # ── Weak Topic Boost ──
    weak_boost: float = 0.50
    partial_boost: float = 0.20
    clear_boost: float = 0.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

# Ensure directories exist
for dir_path in [settings.upload_dir, settings.assets_dir, settings.reports_dir]:
    dir_path.mkdir(parents=True, exist_ok=True)
