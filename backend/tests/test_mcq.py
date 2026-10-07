"""MCQ papers (KTU Comprehensive Course Work, e.g. ADT308): template, parser, validator, insights, mock papers."""

from app.services.exam_templates import get_template, normalize_questions, validate
from app.services.extraction.ocr_parser import parse_blocks, parse_header, parse_questions, split_options
from app.services.insights import QRow, module_dataset, PaperRow
from app.services.practice import BankQuestion, MockPaperError, assemble
from app.services.transcript import Transcript, TranscriptHeader, TranscriptQuestion

T = get_template("ktu2019_mcq_50")

RAW = """text [100, 50, 900, 70]0100ADT308062402
text [100, 90, 900, 110]Course Code: ADT308
text [100, 120, 900, 140]Course name: COMPREHENSIVE COURSE WORK
text [100, 150, 900, 170]Max. Marks: 50 Duration: 1Hour
text [150, 200, 900, 260]Instructions: (1) Each question carries one mark. (2) Total number of questions: 50
text [100, 300, 900, 340]1 Let the page fault service time be 10ms. What is the effective access time?
text [120, 350, 900, 370]a) 21ns b) 30ns c) 23ns d) 35ns
text [100, 400, 900, 440]2 Consider three processes with bursts 2, 4 and 8. The average turn around time is:
text [120, 450, 300, 470]a) 13 units
text [320, 450, 500, 470]b) 14 units
text [520, 450, 700, 470]c) 15 units
text [720, 450, 900, 470]d) 16 units
text [100, 500, 900, 540]3 Which of the following scheduling reduces process flow time?
text [120, 550, 900, 570]a) FCFS b) LIFO c) SJF d) None of these
"""


def test_template_blocks_of_ten():
    assert T.is_mcq and T.total_marks == 50 and T.options == 4
    assert [T.module_of(n) for n in (1, 10, 11, 20, 41, 50)] == [1, 1, 2, 2, 5, 5]
    assert T.part_b_pairs(1) is None and T.part_a_for_module(2) == tuple(range(11, 21))


def test_split_options_ignores_letters_in_the_stem():
    stem, opts = split_options("Which is true of (a) and (b)? a) only a b) only b c) both d) neither")
    assert stem == "Which is true of (a) and (b)?" and opts == ["only a", "only b", "both", "neither"]
    assert split_options("no options here") == ("no options here", [])


def test_parser_mcq_mode():
    blocks = parse_blocks(RAW, 0)
    h = parse_header(blocks, mcq=True)
    assert h.course_code == "ADT308" and h.max_marks == 50
    qs = parse_questions(blocks, mcq=True)
    assert [q.number for q in qs] == [1, 2, 3]
    assert qs[1].options == ["13 units", "14 units", "15 units", "16 units"]
    assert qs[2].text.startswith("Which of the following") and qs[2].options[2] == "SJF"


def test_option_text_never_starts_a_question():
    raw = RAW.replace("d) 16 units", "16 units")  # OCR dropped the letter
    qs = parse_questions(parse_blocks(raw, 0), mcq=True)
    assert [q.number for q in qs] == [1, 2, 3]  # "16 units" did not become question 16


def _full_paper(missing_option_at: int | None = None) -> Transcript:
    qs = [TranscriptQuestion(number=n, text=f"Question number {n} asks something?",
                             options=[f"w{n}", f"x{n}", f"y{n}"] if n == missing_option_at else [f"w{n}", f"x{n}", f"y{n}", f"z{n}"])
          for n in range(1, 51)]
    return Transcript(header=TranscriptHeader(course_code="ADT308", max_marks=50, month=12, year=2025),
                      questions=normalize_questions(T, qs))


def test_validator_accepts_full_paper_and_flags_options():
    t = _full_paper()
    assert all(q.marks == 1.0 and q.marks_inferred for q in t.questions)
    assert [i for i in validate(T, t, "ADT308") if i.level == "error"] == []
    bad = validate(T, _full_paper(missing_option_at=7), "ADT308")
    assert any(i.code == "B11" and i.number == 7 for i in bad)


def test_insights_block_is_the_choice():
    papers = [PaperRow("p1", 202512, "Dec 2025")]
    qs = [QRow(f"q{n}", "p1", "A", n, None, T.module_of(n), 1.0, ["t1"] if n % 2 else ["t2"], "problem")
          for n in range(1, 51)]
    data = module_dataset(T, 1, papers, qs)
    choices, a_qs = data[0]
    assert len(choices) == 1 and len(choices[0]) == 10 and a_qs == []


def test_mock_mcq_paper():
    bank = [BankQuestion(f"q{m}_{i}", f"p{i % 3}", "Dec 2025", "A", (m - 1) * 10 + i % 10 + 1, None, m, 1.0,
                         f"Distinct question {m}-{i} about something?", options=[f"a{m}{i}", f"b{m}{i}", f"c{m}{i}", f"d{m}{i}"])
            for m in range(1, 6) for i in range(12)]
    items = assemble(T, "ADT308", bank, {}, seed=3)
    assert [i["number"] for i in items] == list(range(1, 51))
    assert all(len(i["options"]) == 4 for i in items)
    try:
        assemble(T, "ADT308", bank[:30], {}, seed=1)
        raise AssertionError("thin bank should fail")
    except MockPaperError:
        pass


def test_copied_options_are_flagged():
    t = _full_paper()
    qs = list(t.questions)
    qs[1] = qs[1].model_copy(update={"options": list(qs[0].options)})
    t2 = t.model_copy(update={"questions": qs})
    assert any(i.code == "B11" and "identical" in i.message for i in validate(T, t2, "ADT308"))
