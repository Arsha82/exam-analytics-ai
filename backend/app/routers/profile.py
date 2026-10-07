"""
Profile & academics router (v2): branch/semester, official curriculum, grade-card import,
SGPA/CGPA/backlogs, and "add my subjects" (which auto-creates courses and starts the
papers + notes pipeline). No KTU credentials are ever requested or stored.
"""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.catalog import Course
from app.models.paper import Paper
from app.models.student import AcademicRecord, CurriculumCourse, StudentProfile
from app.services import curriculum as curriculum_svc
from app.services.academics import (
    FAIL, GRADE_POINTS, Attempt, label_for, needed_sgpa, normalize_grade, parse_grade_card, semester_from_code, summarize,
)
from app.services.acquisition.fetcher import Fetched, fetch, sniff, store_bytes
from app.services.acquisition.sessions import parse_session, session_key
from app.services.catalog import ensure_course, list_catalog
from app.services.catalog_builder import provisional_catalog, save_catalog
from app.services.extraction.ocr_parser import parse_blocks
from app.services.extraction.pdf import doc_info, text_layer
from app.services.jobs import job_runner

router = APIRouter()


class ProfileIn(BaseModel):
    branch: str | None = None
    semester: int | None = None
    target_cgpa: float | None = None


class RecordIn(BaseModel):
    course_code: str
    grade: str
    title: str | None = None
    semester: int | None = None
    credits: float | None = None
    session_label: str | None = None


class RecordsIn(BaseModel):
    records: list[RecordIn]
    source: str = "manual"
    source_sha: str | None = None
    replace_same_session: bool = True


class AddSubjects(BaseModel):
    codes: list[str]
    auto: bool = True


async def _profile(db: AsyncSession) -> StudentProfile:
    p = await db.get(StudentProfile, 1)
    if p is None:
        p = StudentProfile(id=1)
        db.add(p)
        await db.flush()
    return p


async def _ensure_curriculum(db: AsyncSession, branch: str) -> list[CurriculumCourse]:
    rows = list((await db.execute(select(CurriculumCourse).where(CurriculumCourse.branch == branch))).scalars())
    if rows:
        return rows
    sources = {s.branch: s for s in await curriculum_svc.discover()}
    src = sources.get(branch)
    if src is None:
        return []
    res = await fetch(src.url)
    if not isinstance(res, Fetched):
        return []
    for r in curriculum_svc.parse_file(res.path):
        db.add(CurriculumCourse(scheme="2019", branch=branch, semester=r.semester, slot=r.slot, code=r.code,
                                title=r.title, ltp=r.ltp, credits=r.credits, source_sha=res.sha256))
    await db.commit()
    return list((await db.execute(select(CurriculumCourse).where(CurriculumCourse.branch == branch))).scalars())


@router.get("")
async def get_profile(db: AsyncSession = Depends(get_db)):
    p = await _profile(db)
    branches = [b for (b,) in (await db.execute(select(CurriculumCourse.branch).distinct())).all()]
    return {"university": p.university, "scheme": p.scheme, "branch": p.branch, "semester": p.semester,
            "target_cgpa": p.target_cgpa, "curriculum_branches": sorted(branches),
            "known_branches": ["CE", "CSE", "ECE", "EEE", "ME", "MR"]}


@router.put("")
async def put_profile(body: ProfileIn, db: AsyncSession = Depends(get_db)):
    p = await _profile(db)
    if body.branch is not None:
        p.branch = body.branch.upper()
    if body.semester is not None:
        p.semester = body.semester
    if body.target_cgpa is not None:
        p.target_cgpa = body.target_cgpa
    await db.commit()
    if p.branch:
        await _ensure_curriculum(db, p.branch)
    return await get_profile(db)


@router.get("/curriculum")
async def get_curriculum(branch: str, db: AsyncSession = Depends(get_db)):
    rows = await _ensure_curriculum(db, branch.upper())
    if not rows:
        raise HTTPException(status_code=404, detail=f"No 2019-scheme curriculum found for {branch}")
    return {"branch": branch.upper(), "courses": [
        {"semester": r.semester, "slot": r.slot, "code": r.code, "title": r.title, "ltp": r.ltp, "credits": r.credits}
        for r in sorted(rows, key=lambda r: (r.semester, r.slot or "Z", r.code))]}


def _is_theory(code: str, ltp: str | None) -> bool:
    """Courses with a written theory exam (labs/projects/mandatory non-credit excluded)."""
    if len(code) >= 3 and code[2] == "L":  # CEL201, CSL201 ... labs
        return False
    if code.startswith(("MCN", "MCC")):  # mandatory non-credit courses
        return False
    return not (ltp or "").startswith("0-")


async def _course_status(db: AsyncSession, code: str) -> dict:
    course = await db.get(Course, code)
    if course is None:
        return {"added": False}
    papers = (await db.execute(select(func.count()).select_from(Paper).where(Paper.course_code == code))).scalar() or 0
    return {"added": True, "papers": papers, "provisional": bool(course.catalog_json.get("provisional"))}


@router.get("/subjects")
async def get_subjects(db: AsyncSession = Depends(get_db)):
    p = await _profile(db)
    current, backlogs = [], []
    if p.branch and p.semester:
        rows = await _ensure_curriculum(db, p.branch)
        for r in sorted((r for r in rows if r.semester == p.semester), key=lambda r: (r.slot or "Z", r.code)):
            current.append({"code": r.code, "title": r.title, "credits": r.credits, "slot": r.slot,
                            "theory": _is_theory(r.code, r.ltp), **await _course_status(db, r.code)})
    summary = await _summary(db, p)
    for b in summary["backlogs"]:
        backlogs.append({**b, **await _course_status(db, b["course_code"])})
    catalog = {c["code"] for c in list_catalog()}
    return {"semester": p.semester, "branch": p.branch, "current": current, "backlogs": backlogs,
            "catalog_codes": sorted(catalog)}


