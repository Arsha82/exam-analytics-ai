"""
PYQ Analyzer — Configuration via Pydantic Settings.

All config is read from environment variables or a .env file.
Model routing, threshold values, and paths are centralized here.
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

# Paths default to locations inside backend/, whatever directory the server starts in.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings — loaded from environment or .env file."""

    # ── App ──
    app_name: str = "PYQ Analyzer"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    # ── Database ──
    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'pyq_analyzer.db').as_posix()}"

    # ── Redis / Celery ──
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── File Storage ──
    upload_dir: Path = BACKEND_DIR / "uploads"
    assets_dir: Path = BACKEND_DIR / "assets"
    reports_dir: Path = BACKEND_DIR / "reports"

    # ── Vector Store ──
    chroma_persist_dir: Path = BACKEND_DIR / "chroma_data"
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

    # ── Storage (v2: content-addressed sources, per-job workspaces) ──
    storage_dir: Path = BACKEND_DIR / "storage"

    # ── agy CLI (Antigravity / Gemini via the user's login) ──
    agy_bin: str = "agy"
    agy_enabled: bool = True
    agy_install_agents: bool = True
    agy_scout_model: str = "gemini-3.8-flash-medium"
    agy_reader_model: str = "gemini-3.8-flash-low"
    agy_tagger_model: str = "gemini-3.8-flash-medium"
    agy_fallback_model: str = "gemini-3.8-flash-low"
    agy_concurrency: int = 3
    agy_timeout_seconds: int = 300
    agy_cooldown_seconds: int = 1800

    # ── Acquisition ──
    acquire_min_queries: int = 8
    acquire_max_queries: int = 12
    notes_queries: int = 6
    auto_refresh_hours: int = 168  # weekly check for new papers per course
    fetch_max_bytes: int = 40 * 1024 * 1024
    fetch_timeout_seconds: float = 120.0
    fetch_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140 Safari/537.36"
    )
    dspace_sources: list[str] = ["http://202.88.225.92/xmlui"]

    # ── Extraction (transcription chain: cheapest first) ──
    extraction_chain: list[str] = ["text_layer", "local_ocr", "agy"]
    ocr_num_ctx: int = 3072  # small KV cache so the OCR model fits a 4 GB GPU next to the desktop
    ocr_num_predict: int = 2400
    ocr_render_scale: float = 2.0

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

    model_config = {"env_file": str(BACKEND_DIR / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()

# Ensure directories exist
for dir_path in [
    settings.upload_dir,
    settings.assets_dir,
    settings.reports_dir,
    settings.storage_dir / "sources",
    settings.storage_dir / "jobs",
]:
    dir_path.mkdir(parents=True, exist_ok=True)
