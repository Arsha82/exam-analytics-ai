import pytest

from app.services.academics import Attempt, needed_sgpa, parse_grade_card, semester_from_code, summarize
from app.services.catalog_builder import _Module, _Topic, apply_taxonomy, provisional_catalog, syllabus_section
from app.services.curriculum import parse_curriculum
from app.services.exam_templates import get_template
from app.services.notes import module_from_text, notes_relevant
from app.services.practice import BankQuestion, MockPaperError, assemble

T = get_template("ktu2019_theory_100")

CE_TEXT = (
    "7 SEMESTER III SLOT COURSE NO. COURSES L-T-P HOURS CREDIT A MAT201 PARTIAL DIFFERENTIAL EQUATION AND COMPLEX "
    "ANALYSIS 3-1-0 4 4 B CET201 MECHANICS OF SOLIDS 3-1-0 4 4 C CET203 FLUID MECHANICS& HYDRAULICS 3-1-0 4 4 "
    "E 1/2 EST200 DESIGN & ENGINEERING 2-0-0 2 2 HUT200 PROFESSIONAL ETHICS 2-0-0 2 2 F MCN201 SUSTAINABLE "
    "ENGINEERING 2-0-0 2 -- S CEL201 CIVIL ENGINEERING PLANNING &DRAFTING LAB 0-0-3 3 2 "
    "SEMESTER IV SLOT COURSE NO. COURSES L-T-P HOURS CREDIT A MAT202 PROBABILITY, STATISTICS AND NUMERICAL METHODS 3-1-0 4 4"
)


def test_curriculum_rows():
    rows = parse_curriculum([CE_TEXT])
    by = {(r.semester, r.code): r for r in rows}
    assert by[(3, "MAT201")].title == "Partial Differential Equation And Complex Analysis"
    assert by[(3, "MAT201")].credits == 4 and by[(3, "MAT201")].slot == "A" and by[(3, "MAT201")].ltp == "3-1-0"
    assert by[(3, "EST200")].credits == 2 and by[(3, "HUT200")].credits == 2
    assert by[(3, "MCN201")].credits is None  # non-credit course
    assert by[(4, "MAT202")].semester == 4
    assert (3, "CEL201") in by


def test_grade_card_parse_and_semester():
    text = """APJ ABDUL KALAM TECHNOLOGICAL UNIVERSITY
B.Tech S3 (R) Examination December 2022 (2019 Scheme)
MAT201 PARTIAL DIFFERENTIAL EQUATION AND COMPLEX ANALYSIS 4 A+
CET201 MECHANICS OF SOLIDS 4 F
CET203 FLUID MECHANICS & HYDRAULICS B+
EST200 DESIGN & ENGINEERING 2 A
"""
    card = parse_grade_card(text)
    assert card.session == (12, 2022)
    g = {r.course_code: r for r in card.records}
    assert g["MAT201"].grade == "A+" and g["MAT201"].credits == 4
    assert g["CET201"].grade == "F" and g["CET203"].grade == "B+" and g["CET203"].credits is None
    assert semester_from_code("MAT201") == 3 and semester_from_code("MAT202") == 4 and semester_from_code("EST200") is None


def test_sgpa_cgpa_backlogs():
    attempts = [
        Attempt("MAT201", "A+", 4, 3, 202212), Attempt("CET201", "F", 4, 3, 202212), Attempt("CET203", "B", 4, 3, 202212),
        Attempt("CET201", "C", 4, 3, 202306),  # cleared in the supplementary
        Attempt("MAT202", "F", 4, 4, 202306),
    ]
    s = summarize(attempts)
    s3 = next(x for x in s["semesters"] if x["semester"] == 3)
    assert s3["sgpa"] == round((4 * 9 + 0 + 4 * 7.5) / 12, 2)  # regular attempt defines the SGPA
    assert s["cgpa"] == round((4 * 9 + 4 * 6.5 + 4 * 7.5 + 0) / 16, 2)  # best attempt; uncleared at 0
    assert [b["course_code"] for b in s["backlogs"]] == ["MAT202"]
    assert needed_sgpa(7.0, 100, 20, 7.5) == 10.0


def test_notes_detection():
    assert module_from_text("MAT201 Module 3 notes.pdf") == 3
    assert module_from_text("KTU PDE mod-IV handwritten") == 4
    assert module_from_text("no module here") is None
    assert notes_relevant("Module 2 notes", "https://x/y.pdf", ["MAT201"])[0]
    assert not notes_relevant("MAT201 question paper Dec 2022", "https://x/y.pdf", ["MAT201"])[0]


