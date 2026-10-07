"""
Course jobs (v2): acquire → process → insights.

acquire  connectors (DSpace, known pages) + ≥8 agy web searches → candidates →
         relevance filter → download (hash-deduped) → source_documents
process  identify (page-1 OCR) → reject other courses → group duplicate scans by QP code →
         transcribe one scan per QP (local OCR) → validate → fill flagged slots from the
         duplicate scan → agy repair for what is still flagged → papers/questions →
         topic tagging → insights snapshot
insights recompute statistics + backtest from the DB
"""

import asyncio
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.models.acquisition import SourceCandidate, SourceDocument
from app.models.catalog import Course, CourseModule, CourseTopic
from app.models.jobs import AnalysisSnapshot
from app.models.paper import Paper, Question, QuestionTopic
from app.services.acquisition.connectors import (
    FoundLink,
    canonical_url,
    dspace_search,
    extract_links,
    links_from_page,
)
from app.services.acquisition.fetcher import FetchError, Fetched, FetchedPage, fetch
from app.services.acquisition.planner import SCOUT_PROMPT, broad_queries, plan_queries
from app.services.acquisition.sessions import MONTHS, expected_windows, parse_session, session_key, session_label
from app.services.agy import AgyError, AgyUnavailable, agy_client
from app.services.backtest import run_backtest
from app.services.catalog import ensure_course
from app.services.exam_templates import flagged_slots, get_template, repair_order
from app.services.extraction import local_ocr
from app.services.extraction.ocr_parser import looks_like_exam, parse_pages
from app.services.extraction.pdf import doc_info, text_layer
from app.services.extraction.pipeline import (
    finalize,
    looped_pages,
    pages_for_slots,
    reread_pages,
    merge_slots,
    ocr_document,
    ocr_first_page,
    repair_with_agy,
    transcript_from_run,
    transcript_from_text_layer,
)
from app.services.insights import PaperRow, QRow, TopicDef, compute, jaccard, _tokens
from app.services.jobs import JobContext
from app.services.notes import NOTES_PROMPT, NOTES_QUERIES, module_for_link, module_from_text, notes_relevant, notes_text_path
from app.services.tagging import TagItem, tag_module
from app.services.transcript import Issue, TranscriptHeader

_NOT_A_PAPER = re.compile(r"\b(notes?|module[\s-]*\d|syllabus|textbook|lab manual|tutorial|ppt|slides?|assignment)\b", re.I)
_PAPER_HINT = re.compile(r"\b(question|qp|paper|exam|examination|regular|supplementary|model)\b", re.I)
_MONTH_YEAR = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,.-]*(19|20)\d{2}\b", re.I)


class _ScoutCandidate(BaseModel):
    url: str
    page_url: str | None = None
    label: str | None = None
    kind: str = "pdf"


class _ScoutReply(BaseModel):
    candidates: list[_ScoutCandidate] = Field(default_factory=list)


_ANY_CODE = re.compile(r"\b([A-Z]{2,3})\s?[-_]?\s?(\d{3})\b")


def is_relevant(link: FoundLink, course: dict) -> tuple[bool, str]:
    """
    Keep a link only if it is about this course. On listing pages the label window also
    holds neighbouring links, so the decision uses the link's own text (anchor + nearby
    words + file name): it must name this course's code, and must not name another code.
    """
    own = f"{link.near or link.label or ''} {link.url.rsplit('/', 1)[-1]}"
    text = f"{link.label or ''} {link.url}"
    codes = {c.replace(" ", "").upper() for c in course.get("code_variants", [course["code"]])}
    compact_own = re.sub(r"(?:%20|[\s_\-])+", "", own).upper()
    has_code = any(c in compact_own for c in codes)
    other = sorted({f"{a}{b}" for a, b in _ANY_CODE.findall(own.upper())} - codes)
    has_session = bool(_MONTH_YEAR.search(own))
    if _NOT_A_PAPER.search(link.near or link.label or "") and not has_session:
        return False, "looks like notes/syllabus, not a question paper"
    if link.found_by.startswith(("dspace:", "page:")):
        return True, ""
    if other and not has_code:
        return False, f"about another course ({', '.join(other[:3])})"
    if ">page" in link.found_by:  # mined from a listing page: the code itself must be there
        return (True, "") if has_code else (False, "listing-page link without this course's code")
    if has_code or (has_session and _PAPER_HINT.search(text)):
        return True, ""
    return False, "no course code (or session + paper hint) in the link's own text"


def broad_relevant(link: FoundLink) -> tuple[bool, str]:
    """
    Broad mode: any subject, but the link's own text (or file name) must look like an exam paper —
    a subject code, an exam month/year, or paper/exam words. College sites link plenty of other PDFs.
    """
    own = f"{link.near or link.label or ''} {link.url.rsplit('/', 1)[-1]}"
    if _NOT_A_PAPER.search(link.near or link.label or "") and not _MONTH_YEAR.search(own):
        return False, "looks like notes/syllabus, not a question paper"
    if _ANY_CODE.search(own.upper()) or _MONTH_YEAR.search(own) or _PAPER_HINT.search(own):
        return True, ""
    if "drive.google" in link.url and not link.found_by.endswith(">page"):
        return True, ""  # a search hit straight to a Drive file: its name is only known after download
    return False, "nothing in the link says question paper (no code, session or exam words)"


def workspace(ctx: JobContext) -> Path:
    d = settings.storage_dir / "jobs" / ctx.job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ───────────────────────────── acquire ─────────────────────────────

