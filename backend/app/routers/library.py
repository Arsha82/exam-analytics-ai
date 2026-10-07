"""Library: gather papers for any subject from Home (upload ZIP/folder/files, wide agy search)."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.acquisition import SourceDocument
from app.models.catalog import Course
from app.models.jobs import Job
from app.routers.courses import _job_out
from app.services.jobs import job_runner
from app.services.library import assign, norm_code, store_files

router = APIRouter()


class SearchBody(BaseModel):
    query: str | None = None
    semester: int | None = None


class AdoptBody(BaseModel):
    code: str
    sha256: str | None = None  # one document (manual assignment); otherwise every library paper for `code`


@router.get("")
async def library(db: AsyncSession = Depends(get_db)):
    docs = (await db.execute(select(SourceDocument).where(SourceDocument.course_code.is_(None)))).scalars().all()
    groups: dict[str, dict] = {}
    unidentified, rejected, pending = [], 0, 0
    for d in docs:
        ident = d.identified or {}
        if d.status == "inbox":
            pending += 1
        elif d.status == "other_course" and ident.get("course_code"):
            g = groups.setdefault(ident["course_code"], {"code": ident["course_code"], "title": ident.get("course_name"),
                                                         "papers": 0})
            g["papers"] += 1
            g["title"] = g["title"] or ident.get("course_name")
        elif d.status == "unidentified":
            unidentified.append({"sha256": d.sha256, "name": d.label_claimed, "pages": d.pages,
                                 "file_url": f"/api/library/documents/{d.sha256}/file"})
        else:
            rejected += 1
    jobs = (await db.execute(select(Job).where(Job.kind.in_(("library_sort", "library_search")))
                             .order_by(Job.created_at.desc()).limit(5))).scalars().all()
    return {"pending": pending, "other_subjects": sorted(groups.values(), key=lambda g: -g["papers"]),
            "unidentified": unidentified, "not_papers": rejected, "jobs": [_job_out(j) for j in jobs]}


@router.post("/upload", status_code=201)
async def upload(files: list[UploadFile] = File(...), db: AsyncSession = Depends(get_db)):
    """PDFs, photos, ZIPs or a whole folder, for any subjects; sorted by the code printed on each paper."""
    out = await store_files(db, [(f.filename or "upload", await f.read()) for f in files], None)
    job = await job_runner.submit("library_sort", None, {"add_any": True}) if out["added"] else None
    return {**{k: out[k] for k in ("added", "duplicates", "skipped")}, "job": _job_out(job) if job else None}


@router.post("/search", status_code=202)
async def search(body: SearchBody):
    job = await job_runner.submit("library_search", None, body.model_dump())
    return _job_out(job)


@router.post("/adopt", status_code=201)
async def adopt(body: AdoptBody, db: AsyncSession = Depends(get_db)):
    """Add a subject from the library: its papers move there and get read."""
    code = norm_code(body.code)
    if not code:
        raise HTTPException(status_code=422, detail="Not a subject code (e.g. MAT201)")
    q = select(SourceDocument).where(SourceDocument.course_code.is_(None))
    if body.sha256:
        docs = [d for d in (await db.execute(q.where(SourceDocument.sha256 == body.sha256))).scalars()]
    else:
        docs = [d for d in (await db.execute(q)).scalars() if (d.identified or {}).get("course_code") == code]
    if not docs:
        raise HTTPException(status_code=404, detail="Nothing in the library for that")
    title = next(((d.identified or {}).get("course_name") for d in docs if (d.identified or {}).get("course_name")), None)
    course: Course = await assign(db, docs, code, title)
    job = await job_runner.submit("process", course.code, {"use_agy": True})
    return {"code": course.code, "title": course.title, "moved": len(docs), "job": _job_out(job)}


@router.get("/documents/{sha}/file")
async def document_file(sha: str, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse

    doc = await db.get(SourceDocument, sha)
    if doc is None or doc.course_code is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(doc.local_path, media_type=doc.mime, filename=f"library_{sha[:10]}.{doc.local_path.rsplit('.', 1)[-1]}")
