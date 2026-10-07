"""
Deterministic source connectors — no LLM involved.

- HTML link extractor: PDF / Google Drive / repository bitstream links on any page,
  with the label text shown next to each link.
- DSpace connector: repository search → item pages → bitstream (file) links.
"""

import html
import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

from app.config import settings

_FILE_HINT = re.compile(
    r"(\.pdf(\?|#|$)|drive\.google\.com/(file/d/|open\?id=|uc\?)|docs\.google\.com/|/bitstream/)",
    re.IGNORECASE,
)
_ANCHOR = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.IGNORECASE | re.DOTALL)


@dataclass
class FoundLink:
    url: str
    label: str
    page_url: str | None
    found_by: str
    near: str = ""  # the link's own text: anchor + the few words right before it


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", fragment))).strip()


def drive_file_id(url: str) -> str | None:
    m = re.search(r"drive\.google\.com/file/d/([\w-]{10,})", url) or re.search(
        r"[?&]id=([\w-]{10,})", url
    )
    if m and ("drive.google.com" in url or "docs.google.com" in url or "usercontent.google.com" in url):
        return m.group(1)
    return None


def canonical_url(url: str) -> str:
    """Stable key for de-duplicating candidates (Drive links collapse to their file id)."""
    fid = drive_file_id(url)
    if fid:
        return f"gdrive:{fid}"
    p = urlparse(url)
    return f"{p.netloc.lower().removeprefix('www.')}{p.path}".rstrip("/") + (f"?{p.query}" if p.query else "")


def extract_links(page_html: str, base_url: str, found_by: str = "html") -> list[FoundLink]:
    """File-like links on a page plus the visible text just before each (its label)."""
    body = _SCRIPT.sub(" ", page_html)
    out: list[FoundLink] = []
    seen: set[str] = set()
    for m in _ANCHOR.finditer(body):
        href = html.unescape(m.group(1)).strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        url = urljoin(base_url, href)
        if not _FILE_HINT.search(url):
            continue
        key = canonical_url(url)
        if key in seen:
            continue
        seen.add(key)
        frag = body[max(0, m.start() - 600) : m.start()]
        lt, gt = frag.find("<"), frag.find(">")
        if gt != -1 and (lt == -1 or gt < lt):  # window starts inside a tag
            frag = frag[gt + 1 :]
        before = _text(frag)
        anchor = _text(m.group(2))
        label = (before[-160:] + " " + anchor).strip()
        near = (before[-60:] + " " + anchor).strip()
        out.append(FoundLink(url=url, label=label, page_url=base_url, found_by=found_by, near=near))
    return out


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": settings.fetch_user_agent},
        follow_redirects=True,
        timeout=httpx.Timeout(45.0, connect=20.0),
    )


async def links_from_page(url: str, found_by: str = "html") -> list[FoundLink]:
    async with _client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        if "html" not in resp.headers.get("content-type", "html"):
            return []
        return extract_links(resp.text, str(resp.url), found_by)


def parse_dspace_search(page_html: str, base: str, code_variants: list[str]) -> list[tuple[str, str]]:
    """(item_url, title) for search hits whose title names the course code."""
    norm_codes = {c.replace(" ", "").upper() for c in code_variants}
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _ANCHOR.finditer(page_html):
        href = html.unescape(m.group(1))
        if "/handle/" not in href or "/browse" in href or "search" in href or "discover" in href:
            continue
        title = _text(m.group(2)).lstrip("﻿").strip()
        compact = title.replace(" ", "").upper()
        if not any(c in compact for c in norm_codes):
            continue
        url = urljoin(base.rstrip("/") + "/", href)
        if url in seen:
            continue
        seen.add(url)
        items.append((url, title))
    return items


def parse_dspace_item(page_html: str, item_url: str) -> list[str]:
    hrefs = {html.unescape(h) for h in re.findall(r"href=\"([^\"]*/bitstream/[^\"]+)\"", page_html)}
    return sorted(urljoin(item_url, h) for h in hrefs)


async def dspace_search(base: str, code_variants: list[str], query: str) -> list[FoundLink]:
    """Search a DSpace (XMLUI) repository and return bitstream links labelled by item title."""
    out: list[FoundLink] = []
    async with _client() as client:
        resp = await client.get(f"{base.rstrip('/')}/search?query={quote_plus(query)}&rpp=100")
        resp.raise_for_status()
        for item_url, title in parse_dspace_search(resp.text, base, code_variants):
            item = await client.get(item_url)
            if item.status_code != 200:
                continue
            for bs in parse_dspace_item(item.text, item_url):
                out.append(FoundLink(url=bs, label=title, page_url=item_url, found_by=f"dspace:{urlparse(base).netloc}"))
    return out
