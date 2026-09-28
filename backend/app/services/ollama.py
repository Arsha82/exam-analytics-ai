"""
PYQ Analyzer — Ollama Service Client.

Handles interaction with local Ollama instance for:
- Document OCR vision inference (Unlimited-OCR)
- Structuring, reasoning, and grading inference (gemma4:12b)
- Vector embedding generation (nomic-embed-text)
"""

import base64
import json
import logging
import re
from typing import Any
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class OllamaService:
    """Async client for local Ollama server."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.timeout = httpx.Timeout(360.0, connect=30.0)

    async def check_health(self) -> dict[str, Any]:
        """Verify Ollama server connectivity and available models."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    return {"status": "ok", "models": models}
                return {"status": "error", "message": f"HTTP {resp.status_code}"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """
        Generate vector embeddings using nomic-embed-text.
        """
        model = model or settings.embedding_model
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": model, "input": texts},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("embeddings", [])
                
                # Fallback to single /api/embeddings endpoint if /api/embed isn't supported
                logger.warning(f"/api/embed returned {resp.status_code}, falling back to /api/embeddings")
                results = []
                for t in texts:
                    r = await client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": model, "prompt": t},
                    )
                    r.raise_for_status()
                    results.append(r.json().get("embedding", []))
                return results
            except Exception as e:
                logger.error(f"Failed to generate embeddings: {e}")
                raise

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        format_json: bool = False,
    ) -> str:
        """
        Generate completion from local LLM (e.g., gemma4:12b).
        """
        model = model or settings.ollama_structuring_model
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": 8192,
            },
        }
        if system:
            payload["system"] = system
        if format_json:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")

    async def generate_json(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        force_grammar: bool = False,
    ) -> dict[str, Any] | list[Any]:
        """
        Generate and parse JSON response from LLM with robust substring extraction.
        By default force_grammar=False to prevent Ollama GBNF grammar freeze on large-context models.
        """
        raw = ""
        json_prompt = prompt
        if not force_grammar and "JSON" not in prompt:
            json_prompt = prompt + "\n\nCRITICAL: Respond ONLY with valid raw JSON. Do not include markdown fences or explanation."

        if force_grammar:
            try:
                raw = await self.generate(
                    prompt=prompt,
                    system=system,
                    model=model,
                    temperature=temperature,
                    format_json=True,
                )
            except Exception as e:
                logger.warning(f"Ollama grammar-constrained generate_json failed ({e}), retrying without format='json'...")
                raw = await self.generate(
                    prompt=json_prompt,
                    system=system,
                    model=model,
                    temperature=temperature,
                    format_json=False,
                )
        else:
            raw = await self.generate(
                prompt=json_prompt,
                system=system,
                model=model,
                temperature=temperature,
                format_json=False,
            )

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            clean = raw.strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            elif clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
            start_dict = clean.find("{")
            start_list = clean.find("[")
            if start_dict != -1 and (start_list == -1 or start_dict < start_list):
                end_dict = clean.rfind("}")
                if end_dict != -1:
                    clean = clean[start_dict : end_dict + 1]
            elif start_list != -1:
                end_list = clean.rfind("]")
                if end_list != -1:
                    clean = clean[start_list : end_list + 1]
            return json.loads(clean.strip())

    @staticmethod
    def clean_ocr_markdown(raw_text: str) -> str:
        """
        Cleans raw OCR output from Unlimited-OCR / DeepSeek-OCR models:
        - Strips token tags (e.g. 'text [y1, x1, y2, x2]')
        - Strips standalone coordinate arrays '[47, 294, 406, 412]'
        - Maps 'title' and 'header' tags to '# '
        - Maps 'section' and 'sub_header' tags to '## '
        - Filters out vision model boilerplate hallucinations (e.g. 'too blurry', 'cannot read')
        - Preserves LaTeX formulas '\\( ... \\)' and '\\[ ... \\]'
        """
        lines = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Skip lone brackets or indices like [1] or 1.2
            if re.match(r"^\[\s*\d+\s*\]$", line) or re.match(r"^\d+\.\d+$", line):
                continue
            # Skip vision model boilerplate hallucinations
            if any(h in line.lower() for h in ["too blurry", "blurry to recognize", "cannot read", "the following table is a table"]):
                continue

            is_title = bool(re.match(r"^(?:title|header)\b", line, re.IGNORECASE))
            is_section = bool(re.match(r"^(?:section|sub_header)\b", line, re.IGNORECASE))

            # Strip label and 4-coordinate bbox: e.g. "text [27, 72, 237, 113]MID-TERM..." -> "MID-TERM..."
            # Note: 4 numbers are matched so mathematical intervals like [1, 3] are preserved.
            cleaned = re.sub(r"^[a-zA-Z_]+\s*\[\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\]\s*", "", line)
            cleaned = re.sub(r"\[\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\]\s*", "", cleaned).strip()

            if not cleaned:
                continue

            if is_title and not cleaned.startswith("#"):
                lines.append(f"# {cleaned}")
            elif is_section and not cleaned.startswith("#"):
                lines.append(f"## {cleaned}")
            else:
                lines.append(cleaned)

        return "\n".join(lines)

    async def generate_vision_ocr(
        self,
        image_bytes: bytes,
        prompt: str | None = None,
        model: str | None = None,
    ) -> str:
        """
        Perform OCR on an image using Unlimited-OCR (or vision LLM with automatic fallback).
        """
        primary_model = model or settings.ollama_ocr_model
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        is_ocr_specialist = any(
            k in primary_model.lower() for k in ["unlimited-ocr", "deepseek", "ocr", "teleocr", "navidc"]
        )

        if prompt is None:
            if is_ocr_specialist:
                effective_prompt = "<image>\nDocument parsing."
            else:
                effective_prompt = (
                    "Extract all text, question numbers, marks, and diagrams from this exam paper image in structured markdown."
                )
        else:
            effective_prompt = prompt
            if is_ocr_specialist and "<image>" not in effective_prompt:
                effective_prompt = f"<image>\n{effective_prompt}"

        payload = {
            "model": primary_model,
            "prompt": effective_prompt,
            "images": [b64_image],
            "stream": False,
            "options": {"temperature": 0.0},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                resp.raise_for_status()
                raw_text = resp.json().get("response", "")
                if is_ocr_specialist:
                    cleaned = self.clean_ocr_markdown(raw_text)
                    return cleaned or raw_text
                return raw_text
            except Exception as primary_err:
                fallback_model = settings.ollama_vision_fallback_model
                if primary_model != fallback_model and fallback_model:
                    logger.warning(
                        f"Primary vision OCR model '{primary_model}' failed ({primary_err}). "
                        f"Falling back to '{fallback_model}'..."
                    )
                    payload["model"] = fallback_model
                    payload["prompt"] = (
                        "Extract all text, question numbers, marks, and diagrams from this exam paper in clean structured Markdown."
                    )
                    resp = await client.post(
                        f"{self.base_url}/api/generate",
                        json=payload,
                    )
                    resp.raise_for_status()
                    return resp.json().get("response", "")
                raise


ollama_service = OllamaService()