async def acquire_job(ctx: JobContext, params: dict) -> dict:
    use_agy = params.get("use_agy", True)
    async with async_session_factory() as db:
        course = await ensure_course(db, ctx.course_code)
        cdef = course.catalog_json
        known_sessions = {(p.session_month, p.session_year) for p in (await db.execute(
            select(Paper).where(Paper.course_code == course.code))).scalars() if p.session_month and p.session_year}
    found: list[FoundLink] = []
    by_source: dict[str, int] = defaultdict(int)

    await ctx.info("connectors", "Querying known sources (no LLM)", progress=3)
    for base in dict.fromkeys(cdef.get("sources", {}).get("dspace", []) + list(settings.dspace_sources)):
        try:
            links = await dspace_search(base, cdef.get("code_variants", [cdef["code"]]), cdef["code"])
            found += links
            await ctx.info("connectors", f"DSpace {urlparse(base).netloc}: {len(links)} file(s)")
        except Exception as exc:  # noqa: BLE001
            await ctx.warn("connectors", f"DSpace {base} failed: {exc}")
    for page in cdef.get("sources", {}).get("pages", []):
        try:
            links = await links_from_page(page, found_by=f"page:{urlparse(page).netloc}")
            found += links
            await ctx.info("connectors", f"Page {urlparse(page).netloc}: {len(links)} link(s)")
        except Exception as exc:  # noqa: BLE001
            await ctx.warn("connectors", f"Page {page} failed: {exc}")
    ctx.check_cancel()

    # Sessions still missing after the free connectors → targeted gap searches.
    known_sessions |= {s for s in (parse_session(l.label) for l in found) if s}
    first = cdef.get("first_exam") or {"year": 2020, "month": 12}
    missing = [w.label for w in expected_windows(first["year"], first["month"])
               if not any(w.contains(m, y) for m, y in known_sessions)]
    await ctx.info("connectors", f"{len(found)} link(s) from known sources; sessions still missing: {len(missing)}",
                   {"missing": missing})

    mined_pages: set[str] = set(cdef.get("sources", {}).get("pages", []))
    queries_run = 0
    if use_agy:
        st = agy_client.status()
        if not st["available"]:
            await ctx.warn("scout", f"agy web search skipped: {st['reason']}")
        else:
            queries = plan_queries(cdef, missing, settings.acquire_min_queries, settings.acquire_max_queries)
            if params.get("broad"):
                queries = queries[:6] + broad_queries(cdef)
            await ctx.info("scout", f"Running {len(queries)} agy web searches ({settings.agy_concurrency} at a time)",
                           {"queries": [q.text for q in queries]}, progress=10)
            ws = workspace(ctx)
            done = 0

            async def one(q):
                nonlocal done
                prompt = SCOUT_PROMPT.format(code=cdef["code"], title=cdef["title"],
                                             university_name=cdef.get("university_name", cdef["university"]),
                                             scheme=cdef["scheme"], query=q.text,
                                             purpose=q.purpose + (" — papers of ANY course of this university and scheme are"
                                                                  " wanted, not only the course above" if q.id.startswith("b") else ""))
                try:
                    reply, _ = await agy_client.run_json(
                        prompt, _ScoutReply, agent="pyq-scout", model=settings.agy_scout_model, cwd=ws,
                        fallback_model=settings.agy_fallback_model, on_event=ctx.event_fn("scout"))
                    cands = reply.candidates
                except AgyUnavailable as exc:
                    await ctx.warn("scout", f"{q.id}: agy unavailable ({exc})")
                    cands = []
                except AgyError as exc:
                    await ctx.warn("scout", f"{q.id}: no usable answer ({exc})")
                    cands = []
                done += 1
                await ctx.info("scout", f"{q.id} \"{q.text}\": {len(cands)} candidate(s)", progress=10 + int(40 * done / len(queries)))
                return q, cands

            results = await asyncio.gather(*(one(q) for q in queries))
            queries_run = len(queries)
            pages_to_mine: list[tuple[str, str]] = []
            for q, cands in results:
                for c in cands:
                    if not c.url.startswith(("http://", "https://")):
                        continue
                    if c.kind == "page":
                        pages_to_mine.append((c.url, f"agy:{q.id}"))
                    else:
                        found.append(FoundLink(url=c.url, label=c.label or "", page_url=c.page_url, found_by=f"agy:{q.id}"))
                    if c.page_url and c.page_url.startswith("http"):
                        pages_to_mine.append((c.page_url, f"agy:{q.id}"))
            for url, origin in pages_to_mine:
                if url in mined_pages or len(mined_pages) > 20:
                    continue
                mined_pages.add(url)
                try:
                    links = await links_from_page(url, found_by=f"{origin}>page")
                    found += links
                    if links:
                        await ctx.info("scout", f"Mined {len(links)} link(s) from {urlparse(url).netloc}")
                except Exception as exc:  # noqa: BLE001
                    await ctx.warn("scout", f"Could not open {url}: {type(exc).__name__}")
    ctx.check_cancel()

    stats, new_shas, unique_count = await persist_and_fetch(
        ctx, found, kind="paper",
        relevance=(lambda link: broad_relevant(link)) if params.get("broad") else (lambda link: is_relevant(link, cdef)),
        by_source=by_source,
        progress=(55, 95))
    return {"links_found": len(found), "unique": unique_count, "agy_queries": queries_run, **stats,
            "by_source": dict(by_source)}


