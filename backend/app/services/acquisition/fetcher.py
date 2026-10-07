"""
Fetcher — downloads candidates, verifies they are real documents, stores them by hash.

Only files whose bytes start with a PDF/PNG/JPEG signature are accepted; HTML pages are
reported back so the caller can mine them for links instead.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import settings
from app.services.acquisition.connectors import drive_file_id

SIGNATURES = {
    b"%PDF": ("application/pdf", "pdf"),
    b"\x89PNG": ("image/png", "png"),
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
}


class FetchError(RuntimeError):
    pass


@dataclass
class Fetched:
    sha256: str
    path: Path
    bytes: int
    mime: str
    final_url: str


@dataclass
class FetchedPage:
    html: str
    final_url: str


def sniff(head: bytes) -> tuple[str, str] | None:
    for sig, info in SIGNATURES.items():
        if head.startswith(sig):
            return info
    return None


def store_bytes(data: bytes, ext: str) -> tuple[str, Path]:
    sha = hashlib.sha256(data).hexdigest()
    folder = settings.storage_dir / "sources" / sha[:2]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}.{ext}"
    if not path.exists():
        path.write_bytes(data)
    return sha, path


async def _download(client: httpx.AsyncClient, url: str) -> tuple[bytes, str, str]:
    async with client.stream("GET", url) as resp:
        if resp.status_code >= 400:
            raise FetchError(f"HTTP {resp.status_code}")
        chunks: list[bytes] = []
        size = 0
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > settings.fetch_max_bytes:
                raise FetchError(f"larger than {settings.fetch_max_bytes // (1024 * 1024)} MB")
            chunks.append(chunk)
        return b"".join(chunks), resp.headers.get("content-type", ""), str(resp.url)


async def fetch(url: str) -> Fetched | FetchedPage:
    """Download `url`. Google Drive file links are converted to direct downloads."""
    targets = [url]
    fid = drive_file_id(url)
    if fid:
        targets = [
            f"https://drive.google.com/uc?export=download&id={fid}",
            f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t",
        ]
    last_html: FetchedPage | None = None
    async with httpx.AsyncClient(
        headers={"User-Agent": settings.fetch_user_agent},
        follow_redirects=True,
        timeout=httpx.Timeout(settings.fetch_timeout_seconds, connect=20.0),
    ) as client:
        for target in targets:
            data, ctype, final = await _download(client, target)
            kind = sniff(data[:8])
            if kind:
                mime, ext = kind
                sha, path = store_bytes(data, ext)
                return Fetched(sha256=sha, path=path, bytes=len(data), mime=mime, final_url=final)
            if "html" in ctype or data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
                last_html = FetchedPage(html=data.decode("utf-8", errors="replace"), final_url=final)
                continue
            raise FetchError(f"not a PDF or image (content-type {ctype or 'unknown'})")
    if last_html is not None:
        if fid and re.search(r"Google Drive - (Virus scan warning|Quota exceeded)|accounts\.google\.com", last_html.html):
            raise FetchError("Google Drive refused the download (permission, quota or scan warning)")
        return last_html
    raise FetchError("no content")
