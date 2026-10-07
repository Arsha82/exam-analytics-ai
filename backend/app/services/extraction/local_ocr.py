"""
Local page OCR with Unlimited-OCR (DeepSeek-OCR, 3B) through Ollama.

Sized for small GPUs: num_ctx is capped (default 4096) so the model fits in ~4 GB VRAM
instead of reserving a 32k-token KV cache, and whole pages are sent at <=1280 px
instead of many bands (one call per page).
"""

import asyncio
import base64
import io
import logging
import re
import zlib

import httpx
from PIL import Image, ImageChops, ImageDraw

from app.config import settings

logger = logging.getLogger(__name__)


class LocalOcrError(RuntimeError):
    pass


def prepare_image(img: Image.Image, max_side: int = 1280) -> Image.Image:
    rgb = img.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255)))
    bbox = diff.getbbox()
    if bbox:
        m = 30
        rgb = rgb.crop((max(0, bbox[0] - m), max(0, bbox[1] - m), min(rgb.width, bbox[2] + m), min(rgb.height, bbox[3] + m)))
    rgb.thumbnail((max_side, max_side))
    return rgb


async def _generate(prepared: Image.Image, timeout: float, repeat_penalty: float | None = None) -> str:
    buf = io.BytesIO()
    prepared.save(buf, format="JPEG", quality=90)
    options = {"temperature": 0.0, "num_ctx": settings.ocr_num_ctx, "num_predict": settings.ocr_num_predict}
    if repeat_penalty:
        options |= {"repeat_penalty": repeat_penalty, "repeat_last_n": 128}
    payload = {
        "model": settings.ollama_ocr_model,
        "prompt": "<image>\nDocument parsing.",
        "images": [base64.b64encode(buf.getvalue()).decode()],
        "stream": False,
        "keep_alive": "15m",
        # num_predict caps a runaway repetition loop (a full page needs ~1.5k tokens).
        "options": options,
    }
    last: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
                resp = await client.post(f"{settings.ollama_base_url.rstrip('/')}/api/generate", json=payload)
                resp.raise_for_status()
                return resp.json().get("response", "")
        except httpx.HTTPError as exc:  # 500s happen when the runner is reloading / short on VRAM
            last = exc
            logger.warning(f"local OCR attempt {attempt + 1} failed: {type(exc).__name__}: {exc}")
            await asyncio.sleep(5 * (attempt + 1))
    raise LocalOcrError(f"local OCR failed: {type(last).__name__}: {last}")


def degenerate_regions(raw: str) -> list[list[float]]:
    """
    Bboxes (0-1000 grid) of blocks where the model fell into a repetition loop: far more
    text than the box can physically hold, or text that compresses to almost nothing.
    Stamps/seals in a corner are the usual trigger.
    """
    from app.services.extraction.ocr_parser import parse_blocks

    out = []
    for b in parse_blocks(raw, 0):
        n = len(b.text)
        if n < 250:
            continue
        w = max(1.0, b.bbox[2] - b.bbox[0])
        h = max(10.0, b.bbox[3] - b.bbox[1])
        capacity = w * h / 60.0
        ratio = len(zlib.compress(b.text.encode("utf-8"))) / n
        if n > 3 * capacity + 80 or ratio < 0.12:
            out.append(b.bbox)
    return out


def _mask(img: Image.Image, boxes: list[list[float]]) -> Image.Image:
    masked = img.copy()
    draw = ImageDraw.Draw(masked)
    w, h = masked.size
    for x1, y1, x2, y2 in boxes:
        m = 8
        draw.rectangle([x1 * w / 1000 - m, y1 * h / 1000 - m, x2 * w / 1000 + m, y2 * h / 1000 + m], fill=(255, 255, 255))
    return masked


_BBOX_LINE = re.compile(r"^(\s*[a-z_]+\s*\[\s*)(\d+)(\s*,\s*)(\d+)(\s*,\s*)(\d+)(\s*,\s*)(\d+)(\s*\].*)$")


def _remap_rows(raw: str, y0: float, scale: float) -> str:
    """Map bboxes of an OCR'd horizontal slice back onto the full page's 0-1000 grid."""
    out = []
    for line in raw.splitlines():
        m = _BBOX_LINE.match(line)
        if m:
            y1 = round(y0 + int(m.group(4)) * scale)
            y2 = round(y0 + int(m.group(8)) * scale)
            line = f"{m.group(1)}{m.group(2)}{m.group(3)}{y1}{m.group(5)}{m.group(6)}{m.group(7)}{y2}{m.group(9)}"
        out.append(line)
    return "\n".join(out)


async def _ocr_halves(prepared: Image.Image, timeout: float) -> str:
    """Read the page as two overlapping halves; changes the model's context enough to break a loop."""
    w, h = prepared.size
    cut, overlap = h // 2, int(h * 0.06)
    parts = []
    for top, bottom in ((0, cut + overlap), (cut - overlap, h)):
        piece = prepared.crop((0, top, w, bottom))
        raw = await _generate(piece, timeout, repeat_penalty=1.15)
        if is_degenerate(raw):
            continue  # give up on this half rather than keep a loop
        parts.append(_remap_rows(raw, top * 1000 / h, (bottom - top) / h))
    return "\n".join(parts)