async def persist_and_fetch(ctx: JobContext, found: list[FoundLink], kind: str, relevance, by_source: dict,
                            progress: tuple[int, int]) -> tuple[dict, list[str], int]:
    """Dedupe links, apply the relevance filter, record candidates, download the new ones."""
    lo, hi = progress
    unique: dict[str, FoundLink] = {}
    for link in found:
        unique.setdefault(canonical_url(link.url), link)
    await ctx.info("fetch", f"{len(found)} links found, {len(unique)} unique", progress=lo)

    async with async_session_factory() as db:
        known = {canonical_url(c.url): c for c in (await db.execute(
            select(SourceCandidate).where(SourceCandidate.course_code.is_(None) if ctx.course_code is None
                                          else SourceCandidate.course_code == ctx.course_code,
                                          SourceCandidate.kind == kind))).scalars()}
        to_fetch: list[SourceCandidate] = []
        for key, link in unique.items():
            ok, why = relevance(link)
            prev = known.get(key)
            if prev is not None and prev.status in ("fetched", "duplicate", "skipped"):
                continue
            cand = prev or SourceCandidate(course_code=ctx.course_code, url=link.url, page_url=link.page_url,
                                           label=link.label[:500] if link.label else None, found_by=link.found_by,
                                           job_id=ctx.job_id, kind=kind)
            if prev is None:
                db.add(cand)
            if not ok:
                cand.status, cand.reason = "skipped", why
            else:
                cand.status = "new"
                to_fetch.append(cand)
            by_source[link.found_by.split(">")[0]] += 1
        await db.commit()
        cand_ids = [c.id for c in to_fetch]

    sem = asyncio.Semaphore(4)
    stats = {"fetched": 0, "duplicate": 0, "failed": 0, "pages_mined": 0}
    new_shas: list[str] = []
    done = 0

    async def fetch_one(cid: int):
        nonlocal done
        async with sem:
            async with async_session_factory() as db:
                cand = await db.get(SourceCandidate, cid)
                try:
                    res = await fetch(cand.url)
                    if isinstance(res, FetchedPage):
                        links = extract_links(res.html, res.final_url, found_by=f"{cand.found_by}>page")
                        cand.status, cand.reason = "skipped", f"HTML page ({len(links)} file links; not followed further)"
                        stats["pages_mined"] += 1
                    else:
                        cand.sha256 = res.sha256
                        existing = await db.get(SourceDocument, res.sha256)
                        if existing is not None:
                            cand.status, cand.reason = "duplicate", f"identical file already stored (from {existing.origin})"
                            stats["duplicate"] += 1
                        else:
                            info = doc_info(res.path) if res.mime == "application/pdf" else None
                            db.add(SourceDocument(
                                sha256=res.sha256, course_code=ctx.course_code, url=cand.url, origin=cand.found_by,
                                label_claimed=cand.label, local_path=str(res.path), bytes=res.bytes, mime=res.mime,
                                pages=info.pages if info else 1, status="inbox" if ctx.course_code is None else "fetched",
                                kind=kind))
                            cand.status = "fetched"
                            stats["fetched"] += 1
                            new_shas.append(res.sha256)
                except (FetchError, httpx.HTTPError, OSError) as exc:
                    cand.status, cand.reason = "failed", f"{type(exc).__name__}: {exc}"[:400]
                    stats["failed"] += 1
                await db.commit()
                done += 1
                await ctx.info("fetch", f"[{done}/{len(cand_ids)}] {cand.status}: {cand.label or cand.url}"[:300],
                               progress=lo + int((hi - lo) * done / max(1, len(cand_ids))))
            ctx.check_cancel()

    await asyncio.gather(*(fetch_one(cid) for cid in cand_ids))
    return stats, new_shas, len(unique)


# ───────────────────────────── notes ─────────────────────────────

async def notes_job(ctx: JobContext, params: dict) -> dict:
    """Find module-wise notes with agy searches + page mining; download; detect modules; keep text."""
    async with async_session_factory() as db:
        course = await ensure_course(db, ctx.course_code)
        cdef = course.catalog_json
    codes = cdef.get("code_variants", [cdef["code"]])
    found: list[FoundLink] = []
    queries_run = 0
    st = agy_client.status()
    if not params.get("use_agy", True) or not st["available"]:
        await ctx.warn("scout", f"agy web search skipped: {st['reason'] or 'disabled for this run'}")
    else:
        qs = NOTES_QUERIES[: max(1, int(params.get("queries", settings.notes_queries)))]
        modules = "\n".join(f"- Module {m['no']}: {m['title']}" for m in cdef["modules"])
        ws = workspace(ctx)
        await ctx.info("scout", f"Running {len(qs)} agy searches for notes ({settings.agy_concurrency} at a time)", progress=5)

        async def one(qid: str, tmpl: str, purpose: str):
            query = tmpl.format(code=cdef["code"], title=cdef["title"], scheme=cdef["scheme"])
            prompt = NOTES_PROMPT.format(code=cdef["code"], title=cdef["title"], scheme=cdef["scheme"],
                                         university_name=cdef.get("university_name", cdef["university"]),
                                         modules=modules, query=query, purpose=purpose)
            try:
                reply, _ = await agy_client.run_json(prompt, _ScoutReply, agent="pyq-scout", model=settings.agy_scout_model,
                                                     cwd=ws, fallback_model=settings.agy_fallback_model,
                                                     on_event=ctx.event_fn("scout"))
                cands = reply.candidates
            except (AgyError, AgyUnavailable) as exc:
                await ctx.warn("scout", f"{qid}: {exc}")
                cands = []
            await ctx.info("scout", f"{qid} \"{query}\": {len(cands)} candidate(s)")
            return qid, cands

        results = await asyncio.gather(*(one(*q) for q in qs))
        queries_run = len(qs)
        pages: list[tuple[str, str]] = []
        for qid, cands in results:
            for c in cands:
                if not c.url.startswith(("http://", "https://")):
                    continue
                if c.kind == "page":
                    pages.append((c.url, f"agy:{qid}"))
                else:
                    found.append(FoundLink(url=c.url, label=c.label or "", page_url=c.page_url, found_by=f"agy:{qid}"))
        mined: set[str] = set()
        for url, origin in pages:
            if url in mined or len(mined) >= 15:
                continue
            mined.add(url)
            try:
                found += await links_from_page(url, found_by=f"{origin}>page")
            except Exception as exc:  # noqa: BLE001
                await ctx.warn("scout", f"Could not open {urlparse(url).netloc}: {type(exc).__name__}")
    ctx.check_cancel()

    by_source: dict[str, int] = defaultdict(int)
    stats, new_shas, unique_count = await persist_and_fetch(
        ctx, found, kind="notes", relevance=lambda link: notes_relevant(link.label or "", link.url, codes),
        by_source=by_source, progress=(55, 90))

    # Module detection + text extraction for new notes.
    per_module: dict[str, int] = defaultdict(int)
    async with async_session_factory() as db:
        for sha in new_shas:
            doc = await db.get(SourceDocument, sha)
            module = module_for_link(doc.label_claimed, doc.url)
            text = ""
            if doc.mime == "application/pdf":
                try:
                    text = "\n".join(text_layer(Path(doc.local_path))[:40])
                except Exception:  # noqa: BLE001 — unreadable PDF: keep the file, skip the text
                    text = ""
                if text.strip():
                    notes_text_path(sha).write_text(text, encoding="utf-8")
            module = module or module_from_text(text[:4000])
            doc.module_no = module
            doc.title = re.sub(r"\s+", " ", (doc.label_claimed or Path(doc.url or "").name))[:200]
            doc.status = "identified"
            per_module[str(module) if module else "unknown"] += 1
        await db.commit()
    await ctx.info("notes", f"Notes by module: {dict(per_module)}", progress=98)
    return {"agy_queries": queries_run, "unique": unique_count, **stats, "by_module": dict(per_module)}


