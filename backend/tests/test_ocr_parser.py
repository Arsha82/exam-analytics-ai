from app.services.exam_templates import get_template, normalize_questions, validate
from app.services.extraction.ocr_parser import clean_math, looks_like_exam, parse_pages

T = get_template("ktu2019_theory_100")


def test_header_from_real_ocr(fixture_text):
    t = parse_pages([fixture_text("mat201_jun2024_p1_ocr.txt")])
    h = t.header
    assert h.course_code == "MAT201"
    assert (h.month, h.year) == (6, 2024)  # June 2024, not the December 2023 WP cohort
    assert h.qp_code == "08000MAT201122301"
    assert h.max_marks == 100 and h.duration == "3 Hours" and h.scheme == "2019"
    assert h.cohorts == ["S3 (S,FE)", "S1 (PT)(S)", "S3 (WP)(R)"]


def test_questions_from_real_ocr(fixture_text):
    t = parse_pages([fixture_text("mat201_jun2024_p1_ocr.txt")])
    qs = normalize_questions(T, t.questions)
    keys = [(q.number, q.sub) for q in qs]
    assert keys == [(n, None) for n in range(1, 11)] + [(11, "a"), (11, "b"), (12, "a"), (12, "b")]
    by = {(q.number, q.sub): q for q in qs}
    assert by[(11, "a")].marks == 7 and by[(11, "a")].module == 1 and by[(11, "a")].part == "B"
    assert by[(2, None)].text.startswith("Solve by direct integration: $\\frac")
    assert "(3)" not in by[(10, None)].text  # wrapped-line marks are stripped
    # The OCR read Q10 twice with different wording → flagged, not silently merged.
    assert by[(10, None)].legibility == "partly_unclear"
    issues = validate(T, t.model_copy(update={"questions": qs}), "MAT201")
    assert ("B06", 10) in {(i.code, i.number) for i in issues}
    assert all(q.bbox and len(q.bbox) == 4 for q in qs)


def test_clean_math_and_orientation():
    assert clean_math(r"Evaluate \(\oint_C f\) and \[x^2\]") == "Evaluate $\\oint_C f$ and $$x^2$$"
    assert looks_like_exam("title [1, 2, 3, 4]PART A\ntext [1, 2, 3, 4]Answer all questions. Marks")
    assert not looks_like_exam("text [1, 2, 3, 4]uo!}unbe |c!1uoJeH!p")


def test_detects_repetition_loops():
    from app.services.extraction.local_ocr import degenerate_regions

    years = " ".join(f"{y}." for y in range(2014, 1700, -1))
    raw = (
        "header [384, 55, 603, 71]08000MAT201122301\n"
        f"header [76, 143, 955, 162]B.Tech Degree S3 June 2024 (2019 Scheme)/S3 (WP)(R) D. {years}\n"
        "header [785, 6, 999, 155]CHGG. COLLEGE\n" + "AT\n" * 400
        + "text [151, 309, 905, 352]1 Form the partial differential equation (3)\n"
    )
    boxes = degenerate_regions(raw)
    assert [76.0, 143.0, 955.0, 162.0] in boxes and [785.0, 6.0, 999.0, 155.0] in boxes
    assert len(boxes) == 2  # the real question line is untouched


def test_exam_score_prefers_upright_reading(fixture_text):
    from app.services.extraction.ocr_parser import exam_score

    upright = fixture_text("mat201_jun2024_p1_ocr.txt")
    # Same content read bottom-up (what an upside-down page produces): numbers descend.
    lines = [l for l in upright.splitlines() if l.startswith("text [151")]
    reversed_read = "\n".join(reversed(lines))
    assert exam_score(upright) > exam_score(reversed_read) + 3


def test_halves_remap_bboxes_onto_full_page():
    from app.services.extraction.local_ocr import _remap_rows

    raw = "text [100, 0, 900, 500]11(a) Solve (7)\ncontinuation line"
    out = _remap_rows(raw, y0=470.0, scale=0.53).splitlines()
    assert out[0] == "text [100, 470, 900, 735]11(a) Solve (7)"
    assert out[1] == "continuation line"


def test_repair_pages_for_missing_slots():
    from app.services.extraction.pipeline import OcrPage, OcrRun, _pages_of
    from app.services.transcript import Transcript, TranscriptQuestion
    from pathlib import Path

    run = OcrRun("x", pages=[OcrPage("", Path("a")), OcrPage("", Path("b")), OcrPage("", Path("c"))])
    t = Transcript(questions=[TranscriptQuestion(number=10, text="q10 text here", page=0),
                              TranscriptQuestion(number=19, text="q19 text here", page=2)])
    assert _pages_of(t, 12, run) == (1,)  # between page 0 and page 2
    t2 = Transcript(questions=[TranscriptQuestion(number=10, text="q10 text here", page=0),
                               TranscriptQuestion(number=13, text="q13 text here", page=1)])
    assert _pages_of(t2, 11, run) == (0, 1)  # adjacent pages: send both
    assert _pages_of(t2, 13, run) == (1,)


def test_detects_line_repeat_and_restart_loops():
    from app.services.extraction.local_ocr import is_degenerate

    line = "text [205, 572, 860, 645]Check whether the function f(z) is continuous at the origin\n"
    assert is_degenerate("text [1, 1, 9, 9]6 Show that (3)\n" + line * 5)
    restart = "\n".join(f"text [1, {i}, 9, {i + 5}]{n} Find the value of the integral (3)" for i, n in
                        enumerate([9, 10, 11, 12, 10, 11, 12, 10, 11]))
    assert is_degenerate(restart)
    ok = "\n".join(f"text [1, {i}, 9, {i + 5}]{n} Find the value number {n} (3)" for i, n in enumerate(range(1, 11)))
    assert not is_degenerate(ok)


def test_page_quality_prefers_complete_read(fixture_text):
    from app.services.extraction.pipeline import page_quality

    full = fixture_text("mat201_jun2024_p1_ocr.txt")
    bottom_half_only = "\n".join(l for l in full.splitlines() if "[151, 6" in l or "[154, 8" in l or "[171, 8" in l)
    assert page_quality(full) > page_quality(bottom_half_only)
