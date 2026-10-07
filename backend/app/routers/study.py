"""Practice & lessons router (v2): question bank, mock papers, notes, narrated lessons."""

import random
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.acquisition import SourceDocument
from app.models.catalog import Course, CourseTopic
from app.models.jobs import AnalysisSnapshot
from app.models.paper import Paper, Question, QuestionTopic
from app.models.study import Lesson, MockPaper
from app.services.acquisition.sessions import session_label
from app.services.exam_templates import get_template
from app.services.jobs import job_runner
from app.services.practice import BankQuestion, MockPaperError, assemble

router = APIRouter()


class MockIn(BaseModel):
    focus: str = "likely"  # likely / balanced / fresh
    seed: int | None = None


class LessonIn(BaseModel):
    topic_id: str


class VideoIn(BaseModel):
    voice: str = "Microsoft Zira Desktop"
    rate: int = 0


async def _course(db: AsyncSession, code: str) -> Course:
    c = await db.get(Course, code.upper())
    if c is None:
        raise HTTPException(status_code=404, detail=f"Course {code} not added yet")
    return c


async def _bank(db: AsyncSession, course: Course) -> list[BankQuestion]:
    rows = (await db.execute(select(Question, Paper).join(Paper, Paper.paper_id == Question.paper_id)
                             .where(Paper.course_code == course.code, Question.module_no.is_not(None)))).all()
    topics: dict[str, list[tuple[float, str]]] = {}
    if rows:
        ids = [q.question_id for q, _p in rows]
        for r in (await db.execute(select(QuestionTopic).where(QuestionTopic.question_id.in_(ids)))).scalars():
            topics.setdefault(r.question_id, []).append((r.confidence, r.topic_id))
    return [BankQuestion(q.question_id, p.paper_id, session_label(p.session_month, p.session_year), q.part or "?",
                         q.number or 0, q.sub, q.module_no, q.marks, q.text,
                         [t for _c, t in sorted(topics.get(q.question_id, []), reverse=True)], q.kind,
                         clean=not q.needs_review and (q.legibility or "clear") == "clear", options=q.options)
            for q, p in rows]


