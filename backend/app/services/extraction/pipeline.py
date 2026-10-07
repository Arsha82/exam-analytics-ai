"""
Transcription chain (token-lean):

1. born-digital PDFs → text layer (no model at all);
2. scans → local Unlimited-OCR per page (cached on disk by sha256 + page), upside-down
   pages detected and rotated;
3. the deterministic parser builds a Transcript; the template validator flags slots;
4. flagged slots are first taken from a duplicate scan of the same QP if it reads them
   cleanly, and only then sent to agy — as a cropped region, low-thinking model.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from pydantic import BaseModel

from app.config import settings
from app.services.agy import AgyClient, AgyError, AgyUnavailable
from app.services.exam_templates import ExamTemplate, normalize_questions, validate
from app.services.extraction import local_ocr
from app.services.extraction.ocr_parser import Block, exam_score, looks_like_exam, parse_header, parse_pages, parse_questions
from app.services.extraction.pdf import doc_info, render_page, text_layer
from app.services.transcript import Issue, Transcript, TranscriptQuestion

logger = logging.getLogger(__name__)


@dataclass
class OcrPage:
    raw: str
    image_path: Path  # the exact image the OCR model saw (bbox grid refers to it)


@dataclass
class OcrRun:
    sha256: str
    pages: list[OcrPage] = field(default_factory=list)
    rotated: bool = False
    provider: str = "local_ocr"
    strips: int = 0


# Bump when the OCR call or its post-processing changes, so stale outputs are re-read.
OCR_CACHE_VERSION = 2


def _cache_dir(sha: str) -> Path:
    d = settings.storage_dir / "ocr" / sha
    d.mkdir(parents=True, exist_ok=True)
    return d


def page_quality(raw: str) -> float:
    """How usable a page read is: exam structure found, minus a heavy penalty for loops."""
    return exam_score(raw) + 0.002 * len(raw) - (25 if local_ocr.is_degenerate(raw) else 0)


async def ocr_page_cached(path: Path, sha: str, index: int, rotate: bool, escalate: bool = False,
                          strips: int = 0) -> OcrPage:
    """
    OCR a page once and cache it. `escalate` reads it again with the full loop guards and
    keeps whichever read is better — a fallback read can be worse (e.g. a half dropped).
    """
    d = _cache_dir(sha)
    tag = f"v{OCR_CACHE_VERSION}_p{index}{'_r180' if rotate else ''}{f'_s{strips}w' if strips > 1 else ''}"
    txt, img_path = d / f"{tag}.txt", d / f"{tag}.jpg"
    cached = OcrPage(txt.read_text(encoding="utf-8"), img_path) if txt.exists() and img_path.exists() else None
    if cached is not None and not escalate:
        return cached
    img = render_page(path, index, settings.ocr_render_scale)
    if rotate:
        img = img.rotate(180, expand=True)
    raw, prepared = await local_ocr.ocr_image(img, escalate=escalate, strips=strips)
    if cached is not None and page_quality(raw) <= page_quality(cached.raw):
        (d / f"{tag}_rejected.txt").write_text(raw, encoding="utf-8")  # kept for inspection
        return cached
    prepared.save(img_path, format="JPEG", quality=90)
    txt.write_text(raw, encoding="utf-8")
    return OcrPage(raw, img_path)


async def ocr_first_page(path: Path, sha: str) -> OcrRun:
    """OCR page 1 (rotating if it reads as garbage) — enough to identify the paper."""
    page = await ocr_page_cached(path, sha, 0, rotate=False)
    run = OcrRun(sha256=sha, pages=[page])
    if not looks_like_exam(page.raw):
        flipped = await ocr_page_cached(path, sha, 0, rotate=True)
        # Rotate only when the flipped page reads clearly better and in question order.
        if looks_like_exam(flipped.raw) and exam_score(flipped.raw) > exam_score(page.raw) + 3:
            run.pages, run.rotated = [flipped], True
    return run


LONG_DOC_PAGES = 6  # a question paper is 2-4 pages; longer files are solved papers / compilations
LONG_DOC_READ = 4


async def ocr_document(path: Path, sha: str, first: OcrRun | None = None, long_doc_pages: int = LONG_DOC_PAGES,
                       strips: int = 0) -> OcrRun:
    """OCR every page of a question paper (only the first pages of a long document).
    With `strips`, every page — page 1 too — is read in horizontal strips."""
    first = first or await ocr_first_page(path, sha)
    info = doc_info(path)
    run = OcrRun(sha256=sha, pages=[] if strips > 1 else list(first.pages), rotated=first.rotated, strips=strips)
    last = info.pages if info.pages <= long_doc_pages else LONG_DOC_READ
    for i in range(len(run.pages), last):
        run.pages.append(await ocr_page_cached(path, sha, i, rotate=first.rotated, strips=strips))
    return run


def looped_pages(run: OcrRun) -> set[int]:
    return {i for i, p in enumerate(run.pages) if local_ocr.is_degenerate(p.raw)}


def pages_for_slots(t: Transcript, slots: set[int], run: OcrRun) -> set[int]:
    return {p for n in slots for p in _pages_of(t, n, run)}


async def reread_pages(path: Path, run: OcrRun, pages: set[int]) -> OcrRun:
    """Fresh, fully-guarded OCR of the given pages (on demand, for flagged questions)."""
    new_pages = list(run.pages)
    for i in sorted(pages):
        new_pages[i] = await ocr_page_cached(path, run.sha256, i, rotate=run.rotated, escalate=True, strips=run.strips)
    return OcrRun(sha256=run.sha256, pages=new_pages, rotated=run.rotated, provider=run.provider, strips=run.strips)


def transcript_from_text_layer(path: Path, mcq: bool = False) -> Transcript:
    blocks: list[Block] = []
    for i, page_text in enumerate(text_layer(path)):
        for line in page_text.splitlines():
            if line.strip():
                blocks.append(Block("text", [0, 0, 1000, 0], re.sub(r"\s+", " ", line).strip(), i))
    return Transcript(header=parse_header(blocks, mcq), questions=parse_questions(blocks, mcq), provider="text_layer",
                      pages=len(set(b.page for b in blocks)))


def transcript_from_run(run: OcrRun, mcq: bool = False) -> Transcript:
    return parse_pages([p.raw for p in run.pages], model=settings.ollama_ocr_model, mcq=mcq)


def finalize(template: ExamTemplate, t: Transcript, course_code: str) -> tuple[Transcript, list[Issue]]:
    t = t.model_copy(update={"questions": normalize_questions(template, t.questions)})
    return t, validate(template, t, course_code)


def _slot_ok(template: ExamTemplate, entries: list[TranscriptQuestion]) -> bool:
    if not entries or any(e.legibility != "clear" or e.marks is None or len(e.text) < 8 for e in entries):
        return False
    if template.is_mcq and any(len(e.options or []) != template.options for e in entries):
        return False
    expected = template.part_a_marks if template.part_of(entries[0].number) == "A" else template.part_b_marks
    return abs(sum(e.marks or 0 for e in entries) - expected) < 1e-6


def merge_slots(template: ExamTemplate, base: Transcript, other: Transcript, slots: set[int]) -> tuple[Transcript, set[int]]:
    """Take flagged slots from another transcript of the same QP where they read cleanly."""
    replaced: set[int] = set()
    qs = list(base.questions)
    for n in slots:
        alt = [q for q in other.questions if q.number == n]
        if _slot_ok(template, alt):
            qs = [q for q in qs if q.number != n] + alt
            replaced.add(n)
    qs.sort(key=lambda q: (q.number, q.sub or ""))
    return base.model_copy(update={"questions": qs}), replaced


# ── agy repair of flagged slots (cropped region) ──

class _RepairPart(BaseModel):
    sub: str | None = None
    marks: float | None = None
    text: str


class _RepairQuestion(BaseModel):
    number: int
    parts: list[_RepairPart] = []
    text: str | None = None  # MCQ: the question stem
    options: list[str] | None = None  # MCQ: the choices a-d, in order


class _RepairReply(BaseModel):
    questions: list[_RepairQuestion]


REPAIR_PROMPT = """Files:
{paths}

