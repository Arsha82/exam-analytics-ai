"""
Exam templates and the deterministic validator.

A template describes how a university lays out a question paper (sections, question
numbers, marks, either/or pairs, which module each position belongs to). The module
of a question is read from its position — ground truth — instead of being guessed.
"""

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.services.transcript import Issue, Transcript, TranscriptQuestion


@dataclass(frozen=True)
class ExamTemplate:
    id: str
    total_marks: int
    part_a_numbers: tuple[int, ...]
    part_a_marks: float
    part_b_numbers: tuple[int, ...]
    part_b_marks: float
    modules: int
    first_valid_year: int
    kind: str = "theory"  # theory: Part A short + Part B either/or; mcq: numbered questions with options
    options: int = 0  # mcq: printed options per question (a-d)
    max_pages: int = 6  # longer files are solved papers / compilations (only their first pages are read)
    ocr_strips: int = 0  # >1: OCR each page as that many horizontal strips (dense pages loop when read whole)

    @property
    def is_mcq(self) -> bool:
        return self.kind == "mcq"

    def part_of(self, number: int) -> str | None:
        if number in self.part_a_numbers:
            return "A"
        if number in self.part_b_numbers:
            return "B"
        return None

    def module_of(self, number: int) -> int | None:
        """Structural module for a question number (KTU: 2 per module in each part)."""
        if number in self.part_a_numbers:
            idx = self.part_a_numbers.index(number)
            return idx // (len(self.part_a_numbers) // self.modules) + 1
        if number in self.part_b_numbers:
            idx = self.part_b_numbers.index(number)
            return idx // (len(self.part_b_numbers) // self.modules) + 1
        return None

    def choice_pair(self, number: int) -> tuple[int, int] | None:
        """Either/or partner pair in Part B, e.g. 13 -> (13, 14)."""
        if number not in self.part_b_numbers:
            return None
        idx = self.part_b_numbers.index(number)
        first = self.part_b_numbers[idx - idx % 2]
        return (first, first + 1)

    def part_b_pairs(self, module_no: int) -> tuple[int, int] | None:
        if not self.part_b_numbers:
            return None
        first = self.part_b_numbers[(module_no - 1) * 2]
        return (first, first + 1)

    def part_a_for_module(self, module_no: int) -> tuple[int, ...]:
        per = len(self.part_a_numbers) // self.modules
        return self.part_a_numbers[(module_no - 1) * per : module_no * per]


TEMPLATES: dict[str, ExamTemplate] = {
    "ktu2019_theory_100": ExamTemplate(
        id="ktu2019_theory_100",
        total_marks=100,
        part_a_numbers=tuple(range(1, 11)),
        part_a_marks=3.0,
        part_b_numbers=tuple(range(11, 21)),
        part_b_marks=14.0,
        modules=5,
        first_valid_year=2020,
    ),
    # KTU 2019 "Comprehensive Course Work" (e.g. CST308/ADT308): 50 one-mark MCQs, four options,
    # in five blocks of ten — one block per earlier course, so the block is the "module".
    "ktu2019_mcq_50": ExamTemplate(
        id="ktu2019_mcq_50",
        total_marks=50,
        part_a_numbers=tuple(range(1, 51)),
        part_a_marks=1.0,
        part_b_numbers=(),
        part_b_marks=0.0,
        modules=5,
        first_valid_year=2020,
        kind="mcq",
        options=4,
        max_pages=10,
        ocr_strips=3,
    ),
}


def get_template(template_id: str) -> ExamTemplate:
    try:
        return TEMPLATES[template_id]
    except KeyError as exc:
        raise ValueError(f"Unknown exam template '{template_id}'") from exc


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z]+", " ", text.lower())).strip()


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def normalize_questions(
    template: ExamTemplate, questions: list[TranscriptQuestion]
) -> list[TranscriptQuestion]:
    """
    Assign part/module from structure, drop OCR-duplicated entries, sort by position.

    A slot (number+sub) exists once on a paper, so repeated entries are OCR re-reads:
    the first occurrence wins, takes marks from a later copy if it lacks them, and is
    marked partly unclear when the copies disagree (so it gets re-read/repaired).
    """
    kept: list[TranscriptQuestion] = []
    for q in questions:
        part = template.part_of(q.number)
        if part is None:
            kept.append(q)
            continue
        q = q.model_copy(update={"part": part})
        dup = next(
            (k for k in kept if k.number == q.number and (k.sub or "") == (q.sub or "")),
            None,
        )
        if dup is not None:
            update: dict = {}
            if dup.marks is None and q.marks is not None:
                update["marks"] = q.marks
            if _similar(dup.text, q.text) < 0.97 and dup.legibility == "clear":
                # The OCR read the same slot twice with different wording: trust neither copy.
                update["legibility"] = "partly_unclear"
            if update:
                kept[kept.index(dup)] = dup.model_copy(update=update)
            continue
        kept.append(q)

    # Marks the template fixes are filled in (and marked inferred): Part A is always 3;
    # in Part B, a single part without marks gets 14 minus its siblings.
    out = []
    for q in kept:
        if q.part == "A" and q.marks is None:
            q = q.model_copy(update={"marks": template.part_a_marks, "marks_inferred": True})
        elif q.part == "B" and q.marks is None:
            siblings = [k for k in kept if k.number == q.number and k is not q]
            unknown = [k for k in siblings if k.marks is None]
            rest = template.part_b_marks - sum(k.marks or 0 for k in siblings)
            if not unknown and rest > 0:
                q = q.model_copy(update={"marks": rest, "marks_inferred": True})
        out.append(q)
    out.sort(key=lambda q: (q.number, q.sub or ""))
    return out