@router.get("/{code}/questions")
async def question_bank(code: str, module: int | None = None, topic: str | None = None, kind: str | None = None,
                        part: str | None = None, q: str | None = None, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    bank = await _bank(db, course)
    out = []
    needle = (q or "").lower().strip()
    for b in bank:
        if module and b.module != module or part and b.part != part or kind and b.kind != kind:
            continue
        if topic and topic not in b.topics or needle and needle not in b.text.lower():
            continue
        out.append({"question_id": b.question_id, "paper": b.paper_label, "part": b.part, "number": b.number, "sub": b.sub,
                    "module": b.module, "marks": b.marks, "text": b.text, "options": b.options, "topics": b.topics, "kind": b.kind,
                    "clean": b.clean})
    out.sort(key=lambda x: (x["module"], x["topics"][0] if x["topics"] else "", x["paper"]))
    return {"total": len(out), "questions": out}


@router.post("/{code}/mock-papers", status_code=201)
async def create_mock(code: str, body: MockIn, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    snap = (await db.execute(select(AnalysisSnapshot).where(AnalysisSnapshot.course_code == course.code)
                             .order_by(AnalysisSnapshot.id.desc()).limit(1))).scalars().first()
    probs = {t["topic_id"]: t["probability_next"] for t in (snap.results.get("topics", []) if snap else [])}
    practised = {t for m in (await db.execute(select(MockPaper).where(MockPaper.course_code == course.code))).scalars()
                 for i in m.items for t in i.get("topics", [])}
    seed = body.seed if body.seed is not None else random.randrange(1, 10**6)
    try:
        items = assemble(get_template(course.template_id), course.code, await _bank(db, course), probs,
                         focus=body.focus, seed=seed, practised=practised)
    except MockPaperError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    n = len(list((await db.execute(select(MockPaper.id).where(MockPaper.course_code == course.code))).scalars())) + 1
    mp = MockPaper(course_code=course.code, title=f"Practice paper {n} ({body.focus})", seed=seed,
                   params={"focus": body.focus}, items=items)
    db.add(mp)
    await db.commit()
    await db.refresh(mp)
    return {"id": mp.id, "title": mp.title, "seed": seed, "items": items}


@router.get("/{code}/mock-papers")
async def list_mocks(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    rows = (await db.execute(select(MockPaper).where(MockPaper.course_code == course.code)
                             .order_by(MockPaper.id.desc()))).scalars()
    return {"mock_papers": [{"id": m.id, "title": m.title, "seed": m.seed, "params": m.params, "created_at": m.created_at,
                             "questions": len(m.items)} for m in rows]}


@router.get("/mock-papers/{mock_id}")
async def get_mock(mock_id: int, db: AsyncSession = Depends(get_db)):
    m = await db.get(MockPaper, mock_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Mock paper not found")
    return {"id": m.id, "course_code": m.course_code, "title": m.title, "seed": m.seed, "params": m.params,
            "created_at": m.created_at, "items": m.items}


@router.get("/{code}/notes")
async def list_notes(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    docs = list((await db.execute(select(SourceDocument).where(SourceDocument.course_code == course.code,
                                                               SourceDocument.kind == "notes",
                                                               SourceDocument.status != "rejected"))).scalars())
    return {"notes": [{"sha256": d.sha256, "title": d.title or d.label_claimed, "module": d.module_no, "url": d.url,
                       "origin": d.origin, "pages": d.pages, "bytes": d.bytes,
                       "file_url": f"/api/courses/{course.code}/documents/{d.sha256}/file"}
                      for d in sorted(docs, key=lambda d: (d.module_no or 9, d.title or ""))]}


@router.post("/{code}/notes/fetch", status_code=202)
async def fetch_notes(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    job = await job_runner.submit("notes", course.code, {"use_agy": True})
    return {"job_id": job.id, "status": job.status}


def _lesson_out(l: Lesson) -> dict:
    return {"id": l.id, "course_code": l.course_code, "topic_id": l.topic_id, "status": l.status, "deck": l.deck,
            "video_status": l.video_status, "has_video": bool(l.video_path and Path(l.video_path).exists()),
            "error": l.error, "created_at": l.created_at, "updated_at": l.updated_at}


@router.get("/{code}/lessons")
async def list_lessons(code: str, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    lessons = {l.topic_id: l for l in (await db.execute(select(Lesson).where(Lesson.course_code == course.code)
                                                         .order_by(Lesson.id))).scalars()}
    topics = list((await db.execute(select(CourseTopic).where(CourseTopic.course_code == course.code))).scalars())
    order = {t["id"]: i for i, t in enumerate(t for m in course.catalog_json["modules"] for t in m["topics"])}
    return {"topics": [{"topic_id": t.topic_id, "name": t.name, "module": t.module_no,
                        "lesson": _lesson_out(lessons[t.topic_id]) if t.topic_id in lessons else None}
                       for t in sorted(topics, key=lambda t: order.get(t.topic_id, 999))]}


@router.post("/{code}/lessons", status_code=202)
async def create_lesson(code: str, body: LessonIn, db: AsyncSession = Depends(get_db)):
    course = await _course(db, code)
    if await db.get(CourseTopic, body.topic_id) is None:
        raise HTTPException(status_code=404, detail="Unknown topic")
    lesson = (await db.execute(select(Lesson).where(Lesson.course_code == course.code,
                                                    Lesson.topic_id == body.topic_id))).scalars().first()
    if lesson is None:
        lesson = Lesson(course_code=course.code, topic_id=body.topic_id, status="queued")
        db.add(lesson)
    else:
        lesson.status, lesson.error = "queued", None
    await db.commit()
    await db.refresh(lesson)
    job = await job_runner.submit("lesson", course.code, {"lesson_id": lesson.id})
    return {"lesson_id": lesson.id, "job_id": job.id}


@router.get("/lessons/{lesson_id}")
async def get_lesson(lesson_id: int, db: AsyncSession = Depends(get_db)):
    l = await db.get(Lesson, lesson_id)
    if l is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return _lesson_out(l)


@router.post("/lessons/{lesson_id}/video", status_code=202)
async def render_lesson_video(lesson_id: int, body: VideoIn, db: AsyncSession = Depends(get_db)):
    l = await db.get(Lesson, lesson_id)
    if l is None or not l.deck:
        raise HTTPException(status_code=409, detail="Lesson has no deck yet")
    job = await job_runner.submit("video", l.course_code, {"lesson_id": lesson_id, "voice": body.voice, "rate": body.rate})
    return {"job_id": job.id}


@router.get("/lessons/{lesson_id}/video")
async def lesson_video(lesson_id: int, db: AsyncSession = Depends(get_db)):
    l = await db.get(Lesson, lesson_id)
    if l is None or not l.video_path or not Path(l.video_path).exists():
        raise HTTPException(status_code=404, detail="No video rendered yet")
    return FileResponse(l.video_path, media_type="video/mp4", filename=f"{l.course_code}_{l.topic_id}.mp4")
