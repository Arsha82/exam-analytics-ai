"""Courses router (v2) — catalog, course workspace data, and job launchers."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.acquisition import SourceCandidate, SourceDocument
from app.models.catalog import Course, CourseModule, CourseTopic
from app.models.jobs import AnalysisSnapshot, Job
from app.models.paper import Paper, Question, QuestionTopic
from app.services.acquisition.sessions import session_label
from app.services.catalog import ensure_course, list_catalog
from app.services.course_pipeline import coverage
from app.services.exam_templates import get_template, validate
from app.services.jobs import job_runner
from app.services.transcript import Transcript, TranscriptHeader, TranscriptQuestion

router = APIRouter()


class AddCourse(BaseModel):
    code: str
    auto: bool = False  # start find → read → notes right away


class JobParams(BaseModel):
    use_agy: bool = True
    reprocess: bool = False
    retag: bool = False
    agy_repair_budget: int = 10
    paper_ids: list[str] | None = None  # process: redo only these papers
    broad: bool = False  # acquire: keep every paper agy finds, even other courses


class QuestionEdit(BaseModel):
    text: str | None = None
    options: list[str] | None = None  # MCQ papers
    marks: float | None = None
    topics: list[str] | None = None
    kind: str | None = None
    resolved: bool | None = None


async def _course(db: AsyncSession, code: str) -> Course:
    course = await db.get(Course, code.upper())
    if course is None:
        raise HTTPException(status_code=404, detail=f"Course {code} not added yet")
    return course


def _job_out(j: Job) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "course_code": j.course_code, "progress": j.progress,
            "params": j.params, "result": j.result, "error": j.error, "created_at": j.created_at,
            "started_at": j.started_at, "finished_at": j.finished_at}


@router.get("/catalog")
async def get_catalog():
    return {"courses": list_catalog()}


@router.get("")
async def list_courses(db: AsyncSession = Depends(get_db)):
    out = []
    for c in (await db.execute(select(Course).order_by(Course.code))).scalars():
        papers = (await db.execute(select(func.count()).select_from(Paper).where(Paper.course_code == c.code))).scalar() or 0
        docs = (await db.execute(select(func.count()).select_from(SourceDocument).where(SourceDocument.course_code == c.code))).scalar() or 0
        snap = (await db.execute(select(AnalysisSnapshot).where(AnalysisSnapshot.course_code == c.code)
                                 .order_by(AnalysisSnapshot.id.desc()).limit(1))).scalars().first()
        cov = await coverage(db, c)
        out.append({"code": c.code, "title": c.title, "university": c.university, "scheme": c.scheme,
                    "semester": c.semester, "credits": c.credits, "papers": papers, "documents": docs,
                    "coverage": {"found": cov["found"], "expected": cov["expected"]},
                    "last_analyzed": snap.computed_at if snap else None})
    return {"courses": out}


@router.post("", status_code=201)
async def add_course(body: AddCourse, db: AsyncSession = Depends(get_db)):
    try:
        course = await ensure_course(db, body.code)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"{body.code} is not in the catalog")
    job = None
    if body.auto:
        job = await job_runner.submit("setup" if course.catalog_json.get("provisional") else "auto", course.code,
                                      {"use_agy": True})
    return {"code": course.code, "title": course.title, "job_id": job.id if job else None}


@router.get("/{code}")
async def get_course(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    modules = list((await db.execute(select(CourseModule).where(CourseModule.course_code == course.code)
                                     .order_by(CourseModule.module_no))).scalars())
    topics = list((await db.execute(select(CourseTopic).where(CourseTopic.course_code == course.code))).scalars())
    cdef = course.catalog_json
    order = {t["id"]: i for i, t in enumerate(t for m in cdef["modules"] for t in m["topics"])}
    return {
        "code": course.code, "title": course.title, "university": cdef.get("university_name", course.university),
        "scheme": course.scheme, "semester": course.semester, "slot": course.slot, "credits": course.credits,
        "template_id": course.template_id,
        "provisional": bool(cdef.get("provisional")), "syllabus_source": cdef.get("syllabus_source"),
        "modules": [{"no": m.module_no, "title": m.title,
                     "syllabus": next((x.get("syllabus") for x in cdef["modules"] if x["no"] == m.module_no), None),
                     "topics": [{"id": t.topic_id, "name": t.name}
                                for t in sorted(topics, key=lambda t: order.get(t.topic_id, 999)) if t.module_no == m.module_no]}
                    for m in modules],
        "sources": cdef.get("sources", {}),
    }


@router.post("/{code}/acquire", status_code=202)
async def start_acquire(code: str, body: JobParams | None = None, db: AsyncSession = Depends(get_db)):
    try:
        course = await ensure_course(db, code)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"{code} is not in the catalog")
    job = await job_runner.submit("acquire", course.code, (body or JobParams()).model_dump())
    return _job_out(job)


@router.post("/{code}/process", status_code=202)
async def start_process(code: str, body: JobParams | None = None, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    job = await job_runner.submit("process", course.code, (body or JobParams()).model_dump())
    return _job_out(job)


@router.post("/{code}/catalog", status_code=202)
async def start_catalog(code: str, source: str = "syllabus", db: AsyncSession = Depends(get_db)):
    """(Re)build the topic list: from the official syllabus, or (`source=papers`) from read past papers."""
    course = await _course(db, code)
    job = await job_runner.submit("catalog", course.code, {"from": "papers"} if source == "papers" else {})
    return _job_out(job)


@router.post("/{code}/insights/recompute", status_code=202)
async def start_insights(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    job = await job_runner.submit("insights", course.code, {})
    return _job_out(job)


@router.get("/{code}/coverage")
async def get_coverage(code: str, db: AsyncSession = Depends(get_db)):
    return await coverage(db, await _course(db, code))


@router.get("/{code}/sources")
async def get_sources(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    cands = list((await db.execute(select(SourceCandidate).where(SourceCandidate.course_code == course.code)
                                   .order_by(SourceCandidate.id))).scalars())
    docs = list((await db.execute(select(SourceDocument).where(SourceDocument.course_code == course.code)
                                  .order_by(SourceDocument.fetched_at))).scalars())
    return {
        "candidates": [{"id": c.id, "url": c.url, "page_url": c.page_url, "label": c.label, "found_by": c.found_by,
                        "status": c.status, "reason": c.reason, "sha256": c.sha256} for c in cands],
        "documents": [{"sha256": d.sha256, "url": d.url, "origin": d.origin, "label_claimed": d.label_claimed,
                       "bytes": d.bytes, "pages": d.pages, "mime": d.mime, "status": d.status,
                       "identified": {k: v for k, v in (d.identified or {}).items() if k != "page1_raw"},
                       "paper_id": d.paper_id, "fetched_at": d.fetched_at,
                       "file_url": f"/api/courses/{course.code}/documents/{d.sha256}/file"} for d in docs],
    }


@router.get("/{code}/documents/{sha}/file")
async def get_document_file(code: str, sha: str, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import FileResponse

    doc = await db.get(SourceDocument, sha)
    if doc is None or doc.course_code != code.upper():
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(doc.local_path, media_type=doc.mime, filename=f"{code}_{sha[:10]}.{doc.local_path.rsplit('.', 1)[-1]}")


async def _paper_payload(db: AsyncSession, papers: list[Paper]) -> list[dict]:
    pids = [p.paper_id for p in papers]
    qs = list((await db.execute(select(Question).where(Question.paper_id.in_(pids)))).scalars()) if pids else []
    topics: dict[str, list[dict]] = {}
    if qs:
        rows = (await db.execute(select(QuestionTopic).where(QuestionTopic.question_id.in_([q.question_id for q in qs])))).scalars()
        for r in rows:
            topics.setdefault(r.question_id, []).append({"id": r.topic_id, "confidence": r.confidence, "source": r.source})
    docs = list((await db.execute(select(SourceDocument).where(SourceDocument.paper_id.in_(pids)))).scalars()) if pids else []
    out = []
    for p in papers:
        pq = sorted((q for q in qs if q.paper_id == p.paper_id), key=lambda q: (q.number or 0, q.sub or ""))
        out.append({
            "paper_id": p.paper_id, "label": session_label(p.session_month, p.session_year),
            "session_month": p.session_month, "session_year": p.session_year, "exam_title": p.exam_title,
            "cohorts": p.cohorts or [], "qp_code": p.qp_code, "scheme": p.scheme, "total_marks": p.total_marks,
            "extraction_provider": p.extraction_provider, "extraction_model": p.extraction_model,
            "issues": p.issues or [], "needs_review": p.needs_review,
            "sources": [{"sha256": d.sha256, "origin": d.origin, "url": d.url, "label_claimed": d.label_claimed,
                         "primary": d.sha256 == p.primary_sha256,
                         "file_url": f"/api/courses/{p.course_code}/documents/{d.sha256}/file"}
                        for d in docs if d.paper_id == p.paper_id],
            "questions": [{"question_id": q.question_id, "part": q.part, "number": q.number, "sub": q.sub,
                           "module": q.module_no, "marks": q.marks, "marks_inferred": q.marks_inferred, "text": q.text, "options": q.options, "kind": q.kind,
                           "legibility": q.legibility, "has_diagram": q.has_diagram, "needs_review": q.needs_review,
                           "review_reason": q.review_reason,
                           "topics": sorted(topics.get(q.question_id, []), key=lambda t: -t["confidence"])}
                          for q in pq],
        })
    return out


@router.get("/{code}/papers")
async def get_papers(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    papers = list((await db.execute(select(Paper).where(Paper.course_code == course.code))).scalars())
    papers.sort(key=lambda p: ((p.session_year or 0) * 100 + (p.session_month or 0), p.paper_id))
    return {"papers": await _paper_payload(db, papers)}


@router.get("/{code}/insights")
async def get_insights(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    snap = (await db.execute(select(AnalysisSnapshot).where(AnalysisSnapshot.course_code == course.code)
                             .order_by(AnalysisSnapshot.id.desc()).limit(1))).scalars().first()
    if snap is None:
        return {"snapshot": None}
    return {"snapshot": {"id": snap.id, "computed_at": snap.computed_at, **snap.results}}


@router.get("/{code}/review")
async def get_review(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    papers = list((await db.execute(select(Paper).where(Paper.course_code == course.code))).scalars())
    items = []
    for p in papers:
        for i in p.issues or []:
            if i["level"] in ("error", "warn"):
                items.append({"paper_id": p.paper_id, "label": session_label(p.session_month, p.session_year), **i})
    return {"items": items}


def _transcript_from_db(paper: Paper, qs: list[Question]) -> Transcript:
    return Transcript(
        header=TranscriptHeader(course_code=paper.course_code, month=paper.session_month, year=paper.session_year,
                                max_marks=paper.total_marks, qp_code=paper.qp_code, exam_title=paper.exam_title),
        questions=[TranscriptQuestion(part=q.part, number=q.number, sub=q.sub, marks=q.marks, text=q.text,
                                      options=q.options, legibility=q.legibility or "clear")
                   for q in qs if q.number is not None],
    )


@router.patch("/questions/{question_id}")
async def edit_question(question_id: str, body: QuestionEdit, db: AsyncSession = Depends(get_db)):
    q = await db.get(Question, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    paper = await db.get(Paper, q.paper_id)
    course = await db.get(Course, paper.course_code) if paper and paper.course_code else None
    if body.text is not None:
        q.text = body.text.strip()
        q.legibility = "clear"
    if body.options is not None:
        q.options = [o.strip() for o in body.options]
        q.legibility = "clear"
    if body.marks is not None:
        q.marks = body.marks
    if body.kind is not None:
        q.kind = body.kind
    if body.topics is not None and course is not None:
        valid = {t.topic_id for t in (await db.execute(select(CourseTopic).where(
            CourseTopic.course_code == course.code, CourseTopic.module_no == q.module_no))).scalars()}
        bad = [t for t in body.topics if t not in valid]
        if bad:
            raise HTTPException(status_code=422, detail=f"Topics not in module {q.module_no}: {bad}")
        await db.execute(delete(QuestionTopic).where(QuestionTopic.question_id == q.question_id))
        for t in body.topics:
            db.add(QuestionTopic(question_id=q.question_id, topic_id=t, confidence=1.0, source="human"))
    if body.resolved is not None:
        q.needs_review = not body.resolved
        if body.resolved:
            q.review_reason = None
    await db.flush()
    if course is not None:
        template = get_template(course.template_id)
        qs = list((await db.execute(select(Question).where(Question.paper_id == paper.paper_id))).scalars())
        kept = [i for i in (paper.issues or []) if i["code"] in ("B08", "B09", "B10", "B12")]
        fresh = [i.model_dump() for i in validate(template, _transcript_from_db(paper, qs), course.code)]
        paper.issues = fresh + kept
        paper.needs_review = any(i["level"] in ("error", "warn") for i in paper.issues)
    await db.commit()
    return {"question_id": q.question_id, "paper_issues": paper.issues if paper else []}


@router.post("/{code}/upload", status_code=201)
async def upload_documents(code: str, files: list[UploadFile] = File(...), process: bool = True,
                           db: AsyncSession = Depends(get_db)):
    """Upload PDFs/images, ZIP archives or a folder straight into one subject."""
    from app.services.library import store_files

    course = await _course(db, code)
    out = await store_files(db, [(f.filename or "upload", await f.read()) for f in files], course.code)
    job = await job_runner.submit("process", course.code, {"use_agy": True}) if process and out["added"] else None
    return {**{k: out[k] for k in ("added", "duplicates", "skipped")}, "job_id": job.id if job else None}