# ───────────────────────────── catalog (any course) ─────────────────────────────

async def catalog_job(ctx: JobContext, params: dict) -> dict:
    """Replace a provisional course definition with one built from the syllabus (or past papers)."""
    from app.services.catalog_builder import (
        apply_taxonomy, find_syllabus, save_catalog, structure_syllabus, taxonomy_from_questions,
    )

    async with async_session_factory() as db:
        course = await db.get(Course, ctx.course_code)
        cdef = dict(course.catalog_json)
    if not cdef.get("provisional") and not params.get("force"):
        return {"status": "kept", "reason": "course already has a syllabus-based catalog"}
    ws = workspace(ctx)
    how, new = None, None
    if params.get("from") != "papers":
        await ctx.info("syllabus", f"Looking for the official {cdef['code']} syllabus", progress=5)
        section, src, files = await find_syllabus(agy_client, cdef, ws, on_event=ctx.event_fn("syllabus"))
        await ctx.info("syllabus", f"Checked {len(files)} PDF(s); course section {'found' if section else 'not found'}"
                       + (f" in {src}" if src else ""), progress=40)
        if section:
            try:
                modules = await structure_syllabus(agy_client, cdef, section, ws, on_event=ctx.event_fn("syllabus"))
                new, how = apply_taxonomy(cdef, modules, src or "syllabus PDF"), "syllabus"
            except (AgyError, AgyUnavailable, ValueError) as exc:
                await ctx.warn("syllabus", f"Could not structure the syllabus: {exc}")
    if new is None:
        async with async_session_factory() as db:
            qs = list((await db.execute(select(Question).join(Paper, Paper.paper_id == Question.paper_id)
                                        .where(Paper.course_code == ctx.course_code, Question.module_no.is_not(None)))).scalars())
        by_mod: dict[int, list[str]] = defaultdict(list)
        for q in qs:
            by_mod[q.module_no].append(q.text)
        if all(len(by_mod.get(m, [])) >= 3 for m in range(1, 6)):
            await ctx.info("syllabus", "Deriving topics from the questions of past papers", progress=60)
            try:
                modules = await taxonomy_from_questions(agy_client, cdef, by_mod, ws, on_event=ctx.event_fn("syllabus"))
                new, how = apply_taxonomy(cdef, modules, "derived from past papers"), "papers"
            except (AgyError, AgyUnavailable, ValueError) as exc:
                await ctx.warn("syllabus", f"Could not derive topics: {exc}")
    if new is None:
        return {"status": "provisional", "reason": "no syllabus found and not enough papers yet"}
    save_catalog(new)
    async with async_session_factory() as db:
        await ensure_course(db, ctx.course_code)
    await ctx.info("syllabus", f"Catalog built from the {how}: "
                   + ", ".join(f"M{m['no']} {len(m['topics'])} topics" for m in new["modules"]), progress=80)
    tagged = await tag_course(ctx, ctx.course_code, use_agy=True, retag=True)
    async with async_session_factory() as db:
        course = await db.get(Course, ctx.course_code)
        snap = await build_snapshot(db, course)
    return {"status": "built", "from": how, "topics": sum(len(m["topics"]) for m in new["modules"]),
            "tagged": tagged, "snapshot_id": snap.id}


async def setup_job(ctx: JobContext, params: dict) -> dict:
    """New course end to end: syllabus catalog → papers → read & analyse → notes → (topics from papers)."""
    out = {"catalog": await catalog_job(ctx, params)}
    ctx.check_cancel()
    out["auto"] = await auto_job(ctx, params)
    if out["catalog"].get("status") == "provisional":
        out["catalog_from_papers"] = await catalog_job(ctx, {**params, "from": "papers"})
    return out


# ───────────────────────────── automation ─────────────────────────────

async def auto_job(ctx: JobContext, params: dict) -> dict:
    """Everything for a course in one job: find papers → read & analyse → find notes."""
    out: dict = {}
    await ctx.info("auto", "Step 1/3: finding papers", progress=1)
    out["acquire"] = await acquire_job(ctx, params)
    ctx.check_cancel()
    await ctx.info("auto", "Step 2/3: reading and analysing papers", progress=1)
    out["process"] = await process_job(ctx, params)
    ctx.check_cancel()
    if params.get("notes", True):
        await ctx.info("auto", "Step 3/3: finding notes", progress=1)
        out["notes"] = await notes_job(ctx, params)
    return out


async def refresh_job(ctx: JobContext, params: dict) -> dict:
    """Periodic check for new papers; reads them only if something new was downloaded."""
    acq = await acquire_job(ctx, params)
    out = {"acquire": acq}
    if acq.get("fetched", 0) > 0:
        await ctx.info("refresh", f"{acq['fetched']} new file(s): reading them", progress=1)
        out["process"] = await process_job(ctx, params)
    else:
        await ctx.info("refresh", "No new papers this time")
    return out


# ───────────────────────────── process ─────────────────────────────

def _qp_key(qp: str | None) -> str | None:
    if not qp:
        return None
    q = re.sub(r"[^A-Z0-9]", "", qp.upper())
    return q if len(q) >= 8 else None


