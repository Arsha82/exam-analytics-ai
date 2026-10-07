"""
Topic + kind tagging against the course's closed taxonomy.

Questions are tagged per module in batches (the module is known from structure), so
one call sees many similar questions and labels them consistently. Labels outside the
module's topic list are discarded. If agy is unavailable, a keyword scorer gives
low-confidence labels that are marked for review.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import settings
from app.services.agy import AgyClient, AgyError, AgyUnavailable

KINDS = ("theory", "derivation", "problem")
BATCH = 60  # fewer, larger calls: latency, not tokens, dominates


@dataclass
class TagItem:
    id: str
    module: int
    text: str


@dataclass
class TagResult:
    id: str
    topics: list[tuple[str, float]]
    kind: str
    source: str  # agy / keyword


class _Label(BaseModel):
    id: str
    topics: list[str] = Field(default_factory=list)
    kind: str = "problem"
    confidence: float = 0.8


class _Reply(BaseModel):
    labels: list[_Label]


TAG_PROMPT = """Label each exam question with topics from this closed list (module {module}: {module_title}).

Topics (id — name):
{topics}

Also give each question a kind:
- "theory": define / state / write / list / explain / assumptions, no working needed
- "derivation": derive / prove / show that, a general result
- "problem": solve / find / evaluate / expand / determine with given data

Questions:
{questions}

Reply with only this JSON:
{{"labels": [{{"id": "q1", "topics": ["t2"], "kind": "problem", "confidence": 0.9}}]}}
(kind is "theory", "derivation" or "problem"; confidence 0..1.) One label per question id,
1-3 topic ids each, main topic first. No other keys, no prose."""


def kind_by_rules(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(derive|prove|show that|deduce|establish)\b", t):
        return "derivation"
    if re.search(r"\b(define|state|write|list|what is|explain|mention|assumptions?)\b", t) and not re.search(
        r"\b(solve|evaluate|find|determine|expand|compute|obtain)\b", t
    ):
        return "theory"
    return "problem"


def keyword_tags(item: TagItem, topics: list[dict]) -> TagResult:
    text = item.text.lower()
    scored: list[tuple[float, str]] = []
    for tp in topics:
        score = 0.0
        for kw in tp.get("keywords", []):
            if kw.lower() in text:
                score += 1.0 + len(kw) / 40
        name_words = [w for w in re.findall(r"[a-z]{5,}", tp["name"].lower())]
        score += 0.3 * sum(w in text for w in name_words)
        if score > 0:
            scored.append((score, tp["id"]))
    scored.sort(reverse=True)
    chosen = [(tid, 0.4) for _s, tid in scored[:1]]
    return TagResult(item.id, chosen, kind_by_rules(item.text), "keyword")


async def tag_module(
    client: AgyClient,
    module_no: int,
    module_title: str,
    topics: list[dict],
    items: list[TagItem],
    workspace: Path,
    use_agy: bool = True,
    on_event=None,
) -> list[TagResult]:
    # Short ids (t1.., q1..) in the prompt and reply: the JSON reply is the main token cost.
    short_topic = {f"t{i + 1}": t["id"] for i, t in enumerate(topics)}
    allowed = set(short_topic)
    results: dict[str, TagResult] = {}
    if use_agy:
        topic_lines = "\n".join(f"- {sid} — {t['name']}" for sid, t in zip(short_topic, topics))
        for start in range(0, len(items), BATCH):
            batch = items[start : start + BATCH]
            short_q = {f"q{i + 1}": it for i, it in enumerate(batch)}
            q_lines = "\n".join(f"- {sid}: {it.text[:500]}" for sid, it in short_q.items())
            prompt = TAG_PROMPT.format(module=module_no, module_title=module_title, topics=topic_lines, questions=q_lines)
            try:
                reply, _ = await client.run_json(
                    prompt, _Reply, agent="pyq-tagger", model=settings.agy_tagger_model, cwd=workspace,
                    fallback_model=settings.agy_fallback_model, on_event=on_event,
                )
            except AgyUnavailable as exc:
                if on_event:
                    await on_event("warn", f"agy unavailable for tagging ({exc}); using keyword fallback", None)
                break
            except AgyError as exc:
                if on_event:
                    await on_event("warn", f"tagging batch failed ({exc}); using keyword fallback for it", None)
                continue
            for lab in reply.labels:
                item = short_q.get(lab.id)
                if item is None:
                    continue
                tps = [short_topic[t] for t in dict.fromkeys(lab.topics) if t in allowed][:3]
                if not tps:
                    continue
                conf = max(0.0, min(1.0, lab.confidence))
                kind = lab.kind if lab.kind in KINDS else kind_by_rules(item.text)
                results[item.id] = TagResult(item.id, [(t, conf if i == 0 else conf * 0.8) for i, t in enumerate(tps)], kind, "agy")
    for it in items:
        if it.id not in results:
            results[it.id] = keyword_tags(it, topics)
    return [results[it.id] for it in items]
