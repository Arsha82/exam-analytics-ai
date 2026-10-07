"""PDF/image helpers: page rendering, born-digital vs scanned detection, text layer."""

from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image


@dataclass
class DocInfo:
    pages: int
    scanned: bool  # pages are images (an OCR text layer, if any, is not trusted)
    text_chars: int


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def doc_info(path: Path) -> DocInfo:
    if not is_pdf(path):
        return DocInfo(pages=1, scanned=True, text_chars=0)
    pdf = pdfium.PdfDocument(str(path))
    scanned_pages = 0
    chars = 0
    try:
        for page in pdf:
            w, h = page.get_size()
            chars += len((page.get_textpage().get_text_range() or "").strip())
            for obj in page.get_objects():
                if obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
                    left, bottom, right, top = obj.get_bounds()
                    if (right - left) * (top - bottom) >= 0.6 * w * h:
                        scanned_pages += 1
                        break
        return DocInfo(pages=len(pdf), scanned=scanned_pages > 0, text_chars=chars)
    finally:
        pdf.close()


def text_layer(path: Path) -> list[str]:
    if not is_pdf(path):
        return [""]
    pdf = pdfium.PdfDocument(str(path))
    try:
        return [(p.get_textpage().get_text_range() or "") for p in pdf]
    finally:
        pdf.close()


def render_page(path: Path, index: int, scale: float = 2.0) -> Image.Image:
    if not is_pdf(path):
        with Image.open(path) as img:
            return img.convert("RGB")
    pdf = pdfium.PdfDocument(str(path))
    try:
        return pdf[index].render(scale=scale).to_pil().convert("RGB")
    finally:
        pdf.close()
