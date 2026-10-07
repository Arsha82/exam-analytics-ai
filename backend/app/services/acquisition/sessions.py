"""
Exam session parsing and expected-session calendar (KTU style).

Headers look like "B.Tech Degree S3 (S,FE) / S1 (PT)(S) June 2024 (2019 Scheme)/S3 (WP)(R)
December 2023 Examination". The first month+year that is followed by the scheme
marker, or else the first month+year at all, is the session of the paper.
"""

import re
from dataclasses import dataclass
from datetime import date

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_SESSION_RE = re.compile(_MONTH_RE + r"[\s,.\-]*((?:19|20)\d{2})", re.IGNORECASE)


def parse_session(text: str | None) -> tuple[int, int] | None:
    """Return (month, year) of the exam session named in a header or label."""
    if not text:
        return None
    matches = list(_SESSION_RE.finditer(text))
    if not matches:
        return None
    for m in matches:
        tail = text[m.end() : m.end() + 20].lower()
        if "scheme" in tail:
            return MONTHS[m.group(1).lower()], int(m.group(2))
    m = matches[0]
    return MONTHS[m.group(1).lower()], int(m.group(2))


def parse_cohorts(text: str | None) -> list[str]:
    """Cohort markers such as 'S3 (S,FE)', 'S3 (R,S)', 'S1 (PT)(S)', 'S3 (WP)(R)', 'Regular'."""
    if not text:
        return []
    found: list[str] = []
    for m in re.finditer(r"\bS\s?(\d)\s*((?:\s*\([A-Z,/\s]+\))+)", text):
        found.append(f"S{m.group(1)} {re.sub(r'\s+', '', m.group(2))}")
    low = text.lower()
    if not found:
        if "regular and supplementary" in low:
            found.append("Regular+Supplementary")
        elif "supplementary" in low:
            found.append("Supplementary")
        elif "regular" in low:
            found.append("Regular")
    return found


def session_label(month: int | None, year: int | None) -> str:
    if not month or not year:
        return "Unknown session"
    return f"{MONTH_NAMES[month]} {year}"


def session_key(month: int, year: int) -> int:
    return year * 100 + month


@dataclass(frozen=True)
class SessionWindow:
    kind: str  # "regular" / "supplementary"
    year: int
    months: tuple[int, ...]
    label: str

    def contains(self, month: int, year: int) -> bool:
        if self.kind == "regular":
            # Regular winter cycle: Nov/Dec of `year`, sometimes held/labelled Jan of year+1.
            return (year == self.year and month in (10, 11, 12)) or (year == self.year + 1 and month == 1)
        return year == self.year and month in self.months


def expected_windows(first_year: int, first_month: int, today: date | None = None) -> list[SessionWindow]:
    """Regular (Nov-Jan) and supplementary (Apr-Aug) windows from the first exam until today."""
    today = today or date.today()
    out: list[SessionWindow] = []
    for y in range(first_year, today.year + 1):
        # A window counts once it has started and does not end before the first exam.
        if (y, 11) <= (today.year, today.month):
            out.append(SessionWindow("regular", y, (11, 12, 1), f"Nov/Dec {y} regular"))
        if (y > first_year or first_month <= 8) and (y, 5) <= (today.year, today.month):
            out.append(SessionWindow("supplementary", y, (4, 5, 6, 7, 8), f"May/Jun {y} supplementary"))
    out.sort(key=lambda w: (w.year, 0 if w.kind == "supplementary" else 1))
    return out
