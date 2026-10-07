from app.services.exam_templates import flagged_slots, get_template, normalize_questions, validate
from app.services.transcript import TranscriptQuestion

T = get_template("ktu2019_theory_100")


def test_structural_modules():
    assert [T.module_of(n) for n in range(1, 11)] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert [T.module_of(n) for n in range(11, 21)] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert T.part_of(3) == "A" and T.part_of(17) == "B" and T.part_of(21) is None
    assert T.choice_pair(13) == (13, 14) and T.choice_pair(14) == (13, 14)
    assert T.part_b_pairs(5) == (19, 20)
    assert T.part_a_for_module(3) == (5, 6)


def test_real_transcript_validates(jun2024_transcript):
    t = jun2024_transcript
    t.questions = normalize_questions(T, t.questions)
    issues = validate(T, t, "MAT201")
    errors = [i for i in issues if i.level == "error"]
    assert errors == [], errors
    # agy marked 13(a) and 19(b) partly unclear: they must be flagged, nothing else.
    assert flagged_slots(issues) == {13, 19}
    # Printed module headings agree with structure.
    assert not [i for i in issues if i.code == "B05"]


def test_detects_missing_and_wrong_marks(jun2024_transcript):
    t = jun2024_transcript
    t.questions = [q for q in t.questions if q.number != 7]
    t.questions = [q.model_copy(update={"marks": 6.0}) if (q.number, q.sub) == (11, "a") else q for q in t.questions]
    codes = {(i.code, i.number) for i in validate(T, t, "MAT201")}
    assert ("B03", 7) in codes
    assert ("B04", 11) in codes


def test_wrong_course_and_marks_header(jun2024_transcript):
    t = jun2024_transcript
    t.header.course_code = "MAT203"
    t.header.max_marks = 75
    codes = {i.code for i in validate(T, t, "MAT201") if i.level == "error"}
    assert {"B01", "B02"} <= codes


def test_normalize_dedupes_and_flags_disagreeing_repeat():
    qs = [
        TranscriptQuestion(number=8, text="Evaluate the integral of cos z over |z|=1", marks=3),
        TranscriptQuestion(number=8, text="Evaluate the integral of cos z over |z|=1", marks=3),
        TranscriptQuestion(number=10, text="Find the singularities of f(z) = z^2 cos(1/z)", marks=None),
        TranscriptQuestion(number=10, text="Find the singularities of f(z) = z^2 in the half plane", marks=3),
    ]
    out = normalize_questions(T, qs)
    assert [q.number for q in out] == [8, 10]
    q10 = out[1]
    assert q10.marks == 3 and q10.legibility == "partly_unclear"
    assert out[0].legibility == "clear" and out[0].part == "A"


def test_infers_single_missing_part_b_mark():
    qs = [
        TranscriptQuestion(number=19, sub="a", text="Find the Laurent series expansion", marks=7),
        TranscriptQuestion(number=19, sub="b", text="Evaluate the real integral", marks=None),
        TranscriptQuestion(number=20, sub="a", text="Residue theorem question", marks=None),
        TranscriptQuestion(number=20, sub="b", text="Another question", marks=None),
    ]
    out = {(q.number, q.sub): q for q in normalize_questions(T, qs)}
    assert out[(19, "b")].marks == 7 and out[(19, "b")].marks_inferred
    assert out[(20, "a")].marks is None  # two unknowns: not inferable, stays flagged