async def process_job(ctx: JobContext, params: dict) -> dict:
    use_agy = params.get("use_agy", True)
    budget = int(params.get("agy_repair_budget", 10))
    reprocess = bool(params.get("reprocess", False))
    moved_to: set[str] = set()  # other courses whose papers turned up here
    async with async_session_factory() as db:
        course = await ensure_course(db, ctx.course_code)
        template = get_template(course.template_id)
        if template.is_mcq:
            budget = max(budget, len(template.part_a_numbers))  # local OCR loses many short slots on dense pages; agy fills them (grouped by page)
        modules = {m.module_no: m.title for m in (await db.execute(
            select(CourseModule).where(CourseModule.course_code == course.code))).scalars()}
        q = select(SourceDocument).where(SourceDocument.course_code == course.code, SourceDocument.kind == "paper",
                                         SourceDocument.status.in_(("fetched", "identified", "transcribed", "unidentified", "rejected") if reprocess else ("fetched", "identified", "transcribed")))
        docs = list((await db.execute(q)).scalars())
        only_papers = set(params.get("paper_ids") or [])
        if only_papers:
            # Redo just these papers: their source files are transcribed again, others untouched.
            docs = [d for d in docs if d.paper_id in only_papers]
            await db.execute(delete(Paper).where(Paper.paper_id.in_(only_papers)))
            for d in docs:
                d.paper_id, d.status = None, "identified"
            await db.commit()
        elif reprocess:
            # Full rebuild: drop this course's papers (questions/topics cascade) and unlink sources.
            await db.execute(delete(Paper).where(Paper.course_code == course.code))
            for d in docs:
                d.paper_id = None
            await db.commit()
    ocr_ok, ocr_reason = await local_ocr.available()
    if not ocr_ok:
        await ctx.warn("identify", f"Local OCR unavailable ({ocr_reason}); scanned papers will be skipped")
    agy_ok = use_agy and agy_client.status()["available"]

    # 1. Identify every document from page 1.
    await ctx.info("identify", f"Identifying {len(docs)} document(s)", progress=2)
    first_runs: dict[str, object] = {}
    for i, doc in enumerate(docs):
        ctx.check_cancel()
        if doc.status == "transcribed" and not reprocess:
            continue
        path = Path(doc.local_path)
        info = doc_info(path)
        async with async_session_factory() as db:
            row = await db.get(SourceDocument, doc.sha256)
            try:
                if not info.scanned and info.text_chars > 300:
                    header = transcript_from_text_layer(path, template.is_mcq).header
                    looks = True
                    rotated = False
                elif ocr_ok:
                    run = await ocr_first_page(path, doc.sha256)
                    first_runs[doc.sha256] = run
                    header = parse_pages([run.pages[0].raw], mcq=template.is_mcq).header
                    looks, rotated = looks_like_exam(run.pages[0].raw), run.rotated
                else:
                    row.identified = {"error": "scanned and local OCR unavailable"}
                    await db.commit()
                    continue
            except local_ocr.LocalOcrError as exc:
                row.identified = {"error": str(exc)}
                await db.commit()
                await ctx.warn("identify", f"{doc.sha256[:10]}: {exc}")
                continue
            session_from = None
            if not (header.month and header.year):
                # Header cut off in the scan: accept the source's label if the visible part agrees.
                lab = parse_session(doc.label_claimed)
                partial = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\W*$", header.exam_title or "", re.I)
                if lab and (not partial or MONTHS[partial.group(1).lower()] == lab[0]):
                    header.month, header.year = lab
                    session_from = "source label (year not readable on the paper)"
            ident = header.model_dump() | {"rotated": rotated, "scanned": info.scanned, "session_from": session_from}
            # Never lose a field an earlier read of this file found (e.g. the QP code).
            for k, v in (doc.identified or {}).items():
                if k in TranscriptHeader.model_fields and v and not ident.get(k):
                    ident[k] = v
            code = (header.course_code or "").upper()
            first_exam = (course.catalog_json.get("first_exam") or {}).get("year", 2020)
            page1 = (first_runs[doc.sha256].pages[0].raw if doc.sha256 in first_runs else "").upper()
            mine = {c.replace(" ", "").upper() for c in course.catalog_json.get("code_variants", [course.code])}
            seen_codes = {f"{a}{b}" for a, b in _ANY_CODE.findall(page1[:3000])}
            if code and code != course.code.upper():
                other = await db.get(Course, code)
                if other is not None and other.code != course.code:
                    # Paper of another course the student has: file it there (it is read on that course's run).
                    row.course_code, row.status = other.code, "fetched"
                    ident["moved_from"] = course.code
                    moved_to.add(other.code)
                else:
                    row.status, ident["reject_reason"] = "other_course", f"paper is for {code} (kept in the library)"
            elif not code and seen_codes and not (seen_codes & mine):
                row.status, ident["reject_reason"] = "rejected", f"page 1 names {', '.join(sorted(seen_codes)[:3])}, not {course.code}"
            elif header.year and header.year < first_exam:
                row.status, ident["reject_reason"] = "rejected", f"{header.year} is before this scheme's first exam ({first_exam})"
            elif not looks:
                row.status, ident["reject_reason"] = "rejected", "not a question paper (cover page of a solved paper, notes, or unreadable)"
            elif not (header.month and header.year):
                row.status, ident["reject_reason"] = "unidentified", "exam session not readable on page 1 — needs review"
            else:
                row.status = "identified"  # (re)identified: a previous rejection no longer applies
            row.identified = ident
            await db.commit()
            doc.status, doc.identified = row.status, ident
        await ctx.info("identify", f"[{i + 1}/{len(docs)}] {session_label(ident.get('month'), ident.get('year'))} "
                       f"QP {ident.get('qp_code') or '?'} — {doc.status}{' (rotated)' if ident.get('rotated') else ''}",
                       progress=2 + int(28 * (i + 1) / max(1, len(docs))))

    if moved_to:
        from app.services.jobs import job_runner  # late import: jobs registers this module's jobs
        for other_code in sorted(moved_to):
            await ctx.info("identify", f"filed papers of {other_code} under that course; queued its processing")
            await job_runner.submit("process", other_code, {"use_agy": params.get("use_agy", True)})

    # 2. Group duplicate scans of the same question paper.
    candidates = [d for d in docs if d.status in ("identified", "transcribed") and d.identified and not d.identified.get("error")]
    groups: list[list[SourceDocument]] = []
    # Primary scan of a group = a normal-length paper (2-4 pages), best scan (largest file) first;
    # solved papers / compilations only serve as fallbacks.
    for d in sorted(candidates, key=lambda x: ((x.pages or 0) > template.max_pages, -x.bytes)):
        key = _qp_key(d.identified.get("qp_code"))
        target = None
        for g in groups:
            g0 = g[0].identified
            if key and key == _qp_key(g0.get("qp_code")):
                target = g
                break
            same_session = (g0.get("year"), g0.get("month")) == (d.identified.get("year"), d.identified.get("month"))
            if same_session and not (key and _qp_key(g0.get("qp_code"))):
                r1, r2 = first_runs.get(d.sha256), first_runs.get(g[0].sha256)
                if r1 and r2 and jaccard(_tokens(r1.pages[0].raw, True), _tokens(r2.pages[0].raw, True)) >= 0.6:
                    target = g
                    break
        (target.append(d) if target is not None else groups.append([d]))
    # A copy whose session came from a (possibly wrong) source label takes the session read
    # from the header of another copy of the same QP.
    for g in groups:
        readable = next((d for d in g if d.identified.get("month") and d.identified.get("year")
                         and not d.identified.get("session_from")), None)
        if readable is None:
            continue
        for d in g:
            if d.identified.get("session_from") and (d.identified.get("month"), d.identified.get("year")) != (
                    readable.identified["month"], readable.identified["year"]):
                fixed = dict(d.identified, month=readable.identified["month"], year=readable.identified["year"],
                             session_from="header of another copy of the same QP")
                d.identified = fixed
                async with async_session_factory() as db:
                    row = await db.get(SourceDocument, d.sha256)
                    row.identified = fixed
                    await db.commit()
    await ctx.info("group", f"{len(candidates)} document(s) → {len(groups)} distinct paper(s)", progress=32)

    # 3. Transcribe one scan per group, repair flagged slots, store.
    papers_written, agy_repairs, swapped = 0, 0, 0
    for gi, group in enumerate(groups):
        ctx.check_cancel()
        primary = group[0]
        if primary.status == "transcribed" and not reprocess and primary.paper_id:
            continue
        path = Path(primary.local_path)
        info = doc_info(path)
        run = None
        try:
            if not info.scanned and info.text_chars > 300:
                t = transcript_from_text_layer(path, template.is_mcq)
            else:
                run = await ocr_document(path, primary.sha256, first_runs.get(primary.sha256), template.max_pages,
                                         template.ocr_strips)
                t = transcript_from_run(run, template.is_mcq)
        except local_ocr.LocalOcrError as exc:
            await ctx.warn("transcribe", f"{primary.sha256[:10]}: {exc}")
            continue
        h0 = primary.identified
        hdr = t.header.model_copy(update={k: v for k, v in h0.items() if k in TranscriptHeader.model_fields and v and not getattr(t.header, k)})
        t = t.model_copy(update={"header": hdr})
        t, issues = finalize(template, t, course.code)
        slots = flagged_slots(issues)
        if slots and run is not None:
            # On demand: re-read (fully guarded) only looped pages that hold flagged questions.
            redo = looped_pages(run) & pages_for_slots(t, slots, run)
            if redo:
                await ctx.info("transcribe", f"Re-reading page(s) {sorted(p + 1 for p in redo)} locally (OCR loop near Q{sorted(slots)})")
                try:
                    run = await reread_pages(path, run, redo)
                    t = transcript_from_run(run, template.is_mcq)
                    t = t.model_copy(update={"header": t.header.model_copy(update={
                        k: v for k, v in h0.items() if k in TranscriptHeader.model_fields and v and not getattr(t.header, k)})})
                    t, issues = finalize(template, t, course.code)
                    slots = flagged_slots(issues)
                except local_ocr.LocalOcrError as exc:
                    await ctx.warn("transcribe", f"Re-read failed: {exc}")
        for alt in group[1:]:
            if not slots:
                break
            try:
                alt_info = doc_info(Path(alt.local_path))
                if not alt_info.scanned and alt_info.text_chars > 300:
                    alt_t = transcript_from_text_layer(Path(alt.local_path), template.is_mcq)
                else:
                    alt_t = transcript_from_run(await ocr_document(Path(alt.local_path), alt.sha256, first_runs.get(alt.sha256),
                                                                template.max_pages, template.ocr_strips), template.is_mcq)
            except local_ocr.LocalOcrError:
                continue
            alt_t, _ = finalize(template, alt_t, course.code)
            t, replaced = merge_slots(template, t, alt_t, slots)
            if replaced:
                swapped += len(replaced)
                await ctx.info("transcribe", f"Filled Q{sorted(replaced)} from the duplicate scan (no tokens used)")
            t, issues = finalize(template, t, course.code)
            slots = flagged_slots(issues)
        if slots and agy_ok and run is not None and budget > 0:
            order = repair_order(issues, slots)
            await ctx.info("repair", f"Asking agy to re-read Q{order[:budget]} (cropped, errors first)")
            t, repaired = await repair_with_agy(agy_client, template, t, run, slots,
                                                f"{course.code} {course.title}", workspace(ctx), budget,
                                                on_event=ctx.event_fn("repair"), order=order)
            agy_repairs += len(repaired)
            t, issues = finalize(template, t, course.code)

        hdr = t.header
        claimed_issues = []
        for d in group:
            claimed = parse_session(d.label_claimed)
            if claimed and hdr.month and hdr.year and claimed != (hdr.month, hdr.year):
                claimed_issues.append(Issue(code="B08", level="warn", message=(
                    f"Source {d.origin} labels it '{session_label(*claimed)}', the paper says "
                    f"'{session_label(hdr.month, hdr.year)}'")))
        if len(group) > 1:
            claimed_issues.append(Issue(code="B09", level="info", message=(
                f"Same paper found in {len(group)} files: " + ", ".join(sorted({d.origin for d in group})))))
        if primary.identified.get("session_from"):
            claimed_issues.append(Issue(code="B07", level="warn", message=(
                f"Session taken from the {primary.identified['session_from']}")))
        if (primary.pages or 0) > template.max_pages:
            claimed_issues.append(Issue(code="B09", level="warn", message=(
                f"Only a {primary.pages}-page document (solved paper/compilation) was available; first pages read")))
        if run is not None:
            # A scan that repeats a page (and so lacks another) explains questions no re-read can find.
            toks = [_tokens(pg.raw, True) for pg in run.pages]
            for a in range(len(toks)):
                for b in range(a + 1, len(toks)):
                    if len(toks[a]) > 40 and jaccard(toks[a], toks[b]) >= 0.7:
                        claimed_issues.append(Issue(code="B12", level="warn", message=(
                            f"The scan repeats page {a + 1} as page {b + 1}, so a page of the paper is missing "
                            "from this file; its questions cannot be read")))
        all_issues = issues + claimed_issues
        paper_id = await write_paper(course, template, modules, t, all_issues, group)
        papers_written += 1
        await ctx.info("transcribe", f"[{gi + 1}/{len(groups)}] {session_label(hdr.month, hdr.year)} → {paper_id}: "
                       f"{len(t.questions)} entries, {sum(1 for i in all_issues if i.level == 'error')} error(s), "
                       f"{sum(1 for i in all_issues if i.level == 'warn')} warning(s)",
                       progress=32 + int(48 * (gi + 1) / max(1, len(groups))))

    # 4. Tag topics, 5. snapshot.
    tagged = await tag_course(ctx, course.code, use_agy=use_agy, retag=bool(params.get("retag", False)))
    await ctx.info("insights", "Recomputing insights and backtest", progress=95)
    async with async_session_factory() as db:
        course = await db.get(Course, ctx.course_code)
        snap = await build_snapshot(db, course)
    return {"documents": len(docs), "distinct_papers": len(groups), "papers_written": papers_written,
            "slots_from_duplicate_scans": swapped, "agy_repaired_slots": agy_repairs, "tagged": tagged,
            "snapshot_id": snap.id}


