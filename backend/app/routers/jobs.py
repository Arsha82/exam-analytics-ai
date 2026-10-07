"""Jobs router (v2) — list, inspect and cancel background jobs."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.jobs import Job, JobEvent
from app.routers.courses import _job_out
from app.services.jobs import job_runner

router = APIRouter()


@router.get("")
async def list_jobs(course: str | None = None, status: str | None = None, limit: int = 50,
                    db: AsyncSession = Depends(get_db)):
    q = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(min(limit, 200))
    if course:
        q = q.where(Job.course_code == course.upper())
    if status:
        q = q.where(Job.status == status)
    return {"jobs": [_job_out(j) for j in (await db.execute(q)).scalars()]}


@router.get("/{job_id}")
async def get_job(job_id: str, after: int = 0, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    events = (await db.execute(select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.id > after)
                               .order_by(JobEvent.id))).scalars()
    return {**_job_out(job), "events": [{"id": e.id, "ts": e.ts, "level": e.level, "stage": e.stage,
                                         "message": e.message, "data": e.data} for e in events]}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str):
    if not await job_runner.cancel(job_id):
        raise HTTPException(status_code=409, detail="Job is not running")
    return {"status": "cancelling"}