@router.post("/subjects/add", status_code=202)
async def add_subjects(body: AddSubjects, db: AsyncSession = Depends(get_db)):
    p = await _profile(db)
    catalog = {c["code"] for c in list_catalog()}
    started = []
    for raw in body.codes:
        code = raw.upper().replace(" ", "")
        if code not in catalog:
            row = (await db.execute(select(CurriculumCourse).where(CurriculumCourse.code == code))).scalars().first()
            rec = (await db.execute(select(AcademicRecord).where(AcademicRecord.course_code == code))).scalars().first()
            title = row.title if row else (rec.title if rec and rec.title else code)
            save_catalog(provisional_catalog(code, title, p.scheme, row.semester if row else semester_from_code(code),
                                             row.credits if row else None, row.slot if row else None))
        course = await ensure_course(db, code)
        if body.auto:
            kind = "setup" if course.catalog_json.get("provisional") else "auto"
            job = await job_runner.submit(kind, code, {"use_agy": True})
            started.append({"code": code, "job_id": job.id, "kind": kind})
        else:
            started.append({"code": code, "job_id": None, "kind": None})
    return {"started": started}


# ── grade card import ──

def _ocr_text(raw: str) -> str:
    return "\n".join(b.text for b in parse_blocks(raw, 0))


@router.post("/grade-card")
async def import_grade_card(file: UploadFile = File(...)):
    """Parse a grade card / result the student downloaded; returns rows to review (not saved)."""
    data = await file.read()
    kind = sniff(data[:8])
    if not kind:
        raise HTTPException(status_code=415, detail="Upload a PDF or an image (PNG/JPEG) of the grade card")
    sha, path = store_bytes(data, kind[1])
    text = ""
    if kind[0] == "application/pdf":
        info = doc_info(path)
        if not info.scanned and info.text_chars > 100:
            text = "\n".join(text_layer(path))
    if not text.strip():
        from app.services.extraction.pipeline import ocr_document

        try:
            run = await ocr_document(path, sha)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"Could not read the scan: {exc}")
        text = "\n".join(_ocr_text(pg.raw) for pg in run.pages)
    parsed = parse_grade_card(text)
    return {"source_sha": sha, "session": label_for(parsed.session),
            "records": [{"course_code": r.course_code, "title": r.title, "grade": r.grade, "credits": r.credits,
                         "semester": semester_from_code(r.course_code)} for r in parsed.records],
            "text_chars": len(text)}


@router.post("/records")
async def save_records(body: RecordsIn, db: AsyncSession = Depends(get_db)):
    saved = 0
    for r in body.records:
        grade = normalize_grade(r.grade)
        if grade is None:
            raise HTTPException(status_code=422, detail=f"Unknown grade '{r.grade}' for {r.course_code}")
        code = r.course_code.upper().replace(" ", "")
        if body.replace_same_session and r.session_label:
            await db.execute(delete(AcademicRecord).where(AcademicRecord.course_code == code,
                                                          AcademicRecord.session_label == r.session_label))
        db.add(AcademicRecord(course_code=code, title=r.title, semester=r.semester, credits=r.credits, grade=grade,
                              session_label=r.session_label, source=body.source, source_sha=body.source_sha))
        saved += 1
    await db.commit()
    return {"saved": saved}


@router.delete("/records/{record_id}", status_code=204)
async def delete_record(record_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(AcademicRecord, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(row)
    await db.commit()


async def _summary(db: AsyncSession, p: StudentProfile) -> dict:
    records = list((await db.execute(select(AcademicRecord))).scalars())
    curriculum = {}
    if p.branch:
        for r in (await db.execute(select(CurriculumCourse).where(CurriculumCourse.branch == p.branch))).scalars():
            curriculum.setdefault(r.code, r)
    attempts = []
    for r in records:
        cur = curriculum.get(r.course_code)
        credits = r.credits if r.credits is not None else (cur.credits if cur and cur.credits else None)
        if credits is None:
            continue  # non-credit course or unknown credits: not part of SGPA/CGPA
        sess = parse_session(r.session_label or "")
        attempts.append(Attempt(r.course_code, r.grade, credits,
                                r.semester or (cur.semester if cur else None) or semester_from_code(r.course_code),
                                session_key(*sess) if sess else 0, r.title or (cur.title if cur else None)))
    out = summarize(attempts)
    out["records"] = [{"id": r.id, "course_code": r.course_code, "title": r.title, "grade": r.grade, "semester": r.semester,
                       "credits": r.credits, "session_label": r.session_label, "source": r.source,
                       "failed": r.grade in FAIL} for r in sorted(records, key=lambda r: (r.semester or 0, r.course_code))]
    out["grade_points"] = GRADE_POINTS
    if p.target_cgpa and p.semester:
        nxt = [r for r in curriculum.values() if r.semester == p.semester and r.credits]
        out["target"] = {"target_cgpa": p.target_cgpa, "next_semester": p.semester,
                         "next_credits": sum(r.credits for r in nxt),
                         "needed_sgpa": needed_sgpa(out["cgpa"], out["credits_registered"], sum(r.credits for r in nxt), p.target_cgpa)}
    return out


@router.get("/academics")
async def get_academics(db: AsyncSession = Depends(get_db)):
    return await _summary(db, await _profile(db))