Task: Open the file(s) with read_file. They are part of a scanned university exam paper ({course}).
Transcribe ONLY question number(s) {numbers}, exactly as printed. Each question may have
sub-parts (a), (b), (c) with marks in brackets like (7); Part A questions have one part.
Write mathematics in LaTeX between $...$. Never solve or explain. Write [unclear] for
anything you cannot read.

Reply with only this JSON:
{{"questions": [{{"number": <int>, "parts": [{{"sub": "a" | "b" | "c" | null, "marks": <number or null>, "text": "<exact text>"}}]}}]}}"""


MCQ_REPAIR_PROMPT = """Files:
{paths}

Task: Open the file(s) with read_file. They are part of a scanned multiple-choice exam paper ({course}).
Transcribe ONLY question number(s) {numbers}, exactly as printed: the question, then its {n_options}
options a), b), c), d) in order (option text only, without the letter). Write mathematics in LaTeX
between $...$. Never answer or explain. Write [unclear] for anything you cannot read.

Reply with only this JSON:
{{"questions": [{{"number": <int>, "text": "<question exactly as printed>", "options": ["<a>", "<b>", "<c>", "<d>"]}}]}}"""


def _crop_for(run: OcrRun, t: Transcript, page_idx: int, numbers: list[int], out: Path) -> Path:
    page = run.pages[page_idx]
    with Image.open(page.image_path) as img:
        w, h = img.size
        boxes = [q.bbox for q in t.questions if q.number in numbers and q.page == page_idx and q.bbox]
        if boxes and len(boxes) >= len(numbers):
            y1 = max(0.0, min(b[1] for b in boxes) - 40)
            y2 = min(1000.0, max(b[3] for b in boxes) + 60)
            region = img.crop((0, int(y1 * h / 1000), w, int(y2 * h / 1000)))
        else:
            region = img.copy()  # a slot is missing entirely: send the whole page
        region.save(out, format="PNG")
    return out


def _pages_of(t: Transcript, number: int, run: OcrRun) -> tuple[int, ...]:
    """Page(s) to show agy for a slot: its own page, or for a missing slot the page(s)
    between the neighbouring questions that were read."""
    own = sorted({q.page for q in t.questions if q.number == number and q.page is not None})
    if own:
        return (own[0],)
    before = [q.page for q in t.questions if q.number < number and q.page is not None]
    after = [q.page for q in t.questions if q.number > number and q.page is not None]
    lo = max(before) if before else 0
    hi = min(after) if after else len(run.pages) - 1
    if hi - lo >= 2:
        return tuple(range(lo + 1, hi))[:2]
    return tuple(sorted({lo, hi}))[:2]


async def repair_with_agy(
    client: AgyClient,
    template: ExamTemplate,
    t: Transcript,
    run: OcrRun,
    slots: set[int],
    course_label: str,
    workspace: Path,
    budget: int,
    on_event=None,
    order: list[int] | None = None,
) -> tuple[Transcript, set[int]]:
    todo = (order or sorted(slots))[:budget]
    by_pages: dict[tuple[int, ...], list[int]] = {}
    for n in todo:
        by_pages.setdefault(_pages_of(t, n, run), []).append(n)
    workspace.mkdir(parents=True, exist_ok=True)
    repaired: set[int] = set()
    qs = list(t.questions)
    # Each agy call carries ~9k tokens of fixed overhead, so all crops of a paper go into
    # one call (split only beyond 4 images).
    crops: list[tuple[Path, int, list[int]]] = []
    for pages, numbers in by_pages.items():
        for p in pages:
            name = f"{run.sha256[:12]}_p{p}_q{'-'.join(map(str, numbers))}.png"
            crops.append((_crop_for(run, t, p, numbers, workspace / name), p, numbers))
    # A call answers at most `per_call` questions: long replies get cut off mid-JSON (seen with
    # 14 MCQs in one call), losing every question in it.
    per_call = 8 if template.is_mcq else 12
    chunks: list[list[tuple[Path, int, list[int]]]] = []
    for f, p, numbers in crops:
        for i in range(0, len(numbers), per_call):
            part = numbers[i : i + per_call]
            last = chunks[-1] if chunks else None
            if last and len(last) < 4 and len({n for _f, _p, ns in last for n in ns} | set(part)) <= per_call:
                last.append((f, p, part))
            else:
                chunks.append([(f, p, part)])
    page_of_number = {n: p for _f, p, ns in crops for n in ns}

    async def one(chunk: list[tuple[Path, int, list[int]]]):
        numbers = sorted({n for _f, _p, ns in chunk for n in ns})
        page_idx = chunk[0][1]
        file_list = "\n".join(f"- {f.resolve()}" for f, _p, _ns in chunk)
        if template.is_mcq:
            prompt = MCQ_REPAIR_PROMPT.format(paths=file_list, course=course_label, numbers=", ".join(map(str, numbers)),
                                              n_options=template.options)
        else:
            prompt = REPAIR_PROMPT.format(paths=file_list, course=course_label, numbers=", ".join(map(str, numbers)))
        try:
            reply, _res = await client.run_json(
                prompt, _RepairReply, agent="pyq-reader", model=settings.agy_reader_model,
                cwd=workspace, fallback_model=settings.agy_fallback_model, on_event=on_event,
            )
        except (AgyError, AgyUnavailable) as exc:
            if on_event:
                await on_event("warn", f"agy repair skipped for Q{numbers}: {exc}", None)
            return page_idx, numbers, None
        return page_idx, numbers, reply

    results = await asyncio.gather(*(one(c) for c in chunks))
    for page_idx, numbers, reply in results:
        if reply is None:
            continue
        for rq in reply.questions:
            if rq.number not in numbers:
                continue
            part = template.part_of(rq.number)
            if template.is_mcq:
                if not rq.text:
                    continue
                new = [TranscriptQuestion(
                    part=part, number=rq.number, marks=template.part_a_marks, marks_inferred=True,
                    text=rq.text.strip(), options=[o.strip() for o in (rq.options or [])] or None,
                    legibility="partly_unclear" if "[unclear]" in rq.text + " ".join(rq.options or []) else "clear",
                    page=page_of_number.get(rq.number, page_idx), provider="agy")]
                if _slot_ok(template, new):
                    qs = [q for q in qs if q.number != rq.number] + new
                    repaired.add(rq.number)
                continue
            new = [
                TranscriptQuestion(
                    part=part, number=rq.number, sub=(p.sub or None) if len(rq.parts) > 1 else None,
                    marks=p.marks if p.marks is not None else (template.part_a_marks if part == "A" else None),
                    text=p.text.strip(), legibility="partly_unclear" if "[unclear]" in p.text else "clear",
                    page=page_of_number.get(rq.number, page_idx), provider="agy",
                )
                for p in rq.parts
            ]
            new = normalize_questions(template, new)  # infers a single missing Part B mark
            if _slot_ok(template, new):
                qs = [q for q in qs if q.number != rq.number] + new
                repaired.add(rq.number)
    qs.sort(key=lambda q: (q.number, q.sub or ""))
    return t.model_copy(update={"questions": qs}), repaired
