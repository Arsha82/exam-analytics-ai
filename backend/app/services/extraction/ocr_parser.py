"""
Deterministic parser for Unlimited-OCR / DeepSeek-OCR page output.

The model emits one block per line as `label [x1, y1, x2, y2]text` (coordinates on a
0-1000 grid), with unlabelled lines continuing the previous block and math in
\\( \\) / \\[ \\]. This module turns those blocks into a Transcript: header fields
from the top of page 1, then questions segmented by number / sub-part / marks, with
the PART and Module headings tracked as context.
"""

import re
from dataclasses import dataclass, field

from app.services.acquisition.sessions import parse_cohorts, parse_session
from app.services.transcript import Transcript, TranscriptHeader, TranscriptQuestion

_BLOCK = re.compile(
    r"^(?P<label>[a-z_]+)\s*\[\s*(?P<x1>\d+)\s*,\s*(?P<y1>\d+)\s*,\s*(?P<x2>\d+)\s*,\s*(?P<y2>\d+)\s*\]\s*(?P<text>.*)$"
)
_PART = re.compile(r"^\W*PART\s*[-:]?\s*([AB])\b\W*(.*)$", re.IGNORECASE)
_MODULE = re.compile(r"^\W*MODULE\s*[-:]?\s*(\d|IV|V|I{1,3})\b\W*(.*)$", re.IGNORECASE)
_INSTRUCTION = re.compile(r"^(answer\s+(all|any)|each\s+question\s+carries|marks?$)", re.IGNORECASE)
_QSTART = re.compile(r"^(?:Q\.?\s*)?(\d{1,2})\s*[.)]?\s*(?:\(\s*([a-e])\s*\)|([a-e])\s*\))?\s+(.*)$")
_QSTART_TIGHT = re.compile(r"^(?:Q\.?\s*)?(\d{1,2})\s*\(\s*([a-e])\s*\)\s*(.*)$")
_SUBSTART = re.compile(r"^\(?\s*([a-e])\s*\)\s+(.*)$")
_MARKS_TAIL = re.compile(r"\(\s*(\d{1,2})\s*(?:marks?)?\s*\)\s*$|\[\s*(\d{1,2})\s*(?:marks?)?\s*\]\s*$", re.IGNORECASE)
_ONLY_MARKS = re.compile(r"^\(\s*(\d{1,2})\s*\)$")
_NOISE = re.compile(r"^(page\s*\d+\s*(of\s*\d+)?|\*+|-+|_+|reg\.?\s*no.*|name\s*:.*)$", re.IGNORECASE)
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
_SKIP_LABELS = {"page_number", "footer", "page_footer", "page_header"}
_DIAGRAM_LABELS = {"image", "figure", "picture", "chart"}


@dataclass
class Block:
    label: str
    bbox: list[float]
    text: str
    page: int


@dataclass
class _Entry:
    number: int
    sub: str | None
    text: str
    marks: float | None
    module: int | None
    part: str | None
    page: int
    bbox: list[float]
    has_diagram: bool = False
    extra: list[str] = field(default_factory=list)


def clean_math(text: str) -> str:
    text = text.replace("\\(", "$").replace("\\)", "$").replace("\\[", "$$").replace("\\]", "$$")
    return re.sub(r"[ \t]+", " ", text).strip()


def parse_blocks(raw: str, page: int) -> list[Block]:
    blocks: list[Block] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        m = _BLOCK.match(line.strip())
        if m:
            bbox = [float(m.group(k)) for k in ("x1", "y1", "x2", "y2")]
            blocks.append(Block(m.group("label").lower(), bbox, clean_math(m.group("text")), page))
        elif blocks:
            # Keep a trailing "(7)" at the end when the block wraps onto another line.
            prev, marks = _strip_marks(blocks[-1].text)
            merged = (prev + " " + clean_math(line)).strip()
            blocks[-1].text = merged + (f" ({marks:g})" if marks is not None else "")
        else:
            blocks.append(Block("text", [0, 0, 1000, 0], clean_math(line), page))
    return blocks


def looks_like_exam(raw: str) -> bool:
    """Cheap orientation/quality check: an upside-down scan yields none of these."""
    low = raw.lower()
    hits = sum(k in low for k in ("part a", "part b", "module", "marks", "answer", "course"))
    starts = len(re.findall(r"\]\s*\d{1,2}\s*(?:\(?[a-e]\))?\s+[A-Za-z\\$]", raw))
    return hits >= 2 or starts >= 3


def exam_score(raw: str) -> float:
    """
    How much an OCR output reads like an exam page, used to choose between the page and
    its 180° rotation. Question numbers must mostly *increase* down the page: a model
    reading an upside-down page still finds text, but in reverse order.
    """
    low = raw.lower()
    hits = sum(k in low for k in ("part a", "part b", "module", "marks", "answer", "course code", "duration"))
    nums = [int(n) for n in re.findall(r"\]\s*(\d{1,2})\s*(?:\(?[a-e]\))?[.)]?\s+[A-Za-z\\$(]", raw) if 1 <= int(n) <= 60]
    pairs = list(zip(nums, nums[1:]))
    ascending = sum(1 for a, b in pairs if b >= a) / len(pairs) if pairs else 0.5
    score = 3 * hits + len(nums)
    if len(nums) >= 4 and ascending < 0.6:
        score -= 2 * len(nums) + 6
    return score


