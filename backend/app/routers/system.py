"""System router (v2) — availability of external tools (agy, Ollama OCR, Podman)."""

import shutil

from fastapi import APIRouter

from app.config import settings
from app.services.agy import agy_client
from app.services.extraction import local_ocr

router = APIRouter()


@router.get("/status")
async def system_status():
    ocr_ok, ocr_reason = await local_ocr.available()
    return {
        "agy": agy_client.status() | {"models": {"scout": settings.agy_scout_model, "reader": settings.agy_reader_model,
                                                  "tagger": settings.agy_tagger_model,
                                                  "fallback": settings.agy_fallback_model},
                                       "concurrency": settings.agy_concurrency},
        "local_ocr": {"available": ocr_ok, "reason": ocr_reason, "model": settings.ollama_ocr_model,
                      "num_ctx": settings.ocr_num_ctx},
        "podman": {"available": shutil.which("podman") is not None, "binary": shutil.which("podman")},
    }
