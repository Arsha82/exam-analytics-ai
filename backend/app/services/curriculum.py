"""
Scheme curriculum: which courses a branch takes in each semester.

Source: the official "<BRANCH> Curriculum - B.Tech 2019 Scheme" PDFs (born-digital), found
through the DSpace connector. Rows look like
  "A MAT201 PARTIAL DIFFERENTIAL EQUATION AND COMPLEX ANALYSIS 3-1-0 4 4"
under "SEMESTER III" headings.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

import httpx

from app.config import settings
from app.services.acquisition.connectors import _client, parse_dspace_item
from app.services.extraction.pdf import text_layer

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}
_SEM = re.compile(r"\bSEMESTER\s+(VIII|VII|VI|IV|V|III|II|I)\b")
_ROW = re.compile(
    r"(?:\b([A-HS-T])\s+(?:1/2\s+)?)?\b([A-Z]{3}\s?\d{3})\s+(.+?)\s+(\d\s*-\s*\d\s*-\s*\d)\s+(\d+)\s+(\d+(?:\.\d)?|--)"
)


@dataclass
class CurriculumRow:
    semester: int
    slot: str | None
    code: str
    title: str
    ltp: str
    credits: float | None


def parse_curriculum(pages: list[str]) -> list[CurriculumRow]:
    text = re.sub(r"\s+", " ", " ".join(pages))
    rows: list[CurriculumRow] = []
    seen: set[tuple[int, str]] = set()
    marks = list(_SEM.finditer(text))
    for i, m in enumerate(marks):
        sem = _ROMAN[m.group(1)]
        chunk = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        for r in _ROW.finditer(chunk):
            code = r.group(2).replace(" ", "")
            if (sem, code) in seen:
                continue
            seen.add((sem, code))
            title = re.sub(r"\s+", " ", r.group(3)).strip(" -")
            # A title swallowing another row means the regex ran past a boundary: cut it there.
            title = re.split(r"\b[A-Z]{3}\s?\d{3}\b", title)[-1].strip() or title
            title = re.sub(r"\s+[A-H]$", "", title)  # S1/S2 group letter printed after the title
            credits = None if r.group(6) == "--" else float(r.group(6))
            ltp = re.sub(r"\s+", "", r.group(4))
            rows.append(CurriculumRow(sem, r.group(1), code, title.title() if title.isupper() else title, ltp, credits))
    return rows


@dataclass
class CurriculumSource:
    branch: str
    title: str
    url: str


async def discover(bases: list[str] | None = None) -> list[CurriculumSource]:
    """Curriculum PDFs listed in the configured DSpace repositories (one per branch)."""
    out: list[CurriculumSource] = []
    async with _client() as client:
        for base in bases or settings.dspace_sources:
            try:
                resp = await client.get(f"{base.rstrip('/')}/search?query={quote_plus('Curriculum 2019 Scheme')}&rpp=100")
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
            for m in re.finditer(r'<a href="([^"]*/handle/[^"]+)"[^>]*>(.*?)</a>', resp.text, re.S):
                title = re.sub(r"<[^>]+>|\s+", " ", m.group(2)).replace("﻿", "").strip()
                tm = re.match(r"^([A-Z]{2,4})\s+Curriculum\b.*2019", title, re.I)
                if not tm:
                    continue
                item_url = f"{base.split('/xmlui')[0]}{m.group(1)}" if m.group(1).startswith("/") else m.group(1)
                item = await client.get(item_url)
                for bs in parse_dspace_item(item.text, item_url):
                    out.append(CurriculumSource(tm.group(1).upper(), title, bs))
                    break
    uniq: dict[str, CurriculumSource] = {}
    for s in out:
        uniq.setdefault(s.branch, s)
    return list(uniq.values())


def parse_file(path: Path) -> list[CurriculumRow]:
    return parse_curriculum(text_layer(path))