async def write_paper(course: Course, template, modules: dict[int, str], t, issues: list[Issue], group) -> str:
    h = t.header
    primary = group[0]
    qp = _qp_key(h.qp_code)
    async with async_session_factory() as db:
        paper = None
        if qp:
            paper = (await db.execute(select(Paper).where(Paper.course_code == course.code, Paper.qp_code == qp))).scalars().first()
        if paper is None:
            existing_ids = [d.paper_id for d in group if d.paper_id]
            if existing_ids:
                paper = await db.get(Paper, existing_ids[0])
        if paper is None:
            stamp = f"{h.year or 0}{(h.month or 0):02d}"
            paper = Paper(paper_id=f"{course.code}_{stamp}_{(qp or primary.sha256)[-6:]}", subject=course.code,
                          year=h.year or 0, total_marks=template.total_marks, source_file=primary.local_path)
            db.add(paper)
        paper.subject, paper.course_code = course.code, course.code
        paper.year, paper.total_marks = h.year or 0, h.max_marks or template.total_marks
        paper.source_file, paper.ocr_status = primary.local_path, "completed"
        paper.session_month, paper.session_year = h.month, h.year
        paper.exam_title, paper.cohorts, paper.qp_code, paper.scheme = h.exam_title, h.cohorts, qp, h.scheme
        paper.primary_sha256 = primary.sha256
        providers = sorted({q.provider or t.provider for q in t.questions})
        paper.extraction_provider = "+".join(providers) or t.provider
        paper.extraction_model = t.model
        paper.issues = [i.model_dump() for i in issues]
        paper.needs_review = any(i.level in ("error", "warn") for i in issues)
        await db.flush()
        await db.execute(delete(Question).where(Question.paper_id == paper.paper_id))
        flagged = {(i.number, i.sub) for i in issues if i.number is not None}
        flagged_numbers = {i.number for i in issues if i.number is not None and i.sub is None}
        used: set[str] = set()
        for q in t.questions:
            qid = f"{paper.paper_id}_q{q.number}{q.sub or ''}"
            while qid in used:
                qid += "_dup"
            used.add(qid)
            module_no = template.module_of(q.number)
            is_flagged = (q.number, q.sub) in flagged or q.number in flagged_numbers
            reasons = [i.message for i in issues if i.number == q.number and (i.sub in (None, q.sub))]
            db.add(Question(
                question_id=qid, paper_id=paper.paper_id, year=h.year or 0, question_no=f"{q.number}{q.sub or ''}",
                text=q.text, options=q.options, marks=q.marks if q.marks is not None else 0.0, has_diagram=q.has_diagram,
                unit_guess=modules.get(module_no) if module_no else None, part=q.part, number=q.number, sub=q.sub,
                module_no=module_no, legibility=q.legibility, marks_inferred=q.marks_inferred, needs_review=is_flagged,
                review_reason="; ".join(reasons) if reasons else None))
        for d in group:
            row = await db.get(SourceDocument, d.sha256)
            row.status, row.paper_id = "transcribed", paper.paper_id
            if d.sha256 == primary.sha256:
                row.transcript = t.model_dump()
        await db.commit()
        return paper.paper_id


