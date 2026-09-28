"""
PYQ Analyzer — OCR Agent.

Processes scanned exam papers (PDF or images) using:
- Unlimited-OCR (SOTA document OCR via Ollama vision with DeepSeek-style document parsing trigger)
- Intelligent whitespace margin cropping & adaptive page banding (eliminating timeouts & resolution degradation)
- pypdfium2 for high-resolution page rendering
- Native text stream extraction fallback
"""

import io
import logging
from pathlib import Path
import re
from typing import Any
from PIL import Image, ImageChops
import pypdfium2 as pdfium
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.config import settings
from app.models.paper import Paper
from app.services.ollama import ollama_service

logger = logging.getLogger(__name__)


def preprocess_image(pil_img: Image.Image) -> Image.Image:
    """
    Auto-crop excessive whitespace borders so that text tokens are not
    downscaled into illegibility by vision encoders.
    """
    rgb = pil_img.convert("RGB")
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    diff = ImageChops.difference(rgb, bg)
    bbox = diff.getbbox()
    if bbox:
        margin = 35
        crop_box = (
            max(0, bbox[0] - margin),
            max(0, bbox[1] - margin),
            min(rgb.width, bbox[2] + margin),
            min(rgb.height, bbox[3] + margin),
        )
        return rgb.crop(crop_box)
    return rgb


def merge_band_texts(band_texts: list[str]) -> str:
    """Merge text extracted from overlapping vertical bands with deduplication."""
    merged_lines: list[str] = []
    seen_lines: set[str] = set()

    for text in band_texts:
        for line in text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            norm = re.sub(r"\W+", "", line_str.lower())
            if len(norm) > 10 and norm in seen_lines:
                continue
            if len(norm) > 10:
                seen_lines.add(norm)
            merged_lines.append(line_str)

    return "\n".join(merged_lines)


class OcrAgent(BaseAgent):
    """Agent that extracts structured text and markdown from scanned papers."""

    name: str = "OcrAgent"

    async def _ocr_image_adaptive(self, img: Image.Image) -> str:
        """
        Process an image using adaptive banding if tall, or direct inference if standard.
        """
        cropped = preprocess_image(img)
        w, h = cropped.size

        # If image height is large (tall full-page scan > 850px), split into bands
        # to ensure fast local inference (< 25s per chunk) and zero timeouts.
        if h > 850:
            band_height = 650
            overlap = 80
            bands: list[Image.Image] = []
            y = 0
            while y < h:
                y2 = min(h, y + band_height)
                bands.append(cropped.crop((0, y, w, y2)))
                if y2 >= h:
                    break
                y += band_height - overlap

            band_results: list[str] = []
            for b in bands:
                buf = io.BytesIO()
                b.save(buf, format="JPEG", quality=85)
                res = await ollama_service.generate_vision_ocr(
                    image_bytes=buf.getvalue(),
                    prompt="<image>\nDocument parsing.",
                )
                if res and res.strip():
                    band_results.append(res)

            return merge_band_texts(band_results)
        else:
            buf = io.BytesIO()
            cropped.save(buf, format="JPEG", quality=88)
            return await ollama_service.generate_vision_ocr(
                image_bytes=buf.getvalue(),
                prompt="<image>\nDocument parsing.",
            )

    async def run(self, paper_id: str, **kwargs) -> dict[str, Any]:
        """
        Execute OCR on a paper.

        Args:
            paper_id: The ID of the paper to process.
        """
        await self.emit_progress("ocr", 5, f"Starting OCR for paper {paper_id}")

        query = select(Paper).where(Paper.paper_id == paper_id)
        result = await self.db.execute(query)
        paper = result.scalar_one_or_none()

        if not paper:
            await self.emit_progress("ocr", 100, f"Paper {paper_id} not found")
            return {"status": "failed", "error": f"Paper {paper_id} not found"}

        source_path = Path(paper.source_file)
        if not source_path.exists():
            # Check relative to upload_dir
            source_path = settings.upload_dir / source_path.name
            if not source_path.exists():
                paper.ocr_status = "failed"
                paper.needs_review = True
                await self.db.commit()
                return {"status": "failed", "error": f"File not found: {paper.source_file}"}

        page_texts: list[str] = []
        is_pdf = source_path.suffix.lower() == ".pdf"

        try:
            if is_pdf:
                pdf = pdfium.PdfDocument(str(source_path))
                num_pages = len(pdf)
                await self.emit_progress("ocr", 15, f"Loaded PDF with {num_pages} page(s)")

                for i, page in enumerate(pdf):
                    pct = 15 + int((i / max(num_pages, 1)) * 75)
                    await self.emit_progress("ocr", pct, f"Processing page {i+1} of {num_pages}")

                    # Check for native digital text stream first
                    text_page = page.get_textpage()
                    native_text = (text_page.get_text_range() or "").strip()

                    # If page contains rich digital text (> 120 chars), use it directly
                    if len(native_text) >= 120:
                        self.logger.info(f"Page {i+1} has digital text stream ({len(native_text)} chars)")
                        extracted = native_text
                    else:
                        # Scanned page — render at 2.0x scale (144 DPI) and run adaptive vision OCR
                        pil_image = page.render(scale=2.0).to_pil()
                        try:
                            extracted = await self._ocr_image_adaptive(pil_image)
                        except Exception as vision_err:
                            self.logger.warning(f"Vision OCR failed on page {i+1}: {vision_err}")
                            extracted = native_text or f"[Page {i+1} OCR extraction failed]"

                    page_texts.append(f"--- Page {i+1} ---\n" + extracted)

            else:
                # Standalone image file (PNG, JPG, TIFF, WEBP)
                await self.emit_progress("ocr", 30, f"Processing image file {source_path.name}")
                with Image.open(source_path) as img:
                    extracted = await self._ocr_image_adaptive(img)
                page_texts.append(extracted)

            full_ocr_text = "\n\n".join(page_texts)

            # Update Paper record
            paper.ocr_status = "completed"
            await self.db.commit()

            await self.emit_progress("ocr", 100, f"OCR completed successfully for {paper_id}")

            return {
                "status": "complete",
                "paper_id": paper_id,
                "pages_count": len(page_texts),
                "pages": page_texts,
                "raw_text": full_ocr_text,
            }

        except Exception as e:
            self.logger.error(f"OCR failed for {paper_id}: {e}", exc_info=True)
            paper.ocr_status = "failed"
            paper.needs_review = True
            await self.db.commit()
            await self.emit_progress("ocr", 100, f"OCR failed: {str(e)}")
            return {"status": "failed", "error": str(e)}
