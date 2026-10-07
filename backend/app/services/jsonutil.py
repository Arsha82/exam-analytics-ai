"""Lenient JSON extraction from model replies (fences, prose around the object)."""

import json
from typing import Any


def extract_json(raw: str) -> Any:
    """Parse the first JSON object/array in `raw`. Raises ValueError if none parses."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty reply")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON object in reply")
    start = min(starts)
    closer = "}" if text[start] == "{" else "]"
    end = text.rfind(closer)
    if end <= start:
        raise ValueError("unterminated JSON in reply")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in reply: {exc}") from exc