async def tag_course(ctx: JobContext, code: str, use_agy: bool, retag: bool) -> dict:
    async with async_session_factory() as db:
        course = await db.get(Course, code)
        topics = list((await db.execute(select(CourseTopic).where(CourseTopic.course_code == code))).scalars())
        qs = list((await db.execute(
            select(Question).join(Paper, Paper.paper_id == Question.paper_id)
            .where(Paper.course_code == code, Question.module_no.is_not(None)))).scalars())
        have = {r[0] for r in (await db.execute(select(QuestionTopic.question_id))).all()}
    todo = [q for q in qs if retag or q.question_id not in have]
    if not todo:
        return {"tagged": 0, "agy": 0, "keyword": 0}
    await ctx.info("tag", f"Tagging {len(todo)} question(s) by module", progress=82)
    cdef_modules = {m["no"]: m for m in course.catalog_json["modules"]}
    counts = {"tagged": 0, "agy": 0, "keyword": 0}

    async def run_module(mno: int):
        items = [TagItem(q.question_id, mno, q.text) for q in todo if q.module_no == mno]
        m_topics = [{"id": t.topic_id, "name": t.name, "keywords": t.keywords} for t in topics if t.module_no == mno]
        return mno, await tag_module(agy_client, mno, cdef_modules[mno]["title"], m_topics, items, workspace(ctx),
                                     use_agy=use_agy, on_event=ctx.event_fn("tag"))

    # Modules are independent: tag them concurrently (the agy client caps parallel calls).
    module_results = await asyncio.gather(*(run_module(m) for m in sorted({q.module_no for q in todo})))
    ctx.check_cancel()
    for mno, results in module_results:
        async with async_session_factory() as db:
            for r in results:
                await db.execute(delete(QuestionTopic).where(QuestionTopic.question_id == r.id))
                q = await db.get(Question, r.id)
                q.kind = r.kind
                for tid, conf in r.topics:
                    db.add(QuestionTopic(question_id=r.id, topic_id=tid, confidence=conf, source=r.source))
                if r.source == "keyword":
                    q.needs_review = True
                    q.review_reason = "; ".join(filter(None, [q.review_reason, "topic from keyword fallback (low confidence)"]))
                counts[r.source] += 1
                counts["tagged"] += 1
            await db.commit()
        await ctx.info("tag", f"Module {mno}: {len(results)} tagged")
    return counts


