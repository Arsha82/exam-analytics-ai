"""
Catalog builder: a course definition (modules + closed topic list) for any KTU course.

1. A provisional catalog (five "Module N" placeholders) is created at once so the
   course can collect papers immediately.
2. The syllabus is located (agy search + page mining → PDFs → the course's section of
   the text layer) and structured by the `pyq-writer` agent into modules and topics.
3. If no syllabus is found but papers are already read, topics are proposed from the
   questions of each module instead (the module itself is known from paper structure).
Generated definitions are saved next to the hand-written ones, marked "generated".
"""

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.services.acquisition.connectors import FoundLink, extract_links, links_from_page
from app.services.acquisition.fetcher import Fetched, FetchedPage, fetch
from app.services.agy import AgyClient, AgyError, AgyUnavailable
from app.services.catalog import CATALOG_DIR
from app.services.extraction.pdf import text_layer

SYLLABUS_PAGES = ["https://www.fisat.ac.in/syllabus-ktu/"]


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:40] or "topic"


def provisional_catalog(code: str, title: str, scheme: str = "2019", semester: int | None = None,
                        credits: float | None = None, slot: str | None = None) -> dict:
    return {
        "code": code, "university": "KTU", "university_name": "APJ Abdul Kalam Technological University",
        "scheme": scheme, "title": title, "title_variants": [], "code_variants": [code, f"{code[:3]} {code[3:]}"],
        "semester": semester, "slot": slot, "credits": int(credits) if credits else None,
        "template_id": "ktu2019_theory_100", "first_exam": {"year": 2020, "month": 12},
        "sources": {"dspace": list(settings.dspace_sources), "pages": []},
        "generated": True, "provisional": True, "syllabus_source": None,
        "modules": [
            {"no": n, "title": f"Module {n}", "syllabus": "",
             "topics": [{"id": f"{code.lower()}.m{n}.all", "name": f"Module {n} (all topics)", "keywords": []}]}
            for n in range(1, 6)
        ],
    }


