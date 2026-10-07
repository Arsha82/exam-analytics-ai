"""
Course insights — pure functions over plain rows (no DB, no models).

See docs/PLAN-v2.md §6: appearance rate, recency-weighted Beta posterior, minimum prep
set (exhaustive per module), question kinds, repeats. Every number here is
reproducible from the questions table.
"""

import itertools
import math
import re
from dataclasses import dataclass, field

from app.services.exam_templates import ExamTemplate


@dataclass
class PaperRow:
    paper_id: str
    session_key: int  # year*100+month
    label: str


@dataclass
class QRow:
    question_id: str
    paper_id: str
    part: str
    number: int
    sub: str | None
    module: int
    marks: float
    topics: list[str] = field(default_factory=list)
    kind: str | None = None
    text: str = ""


@dataclass
class TopicDef:
    id: str
    module: int
    name: str


def sorted_papers(papers: list[PaperRow]) -> list[PaperRow]:
    return sorted(papers, key=lambda p: (p.session_key, p.paper_id))


def presence(papers: list[PaperRow], questions: list[QRow]) -> dict[str, set[str]]:
    """topic_id -> set of paper_ids where it appears."""
    out: dict[str, set[str]] = {}
    for q in questions:
        for t in q.topics:
            out.setdefault(t, set()).add(q.paper_id)
    return out


def recency_weights(papers: list[PaperRow], lam: float) -> dict[str, float]:
    """Weight λ^(age in sessions); papers of the same session share a weight."""
    sessions = sorted({p.session_key for p in papers})
    rank = {s: i for i, s in enumerate(sessions)}
    last = len(sessions) - 1
    return {p.paper_id: lam ** (last - rank[p.session_key]) for p in papers}


def posterior(
    papers: list[PaperRow], pres: dict[str, set[str]], topic_ids: list[str], lam: float = 0.8,
    alpha: float = 1.0, beta: float = 1.0,
) -> dict[str, tuple[float, float]]:
    """topic -> (mean, sd) of the Beta posterior for 'appears in the next paper'."""
    w = recency_weights(papers, lam)
    total = sum(w.values())
    out: dict[str, tuple[float, float]] = {}
    for t in topic_ids:
        hit = sum(w[pid] for pid in pres.get(t, set()) if pid in w)
        a, b = alpha + hit, beta + (total - hit)
        mean = a / (a + b)
        sd = math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
        out[t] = (mean, sd)
    return out


# ── minimum prep set ──

def module_choices(template: ExamTemplate, module: int, paper_qs: list[QRow]) -> list[list[tuple[float, frozenset[str]]]] | None:
    """The two either/or choices of a module in one paper as [(marks, topics) per sub-part].
    MCQ papers have no choice: the module's whole block of questions is the one "choice"."""
    pairs = template.part_b_pairs(module)
    if pairs is None:
        block = [(q.marks, frozenset(q.topics)) for q in paper_qs if q.module == module]
        return [block] if block else None
    n1, n2 = pairs
    choices = []
    for n in (n1, n2):
        parts = [(q.marks, frozenset(q.topics)) for q in paper_qs if q.number == n]
        if not parts:
            return None
        choices.append(parts)
    return choices


def _covered(topics: frozenset[str], s: frozenset[str]) -> bool:
    return bool(topics) and topics <= s


def score_set(
    s: frozenset[str], per_paper: list[tuple[list, list[tuple[float, frozenset[str]]]]]
) -> tuple[float, float, float]:
    """(full-choice coverage, mean Part B marks of 14, mean Part A marks) over papers."""
    if not per_paper:
        return 0.0, 0.0, 0.0
    full = marks = part_a = 0.0
    for choices, a_qs in per_paper:
        best_full = any(all(_covered(t, s) for _m, t in ch) for ch in choices)
        best_marks = max(sum(m for m, t in ch if _covered(t, s)) for ch in choices)
        full += 1.0 if best_full else 0.0
        marks += best_marks
        part_a += sum(m for m, t in a_qs if _covered(t, s))
    n = len(per_paper)
    return full / n, marks / n, part_a / n


