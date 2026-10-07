"""
Library: papers gathered without picking a subject first (Home → upload a ZIP/folder, or a wide agy search).

Files land in an inbox (source_documents.course_code NULL). The sort job reads page 1 of each,
finds the subject code printed on the paper and files it under that subject — creating the
subject when it is one of the student's (or when the student uploaded it) — then queues the
subject's processing. Papers for other subjects stay in the library until the student adds them.
"""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.database import async_session_factory
from app.models.acquisition import SourceDocument
from app.models.catalog import Course
from app.models.student import AcademicRecord, CurriculumCourse, StudentProfile
from app.services.academics import semester_from_code
from app.services.acquisition.connectors import FoundLink, dspace_search, links_from_page
from app.services.acquisition.fetcher import sniff, store_bytes
from app.services.agy import AgyError, AgyUnavailable, agy_client
from app.services.catalog import ensure_course, list_catalog
from app.services.catalog_builder import provisional_catalog, save_catalog
from app.services.extraction import local_ocr
from app.services.extraction.ocr_parser import looks_like_exam, parse_pages
from app.services.extraction.pdf import doc_info
from app.services.extraction.pipeline import ocr_first_page, transcript_from_text_layer
from app.services.jobs import JobContext

CODE_RE = re.compile(r"\b([A-Z]{2,3})\s?[-_]?\s?(\d{3})\b")
MAX_MEMBER_BYTES = 40 * 1024 * 1024


def norm_code(raw: str | None) -> str | None:
    m = CODE_RE.search((raw or "").upper())
    return f"{m.group(1)}{m.group(2)}" if m else None


# ───────────────────────────── storing ─────────────────────────────

