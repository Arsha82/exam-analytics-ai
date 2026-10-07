import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixture_text():
    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _read


@pytest.fixture
def jun2024_transcript():
    """Real agy transcription of MAT201 June 2024 (one entry per question/sub-part)."""
    from app.services.transcript import Transcript, TranscriptHeader, TranscriptQuestion
    from app.services.acquisition.sessions import parse_session

    d = json.loads((FIXTURES / "mat201_jun2024_transcript.json").read_text(encoding="utf-8"))
    h = d["header"]
    month, year = parse_session(f"{h['month']} {h['year']}")
    return Transcript(
        header=TranscriptHeader(course_code=h["course_code"], course_name=h["course_name"], exam_title=h["exam_title"],
                                month=month, year=year, qp_code=h["qp_code"], max_marks=h["max_marks"]),
        questions=[TranscriptQuestion(part=q["part"], number=q["number"], sub=q.get("sub"), marks=q["marks"],
                                      text=q["text"], module=q.get("module"), legibility=q.get("legibility", "clear"))
                   for q in d["questions"]],
        provider="agy",
    )