def _blank_cuts(img: Image.Image, n: int) -> list[int]:
    """Row positions splitting the page into n strips, each moved to the emptiest row nearby
    (white space between questions), so no line of text is cut and no overlap is needed."""
    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()
    step = max(1, w // 200)
    ink = [sum(255 - px[x, y] for x in range(0, w, step)) for y in range(h)]
    cuts, win = [], int(h * 0.06)
    for k in range(1, n):
        target = h * k // n
        lo, hi = max(1, target - win), min(h - 1, target + win)
        cuts.append(min(range(lo, hi), key=lambda y: (sum(ink[max(0, y - 3): y + 4]), abs(y - target))))
    return [0, *cuts, h]


async def _ocr_strips(prepared: Image.Image, timeout: float, n: int, escalate: bool) -> str:
    """Read the page as n horizontal strips: dense pages (e.g. 50-question MCQ papers) make the
    model loop or stop early when read whole; short strips keep each read small."""
    w, h = prepared.size
    bounds = _blank_cuts(prepared, n)
    parts = []
    for top, bottom in zip(bounds, bounds[1:]):
        piece = prepared.crop((0, top, w, bottom))
        raw = await _generate(piece, timeout)
        if is_degenerate(raw) and escalate:
            raw = await _generate(piece, timeout, repeat_penalty=1.15)
        if is_degenerate(raw) and len(raw) > 4000:
            logger.info("OCR strip still loops; keeping only its first part")
            raw = raw[:4000]
        parts.append(_remap_rows(raw, top * 1000 / h, (bottom - top) / h))
    return "\n".join(parts)


TAIL_LOOP_Y = 750  # on the 0-1000 page grid
WATERMARK_GREY = 165  # strip mode: pixels lighter than this are background/watermark
_QNUM_START = re.compile(r"^(\d{1,2})\s*(?:\(?[a-e]\))?[.)]?\s+[A-Za-z\\$(]")


def repeats_itself(raw: str) -> bool:
    """
    Loops made of normal-looking lines: the same block (text) emitted 3+ times, or the
    reading jumping back to earlier question numbers twice or more (the model re-reading
    part of the page instead of finishing it). Masking would erase real text here.
    """
    from collections import Counter

    from app.services.extraction.ocr_parser import parse_blocks

    blocks = [b for b in parse_blocks(raw, 0) if len(b.text) >= 20]
    counts = Counter(b.text for b in blocks)
    # Where does the loop start? A loop in the bottom quarter usually begins after the real
    # content was read (a tail loop) and is tolerated; one higher up is losing text.
    loop_tops = [b.bbox[1] for b in blocks if counts[b.text] >= 3]
    starts = [(b.bbox[1], int(m.group(1))) for b in parse_blocks(raw, 0)
              if (m := _QNUM_START.match(b.text)) and 1 <= int(m.group(1)) <= 60]
    restart_tops = [starts[i + 1][0] for i in range(len(starts) - 1) if starts[i + 1][1] < starts[i][1]]
    if len(restart_tops) >= 2:
        loop_tops.append(restart_tops[0])
    return bool(loop_tops) and min(loop_tops) < TAIL_LOOP_Y


def is_degenerate(raw: str) -> bool:
    return bool(degenerate_regions(raw)) or repeats_itself(raw)


async def ocr_image(img: Image.Image, timeout: float = 420.0, escalate: bool = False,
                    strips: int = 0) -> tuple[str, Image.Image]:
    """
    OCR one page image. Returns (raw model output with labels/bboxes, the image sent).

    A dense looping region (e.g. a college stamp) is always whited out and re-read: it
    ruins the whole page. With `escalate` (used on demand, when a looped page holds a
    flagged question), remaining loops are retried with a repetition penalty and then
    read as two overlapping halves.
    """
    if strips > 1:
        # Dense papers often carry a light-grey college watermark behind the text, which makes the
        # model hallucinate; printed text is near-black, so whitening light greys removes it. Done
        # at full resolution: after downscaling, thin strokes turn grey and would be erased too.
        img = img.convert("L").point(lambda v: 255 if v > WATERMARK_GREY else v).convert("RGB")
        prepared = prepare_image(img)
        return await _ocr_strips(prepared, timeout, strips, escalate), prepared
    prepared = prepare_image(img)
    raw = await _generate(prepared, timeout)
    for _ in range(2):
        located = [b for b in degenerate_regions(raw) if b[3] - b[1] >= 5]
        if not located:
            break
        logger.info(f"OCR loop in {len(located)} region(s); masking and re-reading")
        prepared = _mask(prepared, located)
        raw = await _generate(prepared, timeout)
    if not escalate:
        return raw, prepared
    if is_degenerate(raw):
        logger.info("OCR loop persists; retrying with a repetition penalty")
        raw = await _generate(prepared, timeout, repeat_penalty=1.15)
    if is_degenerate(raw):
        logger.info("OCR loop persists; reading the page in two halves")
        raw = await _ocr_halves(prepared, timeout)
    return raw, prepared


async def available() -> tuple[bool, str | None]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            names = [m.get("name") for m in resp.json().get("models", [])]
    except Exception as exc:  # noqa: BLE001
        return False, f"Ollama not reachable: {exc}"
    if settings.ollama_ocr_model not in names:
        return False, f"OCR model {settings.ollama_ocr_model} not pulled"
    return True, None