async def store_files(db, files: list[tuple[str, bytes]], course_code: str | None) -> dict:
    """Store uploaded PDFs/images (ZIPs are opened) once per content hash."""
    out = {"added": 0, "duplicates": 0, "skipped": [], "shas": []}

    async def add(name: str, data: bytes):
        kind = sniff(data[:8])
        if not kind:
            out["skipped"].append(name)
            return
        sha, path = store_bytes(data, kind[1])
        if await db.get(SourceDocument, sha) is not None:
            out["duplicates"] += 1
            return
        pages = doc_info(path).pages if kind[0] == "application/pdf" else 1
        db.add(SourceDocument(sha256=sha, course_code=course_code, url=None, origin="upload", label_claimed=name[:500],
                              local_path=str(path), bytes=len(data), mime=kind[0], pages=pages,
                              status="fetched" if course_code else "inbox", kind="paper"))
        out["added"] += 1
        out["shas"].append(sha)

    for name, data in files:
        if data[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for info in z.infolist():
                        if not info.is_dir() and info.file_size <= MAX_MEMBER_BYTES:
                            await add(f"{name}/{info.filename}", z.read(info))
            except zipfile.BadZipFile:
                out["skipped"].append(name)
        else:
            await add(name, data)
    await db.commit()
    return out


# ───────────────────────────── subjects ─────────────────────────────

async def my_codes(db) -> set[str]:
    """Subjects of the student's degree: their branch curriculum and their grade records."""
    codes = {c for (c,) in (await db.execute(select(CurriculumCourse.code))).all()}
    codes |= {c for (c,) in (await db.execute(select(AcademicRecord.course_code))).all()}
    return {c.upper().replace(" ", "") for c in codes if c}


async def add_subject(db, code: str, title_hint: str | None = None) -> Course:
    """The subject's course row, creating a provisional catalog entry when there is none."""
    existing = await db.get(Course, code)
    if existing is not None:
        return existing
    if code not in {c["code"] for c in list_catalog()}:
        prof = (await db.execute(select(StudentProfile))).scalars().first()
        row = (await db.execute(select(CurriculumCourse).where(CurriculumCourse.code == code))).scalars().first()
        title = row.title if row else (title_hint or "").strip().title() or code
        save_catalog(provisional_catalog(code, title, prof.scheme if prof else "2019",
                                         row.semester if row else semester_from_code(code),
                                         row.credits if row else None, row.slot if row else None))
    return await ensure_course(db, code)


async def assign(db, docs: list[SourceDocument], code: str, title_hint: str | None = None) -> Course:
    course = await add_subject(db, code, title_hint)
    for d in docs:
        d.course_code, d.status = course.code, "fetched"
        d.identified = {**(d.identified or {}), "filed_from_library": True}
    await db.commit()
    return course


# ───────────────────────────── sort job ─────────────────────────────

async def read_code(doc: SourceDocument, ocr_ok: bool) -> dict:
    """Subject code, name and exam session from page 1 (text layer first, local OCR for scans)."""
    path = Path(doc.local_path)
    info = doc_info(path) if doc.mime == "application/pdf" else None
    if info and not info.scanned and info.text_chars > 300:
        header, page1, looks = transcript_from_text_layer(path).header, "", True
    elif ocr_ok:
        run = await ocr_first_page(path, doc.sha256)
        page1 = run.pages[0].raw
        header, looks = parse_pages([page1]).header, looks_like_exam(page1)
    else:
        return {"error": "scanned and local OCR unavailable"}
    code = norm_code(header.course_code)
    how = "header"
    if not code:
        seen = {f"{a}{b}" for a, b in CODE_RE.findall(page1[:3000].upper())}
        if len(seen) == 1:
            code, how = seen.pop(), "page 1"
        else:
            code, how = norm_code(f"{doc.label_claimed or ''} {Path(doc.label_claimed or '').name}"), "file name"
    return {**header.model_dump(), "course_code": code, "code_from": how if code else None, "looks_like_exam": looks}


async def sort_job(ctx: JobContext, params: dict) -> dict:
    """File every inbox document under its subject; queue processing for the subjects that got papers."""
    from app.services.jobs import job_runner

    add_any = bool(params.get("add_any", True))
    ocr_ok, why = await local_ocr.available()
    if not ocr_ok:
        await ctx.warn("sort", f"Local OCR unavailable ({why}); scanned files stay in the inbox")
    out = {"filed": 0, "other_subject": 0, "not_a_paper": 0, "unidentified": 0, "subjects": {}}
    seen: set[str] = set()
    while True:  # uploads that arrive while sorting are picked up too
        async with async_session_factory() as db:
            mine = await my_codes(db)
            docs = [d for d in (await db.execute(select(SourceDocument).where(
                SourceDocument.course_code.is_(None), SourceDocument.status == "inbox"))).scalars() if d.sha256 not in seen]
        if not docs:
            break
        await ctx.info("sort", f"Reading page 1 of {len(docs)} file(s) to find their subjects", progress=5)
        for i, doc in enumerate(docs):
            ctx.check_cancel()
            seen.add(doc.sha256)
            try:
                ident = await read_code(doc, ocr_ok)
            except local_ocr.LocalOcrError as exc:
                ident = {"error": str(exc)}
            async with async_session_factory() as db:
                row = await db.get(SourceDocument, doc.sha256)
                code = ident.get("course_code")
                if ident.get("error"):
                    row.status = "inbox"
                elif not ident.get("looks_like_exam"):
                    row.status, ident["reject_reason"] = "rejected", "not a question paper (notes, cover page or unreadable)"
                    out["not_a_paper"] += 1
                elif not code and (row.pages or 1) > 12:
                    row.status, ident["reject_reason"] = "rejected", f"{row.pages}-page document without a subject code (syllabus or booklet)"
                    out["not_a_paper"] += 1
                elif not code:
                    row.status, ident["reject_reason"] = "unidentified", "no subject code readable on page 1"
                    out["unidentified"] += 1
                elif await db.get(Course, code) is not None or add_any or code in mine:
                    row.identified = ident
                    course = await assign(db, [row], code, ident.get("course_name"))
                    out["filed"] += 1
                    out["subjects"][course.code] = out["subjects"].get(course.code, 0) + 1
                    await ctx.info("sort", f"[{i + 1}/{len(docs)}] {Path(doc.label_claimed or doc.sha256).name[:60]} → {course.code}",
                                   progress=5 + int(85 * (i + 1) / len(docs)))
                    continue
                else:
                    row.status, ident["reject_reason"] = "other_course", f"paper is for {code}"
                    out["other_subject"] += 1
                row.identified = ident
                await db.commit()
            await ctx.info("sort", f"[{i + 1}/{len(docs)}] {Path(doc.label_claimed or doc.sha256).name[:60]} — "
                           f"{ident.get('reject_reason') or ident.get('error') or 'kept'}",
                           progress=5 + int(85 * (i + 1) / len(docs)))
    for code in out["subjects"]:
        await job_runner.submit("process", code, {"use_agy": params.get("use_agy", True)})
    if out["subjects"]:
        await ctx.info("sort", f"Queued reading for {', '.join(out['subjects'])}", progress=100)
    return out


# ───────────────────────────── search job ─────────────────────────────

LIBRARY_SCOUT_PROMPT = """Find downloadable previous-year university question papers.

University: {university_name} ({scheme} scheme)
Search query to run first: {query}
Purpose: {purpose}

Papers of ANY subject are wanted. Run the query with search_web, then up to two close variations
of it. You cannot open pages: report the URLs that appear in the search results (the app opens
listing pages and collects their download links itself). Never construct or guess URLs.

Reply with only this JSON:
{{"candidates": [{{"url": "<direct file link or listing page URL>", "page_url": "<page where you saw it, or null>", "label": "<text shown next to the link, e.g. subject code, exam month/year>", "kind": "pdf" | "drive" | "page"}}]}}
Use kind "page" for listing pages that contain several papers. Return an empty list if nothing relevant was found."""


class _Cand(BaseModel):
    url: str
    page_url: str | None = None
    label: str | None = None
    kind: str = "pdf"


class _Reply(BaseModel):
    candidates: list[_Cand] = Field(default_factory=list)


def library_queries(query: str | None, uni: str, uni_name: str, scheme: str, branch: str | None,
                    semester: int | None) -> list[tuple[str, str]]:
    """(query, purpose) pairs; at least six, so one bad search engine page doesn't decide the result."""
    s = f"S{semester} " if semester else ""
    b = f"{branch} " if branch else ""
    if query:
        q = query.strip()
        base = re.sub(r"\s*(previous year |university )?question papers?\s*$", "", q, flags=re.I) or q
        return [
            (q, "the student's own search"),
            (f"{base} question paper pdf", "direct PDFs"),
            (f"{base} previous year question papers" + ("" if uni.lower() in base.lower() else f" {uni} {scheme} scheme"),
             "previous years"),
            (f"{base} question papers drive.google.com", "shared Drive folders"),
            (f"{base} regular supplementary examination question paper", "all sessions"),
            (f"{base} question paper filetype:pdf", "PDF files only"),
        ]
    return [
        (f"{uni} {scheme} scheme {s}{b}question papers all subjects pdf", "semester collections"),
        (f"{uni} {s}{b}previous year question papers {scheme} scheme download", "branch collections"),
        (f"{uni_name} B.Tech {s}examination question papers repository", "university repositories"),
        (f"{uni} {scheme} scheme {s}question papers google drive folder", "shared drives"),
        (f"{uni} {scheme} scheme {s}regular and supplementary question papers", "all sessions"),
        (f"{uni} {s}{b}{scheme} scheme solved question papers", "solved papers"),
    ]


_NOT_PREFIX = {"KTU", "AND", "THE", "PDF", "FOR", "ALL", "OLD", "NEW", "CSE", "ECE", "EEE", "MCA", "MBA", "QUESTION"}
PROBE_RANGES = [range(101, 110), range(201, 210), range(281, 300), range(301, 400), range(401, 500)]


def code_prefixes(query: str | None) -> list[str]:
    """Bare 3-letter subject-code prefixes in the query ("ADT" in "KTU AI & DS ADT"), not full codes."""
    up = (query or "").upper()
    return [p for p in dict.fromkeys(re.findall(r"\b([A-Z]{3})\b(?!\s?-?\d)", up)) if p not in _NOT_PREFIX]


async def probe_prefix(ctx: JobContext, prefix: str) -> list[FoundLink]:
    """Ask the KTU question-paper DSpace for every code with this prefix (4 requests at a time)."""
    sem = asyncio.Semaphore(4)
    found: list[FoundLink] = []
    hits: set[str] = set()

    async def one(code: str):
        async with sem:
            ctx.check_cancel()
            for base in settings.dspace_sources:
                try:
                    links = await dspace_search(base, [code], code)
                except Exception:  # noqa: BLE001 — one failed lookup must not stop the sweep
                    continue
                links = [l for l in links if code in re.sub(r"\s", "", (l.label or "").upper())]
                if links:
                    hits.add(code)
                    found.extend(links)

    await asyncio.gather(*(one(f"{prefix}{n}") for r in PROBE_RANGES for n in r))
    await ctx.info("connectors", f"DSpace: {len(hits)} {prefix} subject(s) with papers"
                   + (f" — {', '.join(sorted(hits))}" if hits else ""), {"codes": sorted(hits)})
    return found


async def search_job(ctx: JobContext, params: dict) -> dict:
    """Wide agy search (any subject) → download into the library inbox → sort."""
    from app.services.course_pipeline import broad_relevant, persist_and_fetch, workspace
    from app.services.jobs import job_runner

    st = agy_client.status()
    if not st["available"]:
        raise RuntimeError(f"agy web search unavailable: {st['reason']}")
    async with async_session_factory() as db:
        prof = (await db.execute(select(StudentProfile))).scalars().first()
    uni = prof.university if prof else "KTU"
    uni_name = "APJ Abdul Kalam Technological University" if uni == "KTU" else uni
    scheme = prof.scheme if prof else "2019"
    semester = params.get("semester") or (prof.semester if prof else None)
    queries = library_queries(params.get("query"), uni, uni_name, scheme, prof.branch if prof else None, semester)
    await ctx.info("scout", f"Running {len(queries)} agy web searches ({settings.agy_concurrency} at a time)",
                   {"queries": [q for q, _ in queries]}, progress=3)
    ws = workspace(ctx)
    done = 0

    async def one(idx: int, q: str, purpose: str):
        nonlocal done
        prompt = LIBRARY_SCOUT_PROMPT.format(university_name=uni_name, scheme=scheme, query=q, purpose=purpose)
        try:
            reply, _ = await agy_client.run_json(prompt, _Reply, agent="pyq-scout", model=settings.agy_scout_model, cwd=ws,
                                                 fallback_model=settings.agy_fallback_model, on_event=ctx.event_fn("scout"))
            cands = reply.candidates
        except (AgyUnavailable, AgyError) as exc:
            await ctx.warn("scout", f"l{idx + 1}: no usable answer ({exc})")
            cands = []
        done += 1
        await ctx.info("scout", f"l{idx + 1} \"{q}\": {len(cands)} candidate(s)", progress=3 + int(45 * done / len(queries)))
        return idx, cands

    results = await asyncio.gather(*(one(i, q, p) for i, (q, p) in enumerate(queries)))
    found: list[FoundLink] = []
    pages: list[tuple[str, str]] = []
    for idx, cands in results:
        tag = f"agy:l{idx + 1}"
        for c in cands:
            if not c.url.startswith(("http://", "https://")):
                continue
            if c.kind == "page":
                pages.append((c.url, tag))
            else:
                found.append(FoundLink(url=c.url, label=c.label or "", page_url=c.page_url, found_by=tag))
            if c.page_url and c.page_url.startswith("http"):
                pages.append((c.page_url, tag))
    mined: set[str] = set()
    for url, tag in pages:
        if url in mined or len(mined) >= 25:
            continue
        mined.add(url)
        try:
            links = await links_from_page(url, found_by=f"{tag}>page")
            found += links
            if links:
                await ctx.info("scout", f"Mined {len(links)} link(s) from {urlparse(url).netloc}")
        except Exception as exc:  # noqa: BLE001
            await ctx.warn("scout", f"Could not open {url}: {type(exc).__name__}")
    for prefix in code_prefixes(params.get("query")):
        await ctx.info("connectors", f"Checking the KTU question-paper repository for every {prefix} code", progress=48)
        found += await probe_prefix(ctx, prefix)
    ctx.check_cancel()
    by_source: dict[str, int] = defaultdict(int)
    stats, new_shas, unique = await persist_and_fetch(ctx, found, kind="paper", relevance=broad_relevant,
                                                      by_source=by_source, progress=(50, 95))
    sort = None
    if new_shas:
        sort = await job_runner.submit("library_sort", None, {"add_any": False})
        await ctx.info("sort", f"{len(new_shas)} new file(s) in the library; sorting them by subject", progress=100)
    return {"agy_queries": len(queries), "links_found": len(found), "unique": unique, **stats,
            "sort_job": sort.id if sort else None}
