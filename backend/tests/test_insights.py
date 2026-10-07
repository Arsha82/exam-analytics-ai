import math

from app.services.backtest import run_backtest
from app.services.exam_templates import get_template
from app.services.insights import PaperRow, QRow, TopicDef, best_sets, compute, module_dataset, posterior, presence

T = get_template("ktu2019_theory_100")
MODULES = [{"no": i, "title": f"M{i}"} for i in range(1, 6)]
TOPICS = [TopicDef(f"m{m}.t{k}", m, f"M{m} topic {k}") for m in range(1, 6) for k in range(1, 4)]


def make_paper(pid: str, key: int, b_topics: dict[int, tuple[str, str, str, str]]):
    """b_topics[module] = topics of (Qa.a, Qa.b, Qb.a, Qb.b); Part A uses topic t1 of each module."""
    qs = []
    for m in range(1, 6):
        for n in T.part_a_for_module(m):
            qs.append(QRow(f"{pid}_{n}", pid, "A", n, None, m, 3.0, [f"m{m}.t1"], "theory", f"define {m}"))
        n1, n2 = T.part_b_pairs(m)
        t = b_topics.get(m, (f"m{m}.t1", f"m{m}.t2", f"m{m}.t2", f"m{m}.t3"))
        qs += [
            QRow(f"{pid}_{n1}a", pid, "B", n1, "a", m, 7.0, [t[0]], "problem", f"solve {t[0]} {pid}"),
            QRow(f"{pid}_{n1}b", pid, "B", n1, "b", m, 7.0, [t[1]], "problem", f"solve {t[1]} {pid}"),
            QRow(f"{pid}_{n2}a", pid, "B", n2, "a", m, 7.0, [t[2]], "problem", f"solve {t[2]} {pid}"),
            QRow(f"{pid}_{n2}b", pid, "B", n2, "b", m, 7.0, [t[3]], "problem", f"solve {t[3]} {pid}"),
        ]
    return PaperRow(pid, key, pid), qs


def corpus(n: int = 6):
    papers, qs = [], []
    for i in range(n):
        p, q = make_paper(f"p{i}", 202000 + i * 100 + 12, {})
        papers.append(p)
        qs += q
    return papers, qs


def test_posterior_math():
    papers, qs = corpus(4)
    pres = presence(papers, qs)
    post = posterior(papers, pres, ["m1.t1", "m1.t3", "m9.none"], lam=1.0)
    # Present in all 4 papers, Laplace prior: (1+4)/(2+4)
    assert math.isclose(post["m1.t1"][0], 5 / 6)
    assert math.isclose(post["m9.none"][0], 1 / 6)
    # Recency: with λ<1 the newest paper counts more.
    papers2 = [PaperRow("old", 202012, "old"), PaperRow("new", 202112, "new")]
    q2 = [QRow("a", "new", "B", 11, "a", 1, 7, ["x"]), QRow("b", "old", "B", 11, "a", 1, 7, ["y"])]
    p2 = posterior(papers2, presence(papers2, q2), ["x", "y"], lam=0.5)
    assert p2["x"][0] > p2["y"][0]


def test_prep_set_finds_minimal_cover():
    papers, qs = corpus(5)
    data = module_dataset(T, 1, papers, qs)
    sets = best_sets(["m1.t1", "m1.t2", "m1.t3"], data, 3)
    # Q11 = (t1, t2) is always fully answerable with {t1, t2}.
    two = sets[1]
    assert set(two["topics"]) == {"m1.t1", "m1.t2"} and two["full_coverage"] == 1.0
    assert two["expected_part_b_marks"] == 14.0 and two["part_a_marks"] == 6.0
    one = sets[0]
    assert one["full_coverage"] == 0.0 and one["expected_part_b_marks"] == 7.0


def test_compute_and_repeats():
    papers, qs = corpus(3)
    qs.append(QRow("p0_rep", "p0", "B", 11, "c", 1, 0.0, ["m1.t3"], "problem", "Find the Laurent series of 1/(z^2-1) valid in 1<|z|<2"))
    qs.append(QRow("p2_rep", "p2", "B", 11, "c", 1, 0.0, ["m1.t3"], "problem", "Find the Laurent series of 1/(z^2-1) valid in 1<|z|<2"))
    res = compute(T, MODULES, TOPICS, papers, qs)
    assert res["n_papers"] == 3
    t1 = next(t for t in res["topics"] if t["topic_id"] == "m1.t1")
    assert t1["appearance_rate"] == 1.0 and t1["part_a_rate"] == 1.0
    assert any(c["relation"] == "repeat" and c["times"] == 2 for c in res["repeats"])
    assert res["modules"][0]["prep_sets"][1]["full_coverage"] == 1.0


def test_backtest_beats_random_on_stable_pattern():
    papers, qs = corpus(7)
    bt = run_backtest(T, MODULES, TOPICS, papers, qs, warmup=4, k=2)
    s = bt["summary"]
    assert s["evaluated_papers"] == 3
    assert s["prep_set"]["model_full"] == 1.0
    assert s["prep_set"]["random_full"] < 1.0
    assert "Scored on 3 past papers" in s["verdict"]