def _strip_marks(text: str) -> tuple[str, float | None]:
    m = _MARKS_TAIL.search(text)
    if not m:
        return text, None
    return text[: m.start()].rstrip(" .,;"), float(m.group(1) or m.group(2))


def _union(a: list[float], b: list[float]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def parse_header(blocks: list[Block], mcq: bool = False) -> TranscriptHeader:
    head_blocks: list[Block] = []
    for b in blocks:
        if _PART.match(b.text):
            break
        if mcq and (re.match(r"^\W*instructions?\b", b.text, re.IGNORECASE) or re.match(r"^(?:Q\.?\s*)?1\s*[.)]?\s+[A-Za-z]", b.text)):
            break  # MCQ papers have no PART heading: the header ends at the instructions / Q1
        head_blocks.append(b)
    joined = "\n".join(b.text for b in head_blocks)
    h = TranscriptHeader()
    if m := re.search(r"Course\s*Code\s*[:\-]?\s*([A-Z]{2,4}\s?\d{3})", joined, re.IGNORECASE):
        h.course_code = m.group(1).replace(" ", "").upper()
    if m := re.search(r"Course\s*Name\s*[:\-]?\s*(.+)", joined, re.IGNORECASE):
        h.course_name = m.group(1).strip()
    if m := re.search(r"Max(?:imum)?\.?\s*Marks\s*[:\-]?\s*(\d{2,3})", joined, re.IGNORECASE):
        h.max_marks = int(m.group(1))
    if m := re.search(r"Duration\s*[:\-]?\s*([\d.½]+\s*(?:Hours?|Hrs?))", joined, re.IGNORECASE):
        h.duration = m.group(1)
    for b in head_blocks:
        compact = re.sub(r"\s+", "", b.text).upper()
        if re.fullmatch(r"[0-9OI]{3,6}[A-Z]{3}[0-9OIL]{3,}[A-Z0-9]*", compact) and h.qp_code is None:
            h.qp_code = compact
        if h.exam_title is None and re.search(r"examination|degree", b.text, re.IGNORECASE):
            h.exam_title = b.text
    if h.exam_title:
        if s := parse_session(h.exam_title):
            h.month, h.year = s
        h.cohorts = parse_cohorts(h.exam_title)
        if m := re.search(r"\((\d{4})\s*Scheme\)", h.exam_title, re.IGNORECASE):
            h.scheme = m.group(1)
    return h


_OPT_MARK = r"(?:(?<=\s)|^)\(?\s*{l}\s*[).]\s*"


def split_options(text: str, n: int = 4) -> tuple[str, list[str]]:
    """
    "Stem … a) 21ns b) 30ns c) 23ns d) 35ns" → ("Stem …", ["21ns", "30ns", "23ns", "35ns"]).
    Markers are searched from the last option backwards so a "(a)" inside the stem is not taken.
    """
    letters = "abcdefgh"[:n]
    pos: list[tuple[int, int]] = []  # (marker start, text start) per letter, a..d
    end = len(text)
    for letter in reversed(letters):
        found = list(re.finditer(_OPT_MARK.format(l=letter), text[:end], re.IGNORECASE))
        if not found:
            return text.strip(), []
        m = found[-1]
        pos.insert(0, (m.start(), m.end()))
        end = m.start()
    stem = text[: pos[0][0]].strip()
    opts = [text[pos[i][1]: pos[i + 1][0] if i + 1 < len(pos) else len(text)].strip(" ;,") for i in range(len(pos))]
    return stem, opts


def parse_questions(blocks: list[Block], mcq: bool = False, max_number: int | None = None) -> list[TranscriptQuestion]:
    if mcq:
        return _parse_mcq(blocks, max_number or 50)
    entries: list[_Entry] = []
    part: str | None = None
    module: int | None = None
    started = False
    cur: _Entry | None = None

    def start(number: int, sub: str | None, text: str, b: Block):
        nonlocal cur
        text, marks = _strip_marks(text)
        cur = _Entry(number, sub, text, marks, module if part != "A" else None, part, b.page, list(b.bbox))
        entries.append(cur)

    for b in blocks:
        text = b.text.strip()
        if not text or b.label in _SKIP_LABELS:
            continue
        if b.label in _DIAGRAM_LABELS:
            if cur is not None:
                cur.has_diagram = True
            continue
        if m := _PART.match(text):
            part, started, cur = m.group(1).upper(), True, None
            if part == "A":
                module = None
            continue
        if not started:
            continue
        if m := _MODULE.match(text):
            token = m.group(1).upper()
            module = int(token) if token.isdigit() else _ROMAN.get(token)
            cur = None
            if not m.group(2).strip():
                continue
            text = m.group(2).strip()
        if _INSTRUCTION.match(text) or _NOISE.match(text) or b.label == "header":
            continue
        if m := _ONLY_MARKS.match(text):
            if cur is not None and cur.marks is None:
                cur.marks = float(m.group(1))
            continue

        parsed: tuple[int, str | None, str] | None = None
        if m := _QSTART_TIGHT.match(text):
            parsed = (int(m.group(1)), m.group(2), m.group(3))
        elif m := _QSTART.match(text):
            parsed = (int(m.group(1)), m.group(2) or m.group(3), m.group(4))
        if parsed:
            number, sub, body = parsed
            forward = cur is None or number > cur.number or (number == cur.number and sub and sub != cur.sub)
            # OCR sometimes repeats earlier lines; a separate block that starts with an
            # earlier number followed by a word is a repeat, kept so normalize() can dedupe.
            repeat = (
                cur is not None
                and not forward
                and b.label == "text"
                and re.match(r"[A-Za-z]{3,}", body or "") is not None
            )
            if 1 <= number <= 20 and (forward or repeat):
                start(number, sub.lower() if sub else None, body, b)
                continue
        if (m := _SUBSTART.match(text)) and cur is not None:
            sub = m.group(1).lower()
            if sub != (cur.sub or ""):
                start(cur.number, sub, m.group(2), b)
                continue
        if cur is not None:
            body, marks = _strip_marks(text)
            cur.text = (cur.text + " " + body).strip()
            cur.bbox = _union(cur.bbox, b.bbox) if cur.page == b.page else cur.bbox
            if marks is not None and cur.marks is None:
                cur.marks = marks

    # A question whose later parts are lettered but whose first part is not → first is (a).
    lettered = {e.number for e in entries if e.sub}
    for e in entries:
        if e.sub is None and e.number in lettered:
            e.sub = "a"

    out: list[TranscriptQuestion] = []
    for e in entries:
        has_diagram = e.has_diagram or bool(re.search(r"\b(figure|diagram|fig\.)\b", e.text, re.IGNORECASE))
        out.append(
            TranscriptQuestion(
                part=e.part, number=e.number, sub=e.sub, marks=e.marks, text=e.text.strip(),
                module=e.module, has_diagram=has_diagram, page=e.page, bbox=e.bbox, provider="local_ocr",
            )
        )
    return out


def _parse_mcq(blocks: list[Block], max_number: int) -> list[TranscriptQuestion]:
    """
    MCQ papers: no PART heading; questions 1..N in order, each followed by options a)-d).
    A new question must be the next number, or jump a few the OCR lost when the line starts
    in the question-number column — option texts like "16 units" must not start question 16.
    """
    entries: list[_Entry] = []
    cur: _Entry | None = None
    # Left edge of the question-number column per page (scans are shifted differently on each
    # page): the leftmost block on that page that starts like a question.
    q_col: dict[int, float] = {}
    for b in blocks:
        if _QSTART.match(b.text.strip()):
            q_col[b.page] = min(q_col.get(b.page, b.bbox[0]), b.bbox[0])
    for b in blocks:
        text = b.text.strip()
        if not text or b.label in _SKIP_LABELS:
            continue
        if b.label in _DIAGRAM_LABELS:
            if cur is not None:
                cur.has_diagram = True
            continue
        if _NOISE.match(text) or b.label == "header":
            continue
        m = _QSTART.match(text)
        if m:
            number, sub, body = int(m.group(1)), m.group(2) or m.group(3), m.group(4)
            # Next number, or a jump over questions the OCR lost (often at page ends) — but only from
            # the question-number column: options sit further right, so "16 units" cannot start Q16.
            in_number_column = b.bbox[0] <= q_col.get(b.page, 0.0) + 25
            if cur is None:
                ok = in_number_column  # the first pages may have been lost by the OCR
            else:
                ok = number == cur.number + 1 or (cur.number + 1 < number <= cur.number + 12 and in_number_column)
            if ok and number <= max_number:
                cur = _Entry(number, None, f"{sub}) {body}" if sub else body, None, None, "A", b.page, list(b.bbox))
                entries.append(cur)
                continue
        if cur is None:
            continue  # header / instructions before Q1
        cur.text = (cur.text + " " + text).strip()
        cur.bbox = _union(cur.bbox, b.bbox) if cur.page == b.page else cur.bbox

    out: list[TranscriptQuestion] = []
    for e in entries:
        stem, opts = split_options(e.text)
        out.append(TranscriptQuestion(
            part="A", number=e.number, sub=None, marks=None, text=stem or e.text.strip(), options=opts or None,
            has_diagram=e.has_diagram or bool(re.search(r"\b(figure|diagram|fig\.)\b", e.text, re.IGNORECASE)),
            page=e.page, bbox=e.bbox, provider="local_ocr",
        ))
    return out


def parse_pages(raw_pages: list[str], model: str | None = None, mcq: bool = False) -> Transcript:
    blocks: list[Block] = []
    for i, raw in enumerate(raw_pages):
        blocks.extend(parse_blocks(raw, page=i))
    return Transcript(
        header=parse_header(blocks, mcq),
        questions=parse_questions(blocks, mcq),
        provider="local_ocr",
        model=model,
        pages=len(raw_pages),
    )