def test_syllabus_section_and_taxonomy():
    booklet = ("CET201 MECHANICS OF SOLIDS ... Module 1 stress Module 5 beams ...\n"
               "MAT201 PARTIAL DIFFERENTIAL EQUATIONS AND COMPLEX ANALYSIS\nSyllabus\n"
               "Module 1 (Partial Differential Equations) Formation of PDE, Lagrange's linear equation.\n"
               "Module 2 Wave and heat equations.\nModule 3 Analytic functions.\nModule 4 Cauchy integral formula.\n"
               "Module 5 Laurent series, residues.\nText Books ...\nCET203 FLUID MECHANICS Module 1 fluids")
    sec = syllabus_section(booklet, "MAT201")
    assert sec.startswith("MAT201") and "Module 5 Laurent" in sec and "CET203" not in sec
    cdef = provisional_catalog("MAT999", "Test Course", semester=3, credits=4, slot="A")
    assert cdef["provisional"] and len(cdef["modules"]) == 5
    mods = [_Module(no=n, title=f"M{n}", topics=[_Topic(name="Cauchy's integral formula"), _Topic(name="Cauchy's integral formula")])
            for n in range(1, 6)]
    out = apply_taxonomy(cdef, mods, "syllabus PDF")
    ids = [t["id"] for t in out["modules"][0]["topics"]]
    assert ids == ["mat999.m1.cauchy_s_integral_formula", "mat999.m1.cauchy_s_integral_formula_2"]
    assert out["provisional"] is False


def _bank():
    bank = []
    for p in range(4):
        pid = f"p{p}"
        for m in range(1, 6):
            for n in T.part_a_for_module(m):
                bank.append(BankQuestion(f"{pid}_{n}", pid, f"Paper {p}", "A", n, None, m, 3, f"Part A {pid} q{n} define topic", [f"m{m}.t{n % 2}"]))
            for n in T.part_b_pairs(m):
                for sub in ("a", "b"):
                    bank.append(BankQuestion(f"{pid}_{n}{sub}", pid, f"Paper {p}", "B", n, sub, m, 7,
                                             f"Part B {pid} q{n}{sub} solve", [f"m{m}.t{2 if sub == 'a' else 3}"]))
    return bank


def test_mock_paper_passes_validator_and_mixes_papers():
    items = assemble(T, "MAT201", _bank(), probs={}, focus="balanced", seed=7)
    assert [i["number"] for i in items if i["part"] == "A"] == list(range(1, 11))
    assert sorted({i["number"] for i in items if i["part"] == "B"}) == list(range(11, 21))
    for m in range(1, 6):
        n1, n2 = T.part_b_pairs(m)
        src1 = {i["source"].split(" · ")[0] for i in items if i["number"] == n1}
        src2 = {i["source"].split(" · ")[0] for i in items if i["number"] == n2}
        assert src1 != src2  # the two choices of a module come from different papers
    # Printed: Part A 30 + both either/or choices (5 x 2 x 14); answerable: 30 + 5 x 14 = 100.
    assert sum(i["marks"] for i in items) == 170
    assert sum(i["marks"] for i in items if i["part"] == "A" or i["number"] % 2 == 1) == 100
    again = assemble(T, "MAT201", _bank(), probs={}, focus="balanced", seed=7)
    assert [i["question_id"] for i in again] == [i["question_id"] for i in items]  # reproducible by seed


def test_mock_paper_refuses_thin_bank():
    thin = [q for q in _bank() if not (q.module == 3 and q.part == "B")]
    with pytest.raises(MockPaperError):
        assemble(T, "MAT201", thin, probs={}, seed=1)


def test_notes_module_nearest_link_and_question_bank_filter():
    from app.services.notes import module_for_link

    label = "SET 1 MODULE FILE Module 1 DOWNLOAD Module 2 DOWNLOAD Module 3"
    assert module_for_link(label, "https://drive.google.com/file/d/abc/view") == 3
    assert module_for_link(label, "https://x.org/MAT201-Module-4.pdf") == 4
    assert not notes_relevant("QUESTION PAPERS & QUESTION BANK MODULE 1", "https://x/y.pdf", ["MAT201"])[0]
