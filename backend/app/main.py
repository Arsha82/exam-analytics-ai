"""
PYQ Analyzer — FastAPI Application Factory.

Creates the app, configures CORS, registers routers,
and initializes the database on startup.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(name)-24s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle events."""
    logger.info("Starting PYQ Analyzer backend...")
    await init_db()
    logger.info("Database tables initialized.")
    yield
    logger.info("Shutting down PYQ Analyzer backend.")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="Multi-Agent Question Paper Intelligence & Adaptive Testing System",
        version="0.1.0",
        lifespan=lifespan,
    )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Static files (uploaded papers, extracted assets, generated reports) ──
    app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")
    app.mount("/assets", StaticFiles(directory=str(settings.assets_dir)), name="assets")
    app.mount("/reports", StaticFiles(directory=str(settings.reports_dir)), name="reports")

    # ── Routers ──
    from app.routers import papers, questions, syllabus, analysis, predictions, attempts, mastery, pipeline

    app.include_router(papers.router, prefix="/api/papers", tags=["Papers"])
    app.include_router(questions.router, prefix="/api/questions", tags=["Questions"])
    app.include_router(syllabus.router, prefix="/api/syllabus", tags=["Syllabus"])
    app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis"])
    app.include_router(predictions.router, prefix="/api/predictions", tags=["Predictions"])
    app.include_router(attempts.router, prefix="/api/attempts", tags=["Attempts"])
    app.include_router(mastery.router, prefix="/api/mastery", tags=["Mastery"])
    app.include_router(pipeline.router, prefix="/api/pipeline", tags=["Pipeline"])

    # ── Health check ──
    @app.get("/api/health", tags=["Health"])
    async def health_check():
        return {
            "status": "healthy",
            "service": settings.app_name,
            "version": "0.1.0",
        }

    return app


app = create_app()
