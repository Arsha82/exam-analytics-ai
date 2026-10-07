import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.services.agy import AgyClient, AgyError, AgyUnavailable, _parse_stream


def stream(response: str = "", status: str = "SUCCESS", conv: str = "c1", error=None, model: str = "m") -> str:
    lines = [json.dumps({"event": "init", "init": {"model": model}})]
    lines.append(json.dumps({"event": "result", "result": {
        "status": status, "response": response, "conversation_id": conv, "error": error,
        "usage": {"input_tokens": 10, "output_tokens": 5}}}))
    return "\n".join(lines)


class Fake(AgyClient):
    """AgyClient with the subprocess replaced by scripted replies."""

    def __init__(self, replies):
        super().__init__(binary="python", concurrency=2)
        self.replies = list(replies)
        self.calls: list[list[str]] = []
        self._agents_synced = True

    def resolve_binary(self):
        return "agy"

    def _call(self, args, stdin, cwd, timeout):
        self.calls.append(args)
        return 0, self.replies.pop(0), ""


class Reply(BaseModel):
    candidates: list[str]


def test_parse_stream():
    model, result = _parse_stream("noise\n" + stream("hi", model="gemini-x"))
    assert model == "gemini-x" and result["response"] == "hi"


@pytest.mark.asyncio
async def test_empty_reply_is_retried_in_same_conversation(tmp_path: Path):
    c = Fake([stream(""), stream('{"candidates": ["a"]}')])
    res = await c.run("q", agent="pyq-scout", model="m1", cwd=tmp_path)
    assert res.text.startswith("{") and res.attempts == 2
    assert "--conversation" in c.calls[1] and "c1" in c.calls[1]
    assert res.usage["input_tokens"] == 20


@pytest.mark.asyncio
async def test_falls_back_to_other_model(tmp_path: Path):
    c = Fake([stream("", status="ERROR", conv="", error="internal"), stream("ok")])
    res = await c.run("q", agent="a", model="m1", cwd=tmp_path, fallback_model="m2")
    assert res.text == "ok"
    assert c.calls[1][c.calls[1].index("--model") + 1] == "m2"


@pytest.mark.asyncio
async def test_quota_error_sets_cooldown(tmp_path: Path):
    c = Fake([stream("", status="ERROR", error="RESOURCE_EXHAUSTED: quota")])
    with pytest.raises(AgyUnavailable):
        await c.run("q", agent="a", model="m1", cwd=tmp_path)
    assert not c.status()["available"] or c.status()["cooldown_seconds"] > 0


@pytest.mark.asyncio
async def test_run_json_repairs_invalid_json(tmp_path: Path):
    c = Fake([stream("Sure! here: not json"), stream('```json\n{"candidates": ["x", "y"]}\n```')])
    parsed, _ = await c.run_json("q", Reply, agent="a", model="m1", cwd=tmp_path)
    assert parsed.candidates == ["x", "y"]


@pytest.mark.asyncio
async def test_gives_up_after_retries(tmp_path: Path):
    c = Fake([stream(""), stream(""), stream("", conv="")])
    with pytest.raises(AgyError):
        await c.run("q", agent="a", model="m1", cwd=tmp_path, fallback_model="m2")


def test_never_skips_permissions():
    src = (Path(__file__).resolve().parent.parent / "app" / "services" / "agy.py").read_text(encoding="utf-8")
    code_lines = [l for l in src.splitlines() if not l.strip().startswith("#") and "never" not in l.lower()]
    assert not any("dangerously-skip-permissions" in l for l in code_lines)


@pytest.mark.asyncio
async def test_tagging_maps_short_ids_back(tmp_path: Path):
    from app.services.tagging import TagItem, tag_module

    topics = [{"id": "mat201.m1.lagrange", "name": "Lagrange", "keywords": []},
              {"id": "mat201.m1.charpit", "name": "Charpit", "keywords": ["pq"]}]
    items = [TagItem("MAT201_202012_x_q11a", 1, "Solve the PDE x p + y q = z"),
             TagItem("MAT201_202012_x_q12a", 1, "Solve 2xz - px^2 - 2qxy + pq = 0")]
    reply = '{"labels": [{"id": "q1", "topics": ["t1", "t9"], "kind": "problem", "confidence": 0.9}, {"id": "q2", "topics": ["t2"], "kind": "problem", "confidence": 0.8}]}'
    c = Fake([stream(reply)])
    out = {r.id: r for r in await tag_module(c, 1, "PDE", topics, items, tmp_path)}
    assert out["MAT201_202012_x_q11a"].topics == [("mat201.m1.lagrange", 0.9)]  # unknown t9 dropped
    assert out["MAT201_202012_x_q12a"].topics[0][0] == "mat201.m1.charpit"
    prompt = c.calls[0][c.calls[0].index("-p") + 1]
    assert "MAT201_202012_x_q11a" not in prompt and "mat201.m1.lagrange" not in prompt
