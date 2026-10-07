"""
Persisted job runner (v2).

A job is a DB row plus an append-only event log. Events are also broadcast on the
in-memory event bus, so the existing WebSocket (/api/pipeline/ws) streams them live.
Jobs run as asyncio tasks inside the API process; on restart, unfinished jobs are
marked failed ("interrupted") so nothing is left spinning forever.
"""

import asyncio
import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select, update

from app.database import async_session_factory
from app.models.jobs import Job, JobEvent
from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Naive UTC, matching SQLite's CURRENT_TIMESTAMP used by server defaults."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


RESUMABLE = ("library_sort", "library_search", "setup", "auto", "refresh", "acquire", "process", "notes", "catalog", "lesson", "video")
COURSE_EXCLUSIVE = ("acquire", "process", "insights", "notes", "auto", "refresh", "catalog", "setup")


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id: str, kind: str, course_code: str | None):
        self.job_id = job_id
        self.kind = kind
        self.course_code = course_code
        self.cancel_requested = False
        self._progress = 0

    async def log(self, level: str, stage: str, message: str, data: dict | None = None, progress: int | None = None):
        if progress is not None:
            self._progress = max(0, min(100, progress))
        async with async_session_factory() as db:
            db.add(JobEvent(job_id=self.job_id, level=level, stage=stage, message=message, data=data))
            if progress is not None:
                await db.execute(update(Job).where(Job.id == self.job_id).values(progress=self._progress))
            await db.commit()
        log_fn = logger.warning if level in ("warn", "error") else logger.info
        log_fn(f"[job {self.job_id} {stage}] {message}")
        await event_bus.publish(
            {
                "agent": f"job:{self.kind}",
                "stage": stage,
                "progress": self._progress,
                "detail": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "job_id": self.job_id,
                "kind": self.kind,
                "level": level,
                "course_code": self.course_code,
            }
        )

    async def info(self, stage: str, message: str, data: dict | None = None, progress: int | None = None):
        await self.log("info", stage, message, data, progress)

    async def warn(self, stage: str, message: str, data: dict | None = None):
        await self.log("warn", stage, message, data)

    def check_cancel(self):
        if self.cancel_requested:
            raise JobCancelled()

    def event_fn(self, stage: str):
        """Adapter for services that report through an (level, message, data) callback."""

        async def _fn(level: str, message: str, data: dict | None = None):
            await self.log(level, stage, message, data)

        return _fn


JobFn = Callable[[JobContext, dict[str, Any]], Awaitable[dict[str, Any]]]


class JobRunner:
    def __init__(self):
        self.registry: dict[str, JobFn] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._contexts: dict[str, JobContext] = {}

    def register(self, kind: str, fn: JobFn):
        self.registry[kind] = fn

    async def submit(self, kind: str, course_code: str | None, params: dict[str, Any] | None = None) -> Job:
        if kind not in self.registry:
            raise ValueError(f"Unknown job kind '{kind}'")
        async with async_session_factory() as db:
            # One pipeline job per course at a time (they read and write the same rows).
            same_course = kind in COURSE_EXCLUSIVE and course_code is not None
            candidates = (
                await db.execute(
                    select(Job).where(
                        Job.kind.in_(COURSE_EXCLUSIVE) if same_course else Job.kind == kind,
                        Job.course_code == course_code,
                        Job.status.in_(("queued", "running")),
                    )
                )
            ).scalars().all()
            # Other kinds (lesson, video) de-duplicate on their parameters, e.g. the lesson id.
            running = next((j for j in candidates if same_course or (j.params or {}) == (params or {})), None)
            if running is not None:
                return running
            job = Job(
                id=f"{kind}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
                kind=kind,
                status="queued",
                course_code=course_code,
                params=params or {},
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)
        ctx = JobContext(job.id, kind, course_code)
        self._contexts[job.id] = ctx
        self._tasks[job.id] = asyncio.create_task(self._run(ctx, params or {}))
        return job

    async def _set(self, job_id: str, **values):
        async with async_session_factory() as db:
            await db.execute(update(Job).where(Job.id == job_id).values(**values))
            await db.commit()

    async def _run(self, ctx: JobContext, params: dict[str, Any]):
        await self._set(ctx.job_id, status="running", started_at=utcnow())
        await ctx.info("start", f"{ctx.kind} started", progress=0)
        try:
            result = await self.registry[ctx.kind](ctx, params)
            await self._set(ctx.job_id, status="succeeded", result=result, progress=100, finished_at=utcnow())
            await ctx.info("done", f"{ctx.kind} finished", data=result, progress=100)
        except JobCancelled:
            await self._set(ctx.job_id, status="cancelled", finished_at=utcnow())
            await ctx.warn("cancelled", f"{ctx.kind} cancelled")
        except Exception as exc:  # noqa: BLE001 — a job must never die silently
            tb = traceback.format_exc(limit=8)
            await self._set(ctx.job_id, status="failed", error=f"{exc}", finished_at=utcnow())
            await ctx.log("error", "failed", f"{type(exc).__name__}: {exc}", {"traceback": tb})
        finally:
            self._tasks.pop(ctx.job_id, None)
            self._contexts.pop(ctx.job_id, None)

    async def cancel(self, job_id: str) -> bool:
        ctx = self._contexts.get(job_id)
        if ctx is None:
            return False
        ctx.cancel_requested = True
        async with async_session_factory() as db:  # remembered across a restart: never resumed
            job = await db.get(Job, job_id)
            if job is not None:
                job.params = {**(job.params or {}), "cancel_requested": True}
                await db.commit()
        return True

    async def recover_on_startup(self) -> list[Job]:
        """Mark unfinished jobs as interrupted; pipeline jobs are resumed once (they are idempotent)."""
        async with async_session_factory() as db:
            stuck = list((await db.execute(select(Job).where(Job.status.in_(("queued", "running"))))).scalars())
            await db.execute(
                update(Job)
                .where(Job.status.in_(("queued", "running")))
                .values(status="failed", error="interrupted by a server restart", finished_at=utcnow())
            )
            await db.commit()
        resumed = []
        for j in stuck:
            tries = int((j.params or {}).get("resumed", 0))
            if j.kind in RESUMABLE and tries < 1 and j.kind in self.registry and not (j.params or {}).get("cancel_requested"):
                resumed.append(await self.submit(j.kind, j.course_code, {**(j.params or {}), "resumed": tries + 1}))
        return resumed


job_runner = JobRunner()
