"""
Notes acquisition: module-wise study notes for a course, found by agy web searches and
deterministic page mining, downloaded and stored like papers (kind = "notes").

Module detection: label/URL first ("Module 3", "mod-3", "M3"), then the first pages of
the PDF's text layer. Text is kept on disk for lesson generation.
"""

import re
from pathlib import Path

from app.config import settings

ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
_MODULE = re.compile(r"\b(?:module|mod|unit)[\s_\-.:]*(\d|iv|v|i{1,3})\b", re.I)
_NOT_NOTES = re.compile(
    r"\b(question\s*papers?|question\s*bank|qp|previous\s*years?|answer\s*keys?|scheme\s*of\s*valuation|syllabus)\b", re.I
)
_NOTES_HINT = re.compile(r"\b(notes?|module|mod\s?\d|lecture|handout|study\s*material|textbook|ppt)\b", re.I)


def module_from_text(text: str | None, last: bool = False) -> int | None:
    """First (or, for link labels, last = closest to the link) "Module N" mention."""
    if not text:
        return None
    found = list(_MODULE.finditer(text))
    if not found:
        return None
    tok = (found[-1] if last else found[0]).group(1).lower()
    n = int(tok) if tok.isdigit() else ROMAN.get(tok)
    return n if n and 1 <= n <= 5 else None


def module_for_link(label: str | None, url: str | None) -> int | None:
    """A link's module: from its file name first, then the mention nearest the link in its label."""
    name = (url or "").rsplit("/", 1)[-1]
    return module_from_text(name) or module_from_text(label, last=True)


def notes_relevant(label: str, url: str, codes: list[str]) -> tuple[bool, str]:
    text = f"{label} {url}"
    if _NOT_NOTES.search(label or ""):
        return False, "looks like a question paper / syllabus, not notes"
    compact = re.sub(r"(?:%20|[\s_\-])+", "", text).upper()
    if any(c.replace(" ", "").upper() in compact for c in codes) or _NOTES_HINT.search(text):
        return True, ""
    return False, "no course code or notes hint in label/URL"


def notes_text_path(sha: str) -> Path:
    d = settings.storage_dir / "notes"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sha}.txt"


NOTES_QUERIES = [
    ("n1", '"{code}" {title} notes pdf KTU', "course notes"),
    ("n2", "{code} {title} module 1 module 2 notes", "early modules"),
    ("n3", "{code} {title} module 3 module 4 module 5 notes", "later modules"),
    ("n4", "{code} KTU notes ktunotes OR keralanotes OR ktuassist", "student portals"),
    ("n5", "{title} lecture notes pdf {scheme} scheme", "lecture notes"),
    ("n6", "{code} {title} handwritten notes OR study material drive.google.com", "shared files"),
]

NOTES_PROMPT = """Find downloadable study notes (not question papers) for a university course.

Course: {code} — {title}
University: {university_name} ({scheme} scheme). The course has 5 modules:
{modules}
Search query to run first: {query}
Purpose: {purpose}

Run the query with search_web, then up to two close variations. You cannot open pages:
report the URLs that appear in the search results (the app opens listing pages and
collects their links itself). Never construct or guess URLs.

Reply with only this JSON:
{{"candidates": [{{"url": "<file link or listing page URL>", "page_url": null, "label": "<title/snippet, e.g. 'Module 3 notes'>", "kind": "pdf" | "drive" | "page"}}]}}"""
