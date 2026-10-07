"""
Mock papers: practice papers assembled from real past questions.

Every slot of the KTU template is filled from the question bank of its module: two
Part A questions per module and two complete either/or Part B questions per module
(whole questions with their sub-parts, from different papers). Selection is weighted by
the course's topic probabilities ("likely"), even across topics ("balanced"), or toward
topics not yet practised ("fresh"). The result is checked with the same validator as the
real papers, so a mock paper is structurally a real paper.
"""

import random
import re
from dataclasses import dataclass, field

from app.services.exam_templates import ExamTemplate, validate
from app.services.transcript import Transcript, TranscriptHeader, TranscriptQuestion


@dataclass
class BankQuestion:
    question_id: str
    paper_id: str
    paper_label: str
    part: str
    number: int
    sub: str | None
    module: int
    marks: float
    text: str
    topics: list[str] = field(default_factory=list)
    kind: str | None = None
    clean: bool = True
    options: list[str] | None = None  # MCQ papers


class MockPaperError(ValueError):
    pass


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z]+", " ", text.lower())).strip()


def _weight(topics: list[str], probs: dict[str, float], focus: str, seen: set[str]) -> float:
    if focus == "balanced" or not topics:
        return 1.0
    if focus == "fresh":
        return 0.25 if all(t in seen for t in topics) else 1.0
    return 0.05 + max(probs.get(t, 0.0) for t in topics)


def _pick(rng: random.Random, items: list, weights: list[float], k: int, distinct=lambda chosen, x: True) -> list:
    pool = list(zip(items, weights))
    chosen: list = []
    while pool and len(chosen) < k:
        total = sum(w for _x, w in pool)
        r = rng.uniform(0, total)
        acc = 0.0
        for i, (x, w) in enumerate(pool):
            acc += w
            if acc >= r:
                pool.pop(i)
                if distinct(chosen, x):
                    chosen.append(x)
                break
    return chosen


def assemble(template: ExamTemplate, course_code: str, bank: list[BankQuestion], probs: dict[str, float],
             focus: str = "likely", seed: int | None = None, practised: set[str] | None = None) -> list[dict]:
    rng = random.Random(seed)
    practised = practised or set()
    if template.is_mcq:
        return _assemble_mcq(template, course_code, bank, probs, focus, rng, practised)
    items: list[dict] = []
    for module in range(1, template.modules + 1):
        # Part A: two questions, different topics and texts.
        a_pool = [q for q in bank if q.part == "A" and q.module == module and q.clean and len(q.text) >= 12]
        uniq: dict[str, BankQuestion] = {}
        for q in a_pool:
            uniq.setdefault(_norm(q.text), q)
        a_pool = list(uniq.values())
        a_pick = _pick(rng, a_pool, [_weight(q.topics, probs, focus, practised) for q in a_pool], 2,
                       distinct=lambda ch, x: all(set(x.topics).isdisjoint(c.topics) or not x.topics for c in ch))
        if len(a_pick) < 2:  # relax the distinct-topic rule if the bank is thin
            a_pick += [q for q in a_pool if q not in a_pick][: 2 - len(a_pick)]
        if len(a_pick) < 2:
            raise MockPaperError(f"Module {module}: not enough clean Part A questions")
        for slot, q in zip(template.part_a_for_module(module), a_pick):
            items.append(_item(q, slot, None, "A", module))

        # Part B: two whole questions (all sub-parts), from different papers.
        groups: dict[tuple[str, int], list[BankQuestion]] = {}
        for q in bank:
            if q.part == "B" and q.module == module:
                groups.setdefault((q.paper_id, q.number), []).append(q)
        complete = [g for g in groups.values()
                    if all(p.clean for p in g) and abs(sum(p.marks for p in g) - template.part_b_marks) < 1e-6]
        weights = [_weight(sorted({t for p in g for t in p.topics}), probs, focus, practised) for g in complete]
        b_pick = _pick(rng, complete, weights, 2, distinct=lambda ch, g: all(c[0].paper_id != g[0].paper_id for c in ch))
        if len(b_pick) < 2:
            raise MockPaperError(f"Module {module}: not enough complete Part B questions from different papers")
        for slot, g in zip(template.part_b_pairs(module), b_pick):
            for p in sorted(g, key=lambda p: p.sub or ""):
                items.append(_item(p, slot, p.sub, "B", module))

    check = validate(template, Transcript(
        header=TranscriptHeader(course_code=course_code, max_marks=template.total_marks, month=1, year=2100),
        questions=[TranscriptQuestion(part=i["part"], number=i["number"], sub=i["sub"], marks=i["marks"], text=i["text"])
                   for i in items]), course_code)
    errors = [i for i in check if i.level == "error"]
    if errors:
        raise MockPaperError("; ".join(e.message for e in errors))
    return sorted(items, key=lambda i: (i["number"], i["sub"] or ""))


def _assemble_mcq(template: ExamTemplate, course_code: str, bank: list[BankQuestion], probs: dict[str, float],
                  focus: str, rng: random.Random, practised: set[str]) -> list[dict]:
    """MCQ papers: each block of the template (one per earlier course) gets its share of distinct
    questions that have all their options."""
    items: list[dict] = []
    per = len(template.part_a_numbers) // template.modules
    for module in range(1, template.modules + 1):
        pool = [q for q in bank if q.module == module and q.clean and len(q.options or []) == template.options
                and len(q.text) >= 8]
        uniq: dict[str, BankQuestion] = {}
        for q in pool:
            uniq.setdefault(_norm(q.text), q)
        pool = list(uniq.values())
        pick = _pick(rng, pool, [_weight(q.topics, probs, focus, practised) for q in pool], per)
        if len(pick) < per:
            raise MockPaperError(f"Section {module}: only {len(pick)} clean questions with all options (need {per})")
        for slot, q in zip(template.part_a_for_module(module), pick):
            items.append(_item(q, slot, None, "A", module))
    check = validate(template, Transcript(
        header=TranscriptHeader(course_code=course_code, max_marks=template.total_marks, month=1, year=2100),
        questions=[TranscriptQuestion(part="A", number=i["number"], marks=i["marks"], text=i["text"], options=i["options"])
                   for i in items]), course_code)
    errors = [i for i in check if i.level == "error"]
    if errors:
        raise MockPaperError("; ".join(e.message for e in errors))
    return sorted(items, key=lambda i: i["number"])


def _item(q: BankQuestion, number: int, sub: str | None, part: str, module: int) -> dict:
    return {"number": number, "sub": sub, "part": part, "module": module, "marks": q.marks, "text": q.text,
            "options": q.options,
            "topics": q.topics, "kind": q.kind, "question_id": q.question_id,
            "source": f"{q.paper_label} · Q{q.number}{q.sub or ''}"}
