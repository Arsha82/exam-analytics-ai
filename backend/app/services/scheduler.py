"""Background re-check for new papers: each course with auto-refresh gets a `refresh` job
when its last successful paper search is older than `auto_refresh_hours`."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import func, select

from app.config import settings
from app.database import async_session_factory
from app.models.catalog import Course
from app.models.jobs import Job
from app.services.jobs import job_runner, utcnow

logger = logging.getLogger(__name__)
CHECK_EVERY_SECONDS = 3600


async def due_courses() -> list[str]:
    cutoff = utcnow() - timedelta(hours=settings.auto_refresh_hours)
    out = []
    async with async_session_factory() as db:
        for c in (await db.execute(select(Course).where(Course.auto_refresh.is_(True)))).scalars():
            last = (await db.execute(
                select(Job.finished_at).where(Job.course_code == c.code, Job.status == "succeeded",
                                              Job.kind.in_(("acquire", "auto", "refresh", "setup")))
                .order_by(Job.finished_at.desc()).limit(1))).scalar()
            if last is None or last < cutoff:
                out.append(c.code)
    return out


async def provisional_with_papers() -> list[str]:
    """Courses still on placeholder topics whose papers are read: derive topics from the questions."""
    from app.models.paper import Paper, Question

    out = []
    async with async_session_factory() as db:
        for c in (await db.execute(select(Course))).scalars():
            if not c.catalog_json.get("provisional"):
                continue
            n = (await db.execute(select(func.count()).select_from(Question).join(Paper, Paper.paper_id == Question.paper_id)
                                  .where(Paper.course_code == c.code))).scalar() or 0
            if n >= 60:
                out.append(c.code)
    return out


async def refresh_loop():
    await asyncio.sleep(60)  # let startup finish
    while True:
        try:
            for code in await due_courses():
                logger.info(f"Scheduled refresh for {code}")
                await job_runner.submit("refresh", code, {"use_agy": True})
            for code in await provisional_with_papers():
                logger.info(f"Building the topic list of {code} from its papers")
                await job_runner.submit("catalog", code, {"from": "papers"})
        except Exception as exc:  # noqa: BLE001 — the loop must survive
            logger.warning(f"refresh scheduler: {exc}")
        await asyncio.sleep(CHECK_EVERY_SECONDS)
