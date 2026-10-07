"""
Rolling-origin backtest (docs/PLAN-v2.md §6.4).

For each paper t after a warm-up, everything is fitted on papers strictly before t and
scored on t. Baselines: unweighted frequency (λ = 1) and a uniform rate; prep sets are
compared against the frequency-ranked top-k and the exact expectation of a random set.
"""

import itertools
import statistics

from app.services.exam_templates import ExamTemplate
from app.services.insights import (
    PaperRow,
    QRow,
    TopicDef,
    best_sets,
    module_dataset,
    posterior,
    presence,
    score_set,
    sorted_papers,
)


def _brier(probs: dict[str, float], actual: set[str]) -> float:
    return statistics.fmean((p - (1.0 if t in actual else 0.0)) ** 2 for t, p in probs.items())


def _recall_at_k(probs: dict[str, float], actual: set[str]) -> float | None:
    if not actual:
        return None
    k = len(actual)
    top = [t for t, _ in sorted(probs.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]
    return len(actual & set(top)) / k


def run_backtest(
    template: ExamTemplate,
    modules: list[dict],
    topics: list[TopicDef],
    papers: list[PaperRow],
    questions: list[QRow],
    lam: float = 0.8,
    warmup: int = 4,
    k: int = 2,
) -> dict:
    papers = sorted_papers(papers)
    topic_ids = [t.id for t in topics]
    rows = []
    for idx in range(warmup, len(papers)):
        train, test = papers[:idx], papers[idx]
        train_ids = {p.paper_id for p in train}
        q_train = [q for q in questions if q.paper_id in train_ids]
        q_test = [q for q in questions if q.paper_id == test.paper_id]
        actual = {t for q in q_test for t in q.topics}
        if not actual:
            continue
        pres = presence(train, q_train)
        p_model = {t: v[0] for t, v in posterior(train, pres, topic_ids, lam).items()}
        p_freq = {t: v[0] for t, v in posterior(train, pres, topic_ids, 1.0).items()}
        base_rate = statistics.fmean(len(pres.get(t, set())) / len(train) for t in topic_ids)
        p_uniform = {t: base_rate for t in topic_ids}

        prep = {"model_full": [], "model_marks": [], "freq_full": [], "freq_marks": [], "random_full": [], "random_marks": []}
        for m in modules:
            m_topics = [t.id for t in topics if t.module == m["no"]]
            data_train = module_dataset(template, m["no"], train, q_train)
            data_test = module_dataset(template, m["no"], [test], q_test)
            if not data_train or not data_test or len(m_topics) < k:
                continue
            kk = min(k, len(m_topics))
            chosen = best_sets(m_topics, data_train, kk, {t: p_model[t] for t in m_topics})[-1]["topics"]
            full, marks, _ = score_set(frozenset(chosen), data_test)
            prep["model_full"].append(full)
            prep["model_marks"].append(marks)
            freq_top = sorted(m_topics, key=lambda t: (-p_freq[t], t))[:kk]
            f_full, f_marks, _ = score_set(frozenset(freq_top), data_test)
            prep["freq_full"].append(f_full)
            prep["freq_marks"].append(f_marks)
            combos = list(itertools.combinations(m_topics, kk))
            scores = [score_set(frozenset(c), data_test) for c in combos]
            prep["random_full"].append(statistics.fmean(s[0] for s in scores))
            prep["random_marks"].append(statistics.fmean(s[1] for s in scores))

        rows.append({
            "paper_id": test.paper_id,
            "label": test.label,
            "trained_on": len(train),
            "topics_present": len(actual),
            "brier": {"model": _brier(p_model, actual), "frequency": _brier(p_freq, actual), "uniform": _brier(p_uniform, actual)},
            "recall_at_k": {"model": _recall_at_k(p_model, actual), "frequency": _recall_at_k(p_freq, actual)},
            "prep_set": {key: (statistics.fmean(v) if v else None) for key, v in prep.items()},
        })

    def avg(path: list[str]) -> float | None:
        vals = []
        for r in rows:
            v = r
            for p in path:
                v = v.get(p) if isinstance(v, dict) else None
            if isinstance(v, (int, float)):
                vals.append(v)
        return round(statistics.fmean(vals), 4) if vals else None

    summary = {
        "evaluated_papers": len(rows),
        "warmup": warmup,
        "k": k,
        "lambda": lam,
        "brier": {m: avg(["brier", m]) for m in ("model", "frequency", "uniform")},
        "recall_at_k": {m: avg(["recall_at_k", m]) for m in ("model", "frequency")},
        "prep_set": {m: avg(["prep_set", m]) for m in prep_keys()},
    }
    summary["verdict"] = verdict(summary)
    return {"summary": summary, "rows": rows}


def prep_keys() -> list[str]:
    return ["model_full", "model_marks", "freq_full", "freq_marks", "random_full", "random_marks"]


def verdict(s: dict) -> str:
    n = s["evaluated_papers"]
    if n == 0:
        return "Not enough papers to backtest yet (need more than the warm-up)."
    b = s["brier"]
    ps = s["prep_set"]
    parts = [f"Scored on {n} past paper{'s' if n != 1 else ''}, each predicted only from the papers before it."]
    if b["model"] is not None and b["frequency"] is not None:
        diff = b["frequency"] - b["model"]
        better = "better than" if diff > 0.002 else ("worse than" if diff < -0.002 else "about the same as")
        if s["lambda"] == 1.0:
            parts.append(f"Plain frequency predicted best (Brier {b['model']:.3f} vs {b['uniform']:.3f} for a uniform guess; lower is better), so no recency weighting is applied.")
        else:
            parts.append(f"Recency weighting (λ = {s['lambda']}) is {better} plain frequency (Brier {b['model']:.3f} vs {b['frequency']:.3f}; lower is better).")
    if ps.get("model_full") is not None and ps.get("random_full") is not None:
        parts.append(
            f"A {s['k']}-topic prep set per module would have covered a full question in "
            f"{ps['model_full'] * 100:.0f}% of modules (frequency top-{s['k']}: {ps['freq_full'] * 100:.0f}%, "
            f"random {s['k']} topics: {ps['random_full'] * 100:.0f}%)."
        )
    if n < 5:
        parts.append("Few papers were evaluated, so treat these numbers as rough.")
    return " ".join(parts)