def module_dataset(template: ExamTemplate, module: int, papers: list[PaperRow], questions: list[QRow]):
    by_paper: dict[str, list[QRow]] = {}
    for q in questions:
        if q.module == module:
            by_paper.setdefault(q.paper_id, []).append(q)
    data = []
    for p in papers:
        qs = by_paper.get(p.paper_id, [])
        choices = module_choices(template, module, qs)
        if choices is None:
            continue
        # MCQ: the block already holds every question (counting them again as "Part A" would double them).
        a_qs = [] if template.is_mcq else [(q.marks, frozenset(q.topics)) for q in qs if q.part == "A"]
        data.append((choices, a_qs))
    return data


def best_sets(topic_ids: list[str], data, max_k: int, tiebreak: dict[str, float] | None = None) -> list[dict]:
    tiebreak = tiebreak or {}
    out = []
    for k in range(1, min(max_k, len(topic_ids)) + 1):
        best = None
        for combo in itertools.combinations(topic_ids, k):
            s = frozenset(combo)
            full, marks, part_a = score_set(s, data)
            key = (round(full, 6), round(marks, 6), round(part_a, 6), sum(tiebreak.get(t, 0) for t in combo))
            if best is None or key > best[0]:
                best = (key, combo, full, marks, part_a)
        _key, combo, full, marks, part_a = best
        out.append({"k": k, "topics": list(combo), "full_coverage": round(full, 4),
                    "expected_part_b_marks": round(marks, 2), "part_a_marks": round(part_a, 2)})
    return out


# ── repeats ──

def _tokens(text: str, mask_numbers: bool) -> set[str]:
    t = text.lower()
    t = re.sub(r"\\(left|right|quad|,|;|!)", " ", t)
    if mask_numbers:
        t = re.sub(r"\d+(\.\d+)?", "#", t)
    return set(re.findall(r"[a-z]+|#|\d+(?:\.\d+)?|\\[a-z]+|[=+\-^/*]", t))


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def repeat_clusters(questions: list[QRow], labels: dict[str, str], exact: float = 0.85, template: float = 0.7) -> list[dict]:
    qs = [q for q in questions if len(q.text) >= 15]
    parent = {q.question_id: q.question_id for q in qs}
    kind_of: dict[tuple[str, str], str] = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    toks = {q.question_id: (_tokens(q.text, False), _tokens(q.text, True)) for q in qs}
    for a, b in itertools.combinations(qs, 2):
        if a.paper_id == b.paper_id or a.module != b.module:
            continue
        ja = jaccard(toks[a.question_id][0], toks[b.question_id][0])
        jm = jaccard(toks[a.question_id][1], toks[b.question_id][1])
        rel = None
        if ja >= exact:
            rel = "repeat"
        elif jm >= template and set(a.topics) & set(b.topics) and a.kind == b.kind:
            rel = "template"
        if rel:
            parent[find(a.question_id)] = find(b.question_id)
            kind_of[(a.question_id, b.question_id)] = rel
    groups: dict[str, list[QRow]] = {}
    for q in qs:
        groups.setdefault(find(q.question_id), []).append(q)
    out = []
    for members in groups.values():
        if len({m.paper_id for m in members}) < 2:
            continue
        ids = {m.question_id for m in members}
        rels = {v for (x, y), v in kind_of.items() if x in ids and y in ids}
        out.append({
            "relation": "repeat" if rels == {"repeat"} else ("template" if rels == {"template"} else "mixed"),
            "module": members[0].module,
            "topics": sorted({t for m in members for t in m.topics}),
            "times": len({m.paper_id for m in members}),
            "questions": [
                {"question_id": m.question_id, "paper": labels.get(m.paper_id, m.paper_id),
                 "number": m.number, "sub": m.sub, "marks": m.marks, "text": m.text}
                for m in sorted(members, key=lambda m: labels.get(m.paper_id, ""))
            ],
        })
    out.sort(key=lambda c: (-c["times"], c["module"]))
    return out