# ───────────────────────────── insights ─────────────────────────────

async def coverage(db: AsyncSession, course: Course) -> dict:
    cdef = course.catalog_json
    first = cdef.get("first_exam") or {"year": 2020, "month": 12}
    windows = expected_windows(first["year"], first["month"])
    papers = list((await db.execute(select(Paper).where(Paper.course_code == course.code))).scalars())
    out, placed = [], set()
    for w in windows:
        hits = [p for p in papers if p.session_month and p.session_year and w.contains(p.session_month, p.session_year)]
        placed |= {p.paper_id for p in hits}
        out.append({"label": w.label, "kind": w.kind, "year": w.year,
                    "papers": [{"paper_id": p.paper_id, "label": session_label(p.session_month, p.session_year),
                                "qp_code": p.qp_code} for p in hits]})
    other = [{"paper_id": p.paper_id, "label": session_label(p.session_month, p.session_year), "qp_code": p.qp_code}
             for p in papers if p.paper_id not in placed]
    return {"windows": out, "other": other,
            "found": sum(1 for w in out if w["papers"]), "expected": len(out)}


LAMBDA_CHOICES = (1.0, 0.9, 0.8, 0.7)


async def build_snapshot(db: AsyncSession, course: Course) -> AnalysisSnapshot:
    template = get_template(course.template_id)
    cdef = course.catalog_json
    order = {t["id"]: i for i, t in enumerate(t for m in cdef["modules"] for t in m["topics"])}
    topics = sorted((await db.execute(select(CourseTopic).where(CourseTopic.course_code == course.code))).scalars(),
                    key=lambda t: order.get(t.topic_id, 10_000))
    papers = [p for p in (await db.execute(select(Paper).where(Paper.course_code == course.code))).scalars()
              if p.session_year and p.session_month]
    counts: dict[int, int] = defaultdict(int)
    for p in papers:
        counts[session_key(p.session_month, p.session_year)] += 1
    rows = []
    for p in papers:
        label = session_label(p.session_month, p.session_year)
        if counts[session_key(p.session_month, p.session_year)] > 1 and p.qp_code:
            label += f" · QP …{p.qp_code[-3:]}"
        rows.append(PaperRow(p.paper_id, session_key(p.session_month, p.session_year), label))
    pids = [p.paper_id for p in papers]
    qs = list((await db.execute(select(Question).where(Question.paper_id.in_(pids), Question.module_no.is_not(None))))
              .scalars()) if pids else []
    tq: dict[str, list[tuple[float, str]]] = defaultdict(list)
    if qs:
        for r in (await db.execute(select(QuestionTopic).where(QuestionTopic.question_id.in_([q.question_id for q in qs])))).scalars():
            tq[r.question_id].append((r.confidence, r.topic_id))
    qrows = [QRow(q.question_id, q.paper_id, q.part or template.part_of(q.number or 0) or "?", q.number or 0, q.sub,
                  q.module_no, q.marks, [t for _c, t in sorted(tq.get(q.question_id, []), reverse=True)], q.kind, q.text)
             for q in qs]
    tdefs = [TopicDef(t.topic_id, t.module_no, t.name) for t in topics]
    # Pick the recency weight by backtest (ties go to the simpler λ = 1, plain frequency).
    trials = {lam: run_backtest(template, cdef["modules"], tdefs, rows, qrows, lam=lam) for lam in LAMBDA_CHOICES}
    scored = [(bt["summary"]["brier"]["model"], -lam, lam) for lam, bt in trials.items()
              if bt["summary"]["brier"]["model"] is not None]
    lam = min(scored)[2] if scored else 1.0
    results = compute(template, cdef["modules"], tdefs, rows, qrows, lam=lam)
    results["backtest"] = trials[lam]
    results["backtest"]["lambda_trials"] = {str(k): v["summary"]["brier"]["model"] for k, v in trials.items()}
    results["coverage"] = await coverage(db, course)
    snap = AnalysisSnapshot(course_code=course.code, params=results["params"], results=results)
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return snap


async def insights_job(ctx: JobContext, params: dict) -> dict:
    async with async_session_factory() as db:
        course = await ensure_course(db, ctx.course_code)
        snap = await build_snapshot(db, course)
    return {"snapshot_id": snap.id, "papers": snap.results["n_papers"]}