def save_catalog(cdef: dict) -> Path:
    folder = CATALOG_DIR / cdef.get("university", "KTU").lower()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{cdef['code']}.json"
    path.write_text(json.dumps(cdef, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def syllabus_section(text: str, code: str) -> str | None:
    """The course's part of a multi-course syllabus booklet: from the code to just after Module 5."""
    flat = re.sub(r"[ \t]+", " ", text)
    for m in re.finditer(re.escape(code) + r"|" + re.escape(f"{code[:3]} {code[3:]}"), flat):
        window = flat[m.start(): m.start() + 20000]
        m1 = re.search(r"\bModule\s*[-–:]?\s*(1|I)\b", window, re.I)
        m5 = re.search(r"\bModule\s*[-–:]?\s*(5|V)\b", window, re.I)
        if m1 and m5 and m1.start() < m5.start() and m1.start() < 9000:
            end = m5.end() + 1800
            # Stop early at the next course's code header if it appears.
            nxt = re.search(r"\n\s*[A-Z]{3}\s?\d{3}\b", window[m5.end(): end])
            if nxt:
                end = m5.end() + nxt.start()
            return window[:end].strip()
    return None


class _Topic(BaseModel):
    name: str
    keywords: list[str] = Field(default_factory=list)


class _Module(BaseModel):
    no: int
    title: str
    syllabus: str = ""
    topics: list[_Topic]

    @field_validator("topics")
    @classmethod
    def _n_topics(cls, v):
        if not 2 <= len(v) <= 9:
            raise ValueError("each module needs 2-9 topics")
        return v


class _Taxonomy(BaseModel):
    modules: list[_Module]

    @field_validator("modules")
    @classmethod
    def _five(cls, v):
        if sorted(m.no for m in v) != [1, 2, 3, 4, 5]:
            raise ValueError("exactly modules 1-5 are required")
        return v


TAXONOMY_PROMPT = """Build the topic taxonomy of a university course from its official syllabus.

Course: {code} — {title} (KTU {scheme} scheme)

Syllabus text (from the official PDF; may contain OCR noise):
\"\"\"
{syllabus}
\"\"\"

For each of the 5 modules give: a short module title, the module's syllabus line (copied,
cleaned), and 3-8 topics. A topic is a unit an exam question can be about (e.g. "Lagrange's
linear equation", "Cauchy's integral formula"), named in the syllabus's own words; add 1-4
keywords per topic that appear in typical exam questions. Do not add topics the syllabus
does not cover.

Reply with only this JSON:
{{"modules": [{{"no": 1, "title": "...", "syllabus": "...", "topics": [{{"name": "...", "keywords": ["..."]}}]}}]}}"""

FROM_QUESTIONS_PROMPT = """Propose the topic taxonomy of one module of a university course from its real exam questions.

Course: {code} — {title}. Module {module}.
Questions asked in this module across past papers:
{questions}

Group them into 3-7 topics (units an exam question can be about), named the way a syllabus
would name them, each with 1-4 keywords seen in the questions. Also give a short module title.

Reply with only this JSON:
{{"title": "...", "topics": [{{"name": "...", "keywords": ["..."]}}]}}"""


class _ModuleFromQuestions(BaseModel):
    title: str
    topics: list[_Topic]


def apply_taxonomy(cdef: dict, modules: list[_Module], source: str | None) -> dict:
    code = cdef["code"].lower()
    out = dict(cdef)
    out["modules"] = [
        {"no": m.no, "title": m.title.strip(), "syllabus": m.syllabus.strip(),
         "topics": _unique_topics(code, m.no, m.topics)}
        for m in sorted(modules, key=lambda m: m.no)
    ]
    out["provisional"] = False
    out["syllabus_source"] = source
    return out


def _unique_topics(code: str, module: int, topics: list[_Topic]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for t in topics:
        tid = f"{code}.m{module}.{slug(t.name)}"
        while tid in seen:
            tid += "_2"
        seen.add(tid)
        out.append({"id": tid, "name": t.name.strip(), "keywords": [k for k in t.keywords if k][:4]})
    return out


async def find_syllabus(client: AgyClient, cdef: dict, workspace: Path, on_event=None) -> tuple[str | None, str | None, list[Fetched]]:
    """Search for the syllabus, download candidate PDFs, return (section text, source URL, files)."""
    code, title, scheme = cdef["code"], cdef["title"], cdef["scheme"]
    from app.services.acquisition.planner import SCOUT_PROMPT
    from app.services.course_pipeline import _ScoutReply

    links: list[FoundLink] = []
    for page in SYLLABUS_PAGES:
        try:
            links += [l for l in await links_from_page(page, found_by="page:syllabus") if l.url.lower().endswith(".pdf") or "drive.google" in l.url]
        except Exception:  # noqa: BLE001
            pass
    queries = [f"KTU {code} {title} syllabus {scheme} scheme pdf", f"KTU {scheme} scheme syllabus {code} module 1 module 2 module 3"]
    st = client.status()
    if st["available"]:
        for q in queries:
            prompt = SCOUT_PROMPT.format(code=code, title=title, university_name=cdef.get("university_name", "KTU"),
                                         scheme=scheme, query=q, purpose="the official syllabus PDF (module-wise contents)")
            try:
                reply, _ = await client.run_json(prompt, _ScoutReply, agent="pyq-scout", model=settings.agy_scout_model,
                                                 cwd=workspace, fallback_model=settings.agy_fallback_model, on_event=on_event)
            except (AgyError, AgyUnavailable):
                continue
            for c in reply.candidates:
                if c.kind == "page":
                    try:
                        links += await links_from_page(c.url, found_by="agy>page")
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    links.append(FoundLink(c.url, c.label or "", c.page_url, "agy"))
    # Rank: label/URL mentioning the code or "syllabus" first.
    def score(l: FoundLink) -> int:
        t = f"{l.label} {l.url}".lower()
        return (3 if code.lower() in t.replace(" ", "") else 0) + (2 if "syllabus" in t else 0) + (1 if f"s{cdef.get('semester') or ''}" in t else 0)

    files: list[Fetched] = []
    tried: set[str] = set()
    for link in sorted(links, key=score, reverse=True)[:8]:
        if link.url in tried:
            continue
        tried.add(link.url)
        try:
            res = await fetch(link.url)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(res, FetchedPage):
            for sub in extract_links(res.html, res.final_url)[:4]:
                try:
                    r2 = await fetch(sub.url)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(r2, Fetched) and r2.mime == "application/pdf":
                    files.append(r2)
            continue
        if res.mime != "application/pdf":
            continue
        files.append(res)
        section = syllabus_section("\n".join(text_layer(res.path)), code)
        if section:
            return section, link.url, files
    for f in files:
        section = syllabus_section("\n".join(text_layer(f.path)), code)
        if section:
            return section, None, files
    return None, None, files


async def structure_syllabus(client: AgyClient, cdef: dict, section: str, workspace: Path, on_event=None) -> list[_Module]:
    prompt = TAXONOMY_PROMPT.format(code=cdef["code"], title=cdef["title"], scheme=cdef["scheme"], syllabus=section[:12000])
    reply, _ = await client.run_json(prompt, _Taxonomy, agent="pyq-writer", model=settings.agy_reader_model,
                                     cwd=workspace, fallback_model=settings.agy_fallback_model, on_event=on_event)
    return reply.modules


async def taxonomy_from_questions(client: AgyClient, cdef: dict, questions_by_module: dict[int, list[str]],
                                  workspace: Path, on_event=None) -> list[_Module]:
    modules = []
    for no in range(1, 6):
        qs = questions_by_module.get(no, [])
        if len(qs) < 3:
            raise ValueError(f"module {no} has too few questions to infer topics")
        lines = "\n".join(f"- {q[:300]}" for q in qs[:60])
        prompt = FROM_QUESTIONS_PROMPT.format(code=cdef["code"], title=cdef["title"], module=no, questions=lines)
        if "mcq" in cdef.get("template_id", ""):
            prompt += ("\n\nThis is a comprehensive multiple-choice exam: each block of questions comes from one earlier"
                       " course of the programme. Use that course's name as the title (e.g. \"Operating Systems\").")
        reply, _ = await client.run_json(prompt, _ModuleFromQuestions, agent="pyq-writer", model=settings.agy_reader_model,
                                         cwd=workspace, fallback_model=settings.agy_fallback_model, on_event=on_event)
        modules.append(_Module(no=no, title=reply.title, syllabus="", topics=reply.topics))
    return modules
