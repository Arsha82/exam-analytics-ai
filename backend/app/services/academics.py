"""
Academics: KTU grade points, grade-card parsing, SGPA/CGPA and backlogs.

Grade points (KTU B.Tech 2019 regulations): S 10, A+ 9, A 8.5, B+ 8, B 7.5, C+ 7,
C 6.5, D 6, P 5.5, F 0. FE (failed — not eligible), Absent and Withheld count as fail.
SGPA of a semester = Σ credits × grade point / Σ credits of the courses registered
(fails count with 0); CGPA uses each course's best attempt, uncleared courses at 0.
"""

import re
from dataclasses import dataclass, field

from app.services.acquisition.sessions import parse_session, session_label

GRADE_POINTS: dict[str, float] = {
    "S": 10.0, "O": 10.0, "A+": 9.0, "A": 8.5, "B+": 8.0, "B": 7.5,
    "C+": 7.0, "C": 6.5, "D": 6.0, "P": 5.5, "F": 0.0, "FE": 0.0, "AB": 0.0, "ABSENT": 0.0, "W": 0.0,
}
FAIL = {"F", "FE", "AB", "ABSENT", "W"}
_CODE = re.compile(r"\b([A-Z]{3}\s?\d{3})\b")
_GRADE_TOKEN = re.compile(r"(?<![A-Za-z])(S|O|A\+|A|B\+|B|C\+|C|D|P|F|FE|AB|Absent|W)(?![A-Za-z+])")


def normalize_grade(g: str) -> str | None:
    g = g.strip().upper().replace(" ", "")
    if g == "ABSENT":
        return "AB"
    return g if g in GRADE_POINTS else None


def semester_from_code(code: str) -> int | None:
    """KTU course numbers: first digit = year, odd last digit = odd semester (MAT201 → S3)."""
    m = re.match(r"^[A-Z]{3}(\d)(\d)(\d)$", code)
    if not m:
        return None
    year, last = int(m.group(1)), int(m.group(3))
    if not 1 <= year <= 4:
        return None
    if last == 0:  # e.g. EST200 / HUT200 are offered in either semester of the year
        return None
    return 2 * year - (1 if last % 2 == 1 else 0)


@dataclass
class ParsedRecord:
    course_code: str
    grade: str
    title: str | None = None
    credits: float | None = None


@dataclass
class ParsedGradeCard:
    session: tuple[int, int] | None
    records: list[ParsedRecord] = field(default_factory=list)


def parse_grade_card(text: str) -> ParsedGradeCard:
    """
    Course lines from a KTU result / grade card (text layer or OCR): a course code, an
    optional title, optional credits, and a grade as the last grade-like token.
    """
    records: dict[str, ParsedRecord] = {}
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        m = _CODE.search(line)
        if not m:
            continue
        code = m.group(1).replace(" ", "")
        rest = line[m.end():]
        grades = [g for g in _GRADE_TOKEN.findall(rest)]
        if not grades:
            continue
        grade = normalize_grade(grades[-1])
        if grade is None:
            continue
        title_part = rest
        last = rest.rfind(grades[-1])
        if last != -1:
            title_part = rest[:last]
        credit_m = re.search(r"\b(\d(?:\.\d)?)\s*$", title_part.strip())
        credits = float(credit_m.group(1)) if credit_m else None
        if credit_m:
            title_part = title_part.strip()[: credit_m.start()]
        title = re.sub(r"[|:\-–]+", " ", title_part).strip(" .|") or None
        records[code] = ParsedRecord(code, grade, title.title() if title and title.isupper() else title, credits)
    return ParsedGradeCard(session=parse_session(text), records=list(records.values()))


@dataclass
class Attempt:
    course_code: str
    grade: str
    credits: float
    semester: int | None
    session_key: int  # ordering of attempts (year*100+month, 0 if unknown)
    title: str | None = None


def summarize(attempts: list[Attempt]) -> dict:
    """SGPA per semester, CGPA, credits and current backlogs."""
    by_sem: dict[int, list[Attempt]] = {}
    for a in attempts:
        if a.semester:
            by_sem.setdefault(a.semester, []).append(a)

    semesters = []
    for sem in sorted(by_sem):
        # The first (regular) attempt of each course defines the semester's SGPA.
        first: dict[str, Attempt] = {}
        for a in sorted(by_sem[sem], key=lambda x: x.session_key):
            first.setdefault(a.course_code, a)
        credits = sum(a.credits for a in first.values())
        points = sum(a.credits * GRADE_POINTS[a.grade] for a in first.values())
        semesters.append({
            "semester": sem,
            "sgpa": round(points / credits, 2) if credits else None,
            "credits_registered": credits,
            "credits_earned": sum(a.credits for a in first.values() if a.grade not in FAIL),
            "courses": len(first),
        })

    best: dict[str, Attempt] = {}
    for a in attempts:
        cur = best.get(a.course_code)
        if cur is None or GRADE_POINTS[a.grade] > GRADE_POINTS[cur.grade] or (
            GRADE_POINTS[a.grade] == GRADE_POINTS[cur.grade] and a.session_key > cur.session_key
        ):
            best[a.course_code] = a
    total_credits = sum(a.credits for a in best.values())
    cgpa = round(sum(a.credits * GRADE_POINTS[a.grade] for a in best.values()) / total_credits, 2) if total_credits else None
    backlogs = [
        {"course_code": a.course_code, "title": a.title, "semester": a.semester, "credits": a.credits, "grade": a.grade,
         "attempts": sum(1 for x in attempts if x.course_code == a.course_code)}
        for a in best.values() if a.grade in FAIL
    ]
    return {
        "semesters": semesters,
        "cgpa": cgpa,
        "credits_earned": sum(a.credits for a in best.values() if a.grade not in FAIL),
        "credits_registered": total_credits,
        "backlogs": sorted(backlogs, key=lambda b: (b["semester"] or 0, b["course_code"])),
    }


def needed_sgpa(current_cgpa: float | None, credits_so_far: float, next_credits: float, target: float) -> float | None:
    """SGPA needed next semester to reach a target CGPA (None if not computable)."""
    if current_cgpa is None or next_credits <= 0:
        return None
    need = (target * (credits_so_far + next_credits) - current_cgpa * credits_so_far) / next_credits
    return round(need, 2)


def label_for(session: tuple[int, int] | None) -> str | None:
    return session_label(*session) if session else None