# ── assembly ──

def compute(
    template: ExamTemplate,
    modules: list[dict],
    topics: list[TopicDef],
    papers: list[PaperRow],
    questions: list[QRow],
    lam: float = 0.8,
    max_k: int = 4,
) -> dict:
    papers = sorted_papers(papers)
    paper_ids = [p.paper_id for p in papers]
    labels = {p.paper_id: p.label for p in papers}
    questions = [q for q in questions if q.paper_id in labels]
    topic_ids = [t.id for t in topics]
    pres = presence(papers, questions)
    post = posterior(papers, pres, topic_ids, lam)
    n = len(papers)

    # Heatmap: marks per topic per paper (multi-topic questions split their marks).
    cells: dict[tuple[str, str], dict] = {}
    for q in questions:
        if not q.topics:
            continue
        share = q.marks / len(q.topics)
        for t in q.topics:
            c = cells.setdefault((t, q.paper_id), {"marks": 0.0, "a": 0, "b": 0, "q": []})
            c["marks"] += share
            c["a" if q.part == "A" else "b"] += 1
            c["q"].append(f"{q.number}{q.sub or ''}")

    topic_stats = []
    for t in topics:
        present = [pid for pid in paper_ids if pid in pres.get(t.id, set())]
        a_papers = {q.paper_id for q in questions if t.id in q.topics and q.part == "A"}
        b_papers = {q.paper_id for q in questions if t.id in q.topics and q.part == "B"}
        marks_total = sum(cells.get((t.id, pid), {}).get("marks", 0.0) for pid in paper_ids)
        last_idx = max((paper_ids.index(pid) for pid in present), default=None)
        mean, sd = post[t.id]
        topic_stats.append({
            "topic_id": t.id, "module": t.module, "name": t.name,
            "papers_with": len(present), "appearance_rate": round(len(present) / n, 4) if n else 0.0,
            "probability_next": round(mean, 4), "probability_sd": round(sd, 4),
            "part_a_rate": round(len(a_papers) / n, 4) if n else 0.0,
            "part_b_rate": round(len(b_papers) / n, 4) if n else 0.0,
            "total_marks": round(marks_total, 2),
            "avg_marks_when_present": round(marks_total / len(present), 2) if present else 0.0,
            "last_seen": labels[paper_ids[last_idx]] if last_idx is not None else None,
            "papers_since_last_seen": (n - 1 - last_idx) if last_idx is not None else None,
        })

    module_out = []
    for m in modules:
        mno = m["no"]
        m_topics = [t.id for t in topics if t.module == mno]
        data = module_dataset(template, mno, papers, questions)
        kinds: dict[str, dict[str, int]] = {"A": {}, "B": {}}
        for q in questions:
            if q.module == mno and q.kind:
                kinds[q.part][q.kind] = kinds[q.part].get(q.kind, 0) + 1
        module_out.append({
            "module": mno, "title": m["title"], "papers_evaluated": len(data),
            "prep_sets": best_sets(m_topics, data, max_k, {t: post[t][0] for t in m_topics}) if data else [],
            "kinds": kinds,
        })

    untagged = sum(1 for q in questions if not q.topics)
    return {
        "n_papers": n,
        "papers": [{"paper_id": p.paper_id, "label": p.label, "session_key": p.session_key} for p in papers],
        "params": {"lambda": lam, "alpha": 1.0, "beta": 1.0, "max_k": max_k},
        "questions_total": len(questions),
        "questions_untagged": untagged,
        "heatmap": [
            {"topic_id": t, "paper_id": pid, "marks": round(c["marks"], 2), "part_a": c["a"], "part_b": c["b"],
             "questions": c["q"]}
            for (t, pid), c in sorted(cells.items())
        ],
        "topics": topic_stats,
        "modules": module_out,
        "repeats": repeat_clusters(questions, labels),
    }