def validate(template: ExamTemplate, transcript: Transcript, course_code: str) -> list[Issue]:
    """Rules B01-B07, B11 for MCQ options (see docs/PLAN-v2.md §6.5). Pure function."""
    issues: list[Issue] = []
    h = transcript.header

    code = (h.course_code or "").replace(" ", "").upper()
    if not code:
        issues.append(Issue(code="B01", level="warn", message="Course code not found on the paper"))
    elif code != course_code.replace(" ", "").upper():
        issues.append(
            Issue(code="B01", level="error", message=f"Paper is for {h.course_code}, not {course_code}")
        )

    if h.max_marks is not None and h.max_marks != template.total_marks:
        issues.append(
            Issue(code="B02", level="error", message=f"Max marks {h.max_marks} ≠ {template.total_marks}")
        )

    if h.year is None or h.month is None:
        issues.append(Issue(code="B07", level="warn", message="Exam session (month/year) not found"))
    elif not (template.first_valid_year <= h.year <= 2100) or not (1 <= h.month <= 12):
        issues.append(
            Issue(code="B07", level="error", message=f"Implausible session {h.month}/{h.year} for this scheme")
        )

    by_number: dict[int, list[TranscriptQuestion]] = {}
    for q in transcript.questions:
        by_number.setdefault(q.number, []).append(q)
        if template.part_of(q.number) is None:
            issues.append(
                Issue(code="B04", level="warn", message=f"Unexpected question number {q.number}", number=q.number)
            )

    # Part A: every number present, 3 marks each, no sub-parts expected.
    for n in template.part_a_numbers:
        entries = by_number.get(n, [])
        if not entries:
            issues.append(Issue(code="B03", level="error", message=f"Part A question {n} missing", number=n))
            continue
        marks = sum(q.marks or 0 for q in entries)
        if not math.isclose(marks, template.part_a_marks):
            issues.append(
                Issue(
                    code="B03",
                    level="error",
                    message=f"Q{n} marks {marks:g} ≠ {template.part_a_marks:g}",
                    number=n,
                )
            )

    # Part B: every number present, sub-part marks sum to 14.
    for n in template.part_b_numbers:
        entries = by_number.get(n, [])
        if not entries:
            issues.append(Issue(code="B04", level="error", message=f"Part B question {n} missing", number=n))
            continue
        if any(q.marks is None for q in entries):
            issues.append(Issue(code="B04", level="error", message=f"Q{n} has a part without marks", number=n))
            continue
        total = sum(q.marks or 0 for q in entries)
        if not math.isclose(total, template.part_b_marks):
            issues.append(
                Issue(
                    code="B04",
                    level="error",
                    message=f"Q{n} parts sum to {total:g}, expected {template.part_b_marks:g}",
                    number=n,
                )
            )
        subs = [q.sub for q in entries]
        if len(entries) > 1 and len(set(subs)) != len(subs):
            issues.append(
                Issue(code="B04", level="warn", message=f"Q{n} has repeated sub-part labels {subs}", number=n)
            )

    if template.is_mcq:
        prev: TranscriptQuestion | None = None
        for q in sorted(transcript.questions, key=lambda x: x.number):
            n_opt = len(q.options or [])
            if n_opt != template.options:
                issues.append(Issue(code="B11", level="error", number=q.number,
                                    message=f"Q{q.number} has {n_opt} option(s), expected {template.options}"))
            elif prev is not None and [_norm(o) for o in q.options] == [_norm(o) for o in (prev.options or [])]:
                # A looping OCR copies the previous question's options; real papers never repeat them.
                issues.append(Issue(code="B11", level="warn", number=q.number,
                                    message=f"Q{q.number} options are identical to Q{prev.number}'s (OCR repeat?)"))
            prev = q

    for q in transcript.questions:
        structural = template.module_of(q.number)
        if q.module is not None and structural is not None and q.module != structural:
            issues.append(
                Issue(
                    code="B05",
                    level="warn",
                    message=f"Q{q.number} printed under Module {q.module}, position says Module {structural}",
                    number=q.number,
                    sub=q.sub,
                )
            )
        if q.legibility != "clear" or "[unclear]" in q.text:
            issues.append(
                Issue(
                    code="B06",
                    level="warn",
                    message=f"Q{q.number}{q.sub or ''} text is {q.legibility.replace('_', ' ')}",
                    number=q.number,
                    sub=q.sub,
                )
            )
        if len(_norm(q.text)) < 8:
            issues.append(
                Issue(code="B06", level="warn", message=f"Q{q.number}{q.sub or ''} text looks truncated",
                      number=q.number, sub=q.sub)
            )

    return issues


def flagged_slots(issues: list[Issue]) -> set[int]:
    """Question numbers whose transcription should be repaired by a stronger reader."""
    return {i.number for i in issues if i.number is not None and i.code in {"B03", "B04", "B06", "B11"}}


def repair_order(issues: list[Issue], slots: set[int]) -> list[int]:
    """Slots ordered for a limited repair budget: errors (missing, wrong marks) before warnings."""
    rank: dict[int, int] = {}
    for i in issues:
        if i.number in slots:
            r = 0 if i.level == "error" else 1
            rank[i.number] = min(rank.get(i.number, 9), r)
    return sorted(slots, key=lambda n: (rank.get(n, 9), n))
