"""Course catalog: definitions shipped as JSON under app/catalog/<university>/<code>.json."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Course, CourseModule, CourseTopic

CATALOG_DIR = Path(__file__).resolve().parent.parent / "catalog"


def list_catalog() -> list[dict]:
    out = []
    for path in sorted(CATALOG_DIR.glob("*/*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        out.append({
            "code": d["code"], "university": d["university"], "scheme": d["scheme"], "title": d["title"],
            "semester": d.get("semester"), "modules": len(d["modules"]),
            "topics": sum(len(m["topics"]) for m in d["modules"]),
        })
    return out


def load_catalog(code: str) -> dict:
    for path in CATALOG_DIR.glob("*/*.json"):
        d = json.loads(path.read_text(encoding="utf-8"))
        if d["code"].upper() == code.upper():
            return d
    raise KeyError(code)


async def ensure_course(db: AsyncSession, code: str) -> Course:
    """Create or refresh a course (and its modules/topics) from its catalog definition."""
    d = load_catalog(code)
    course = await db.get(Course, d["code"])
    if course is None:
        course = Course(code=d["code"], university=d["university"], scheme=d["scheme"], title=d["title"],
                        semester=d.get("semester"), slot=d.get("slot"), credits=d.get("credits"),
                        template_id=d["template_id"], catalog_json=d)
        db.add(course)
    else:
        course.title, course.catalog_json, course.template_id = d["title"], d, d["template_id"]
    await db.flush()

    existing_modules = {m.module_no: m for m in (await db.execute(
        select(CourseModule).where(CourseModule.course_code == d["code"]))).scalars()}
    existing_topics = {t.topic_id: t for t in (await db.execute(
        select(CourseTopic).where(CourseTopic.course_code == d["code"]))).scalars()}
    wanted = {t["id"] for m in d["modules"] for t in m["topics"]}
    for tid, row in existing_topics.items():
        if tid not in wanted:  # catalog changed (e.g. provisional → syllabus): its tags go too
            await db.delete(row)
    for m in d["modules"]:
        if m["no"] in existing_modules:
            existing_modules[m["no"]].title = m["title"]
        else:
            db.add(CourseModule(course_code=d["code"], module_no=m["no"], title=m["title"]))
        for t in m["topics"]:
            row = existing_topics.get(t["id"])
            if row is None:
                db.add(CourseTopic(topic_id=t["id"], course_code=d["code"], module_no=m["no"], name=t["name"],
                                   description=t.get("description", ""), keywords=t.get("keywords", [])))
            else:
                row.name, row.module_no, row.keywords = t["name"], m["no"], t.get("keywords", [])
    await db.commit()
    return course
