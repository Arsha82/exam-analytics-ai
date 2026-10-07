"""
PYQ Analyzer — FastAPI Application Factory.

Creates the app, configures CORS, registers routers,
and initializes the database on startup.
"""

import asyncio
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
    logger.info("Database schema at latest migration.")

    from app.services import course_pipeline as cp
    from app.services.jobs import job_runner
    from app.services.lessons import lesson_job, video_job
    from app.services.library import search_job, sort_job
    from app.services.scheduler import refresh_loop

    for kind, fn in {
        "acquire": cp.acquire_job, "process": cp.process_job, "insights": cp.insights_job,
        "notes": cp.notes_job, "auto": cp.auto_job, "refresh": cp.refresh_job,
        "catalog": cp.catalog_job, "setup": cp.setup_job, "lesson": lesson_job, "video": video_job,
        "library_sort": sort_job, "library_search": search_job,
    }.items():
        job_runner.register(kind, fn)
    await job_runner.recover_on_startup()
    scheduler = asyncio.create_task(refresh_loop())
    yield
    scheduler.cancel()
    logger.info("Shutting down PYQ Analyzer backend.")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="Multi-Agent Question Paper Intelligence & Adaptive Testing System",
        version="0.2.0",
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
    from app.routers import courses, jobs, library, profile, study, system

    app.include_router(papers.router, prefix="/api/papers", tags=["Papers"])
    app.include_router(questions.router, prefix="/api/questions", tags=["Questions"])
    app.include_router(syllabus.router, prefix="/api/syllabus", tags=["Syllabus"])
    app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis"])
    app.include_router(predictions.router, prefix="/api/predictions", tags=["Predictions"])
    app.include_router(attempts.router, prefix="/api/attempts", tags=["Attempts"])
    app.include_router(mastery.router, prefix="/api/mastery", tags=["Mastery"])
    app.include_router(pipeline.router, prefix="/api/pipeline", tags=["Pipeline"])
    app.include_router(courses.router, prefix="/api/courses", tags=["Courses (v2)"])
    app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs (v2)"])
    app.include_router(system.router, prefix="/api/system", tags=["System (v2)"])
    app.include_router(profile.router, prefix="/api/profile", tags=["Profile & academics (v2)"])
    app.include_router(library.router, prefix="/api/library", tags=["Library (v2)"])
    app.include_router(study.router, prefix="/api/study", tags=["Practice & lessons (v2)"])

    # ── Health check ──
    @app.get("/api/health", tags=["Health"])
    async def health_check():
        return {
            "status": "healthy",
            "service": settings.app_name,
            "version": "0.2.0",
        }

    return app


app = create_app()
