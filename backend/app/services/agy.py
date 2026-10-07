"""
agy (Antigravity CLI) harness — runs Gemini through the user's own agy login.

Design rules (docs/PLAN-v2.md §5.3):
- subprocess in a worker thread, so it works under any asyncio loop on Windows;
- read-only agents with tool allowlists, never --dangerously-skip-permissions;
- no --json-schema together with tools (it makes headless tool calls get denied):
  JSON is requested in the prompt and validated here with Pydantic;
- empty SUCCESS replies (a known agy bug) are retried in the same conversation,
  then on a fallback model; quota/auth errors put agy on a cooldown;
- global concurrency limit (8 parallel high-effort calls all came back empty in testing).
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings
from app.services.jsonutil import extract_json

logger = logging.getLogger(__name__)

AGENTS_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "agy_agents"
MAX_ARG_PROMPT_CHARS = 24000  # Windows caps a command line at 32767 chars
NUDGE = (
    "Your previous turn ended without an answer. Using only your own tools, answer the "
    "original request now, in the required format."
)
_QUOTA_RE = re.compile(r"quota|rate.?limit|exhausted|429|authenticat|log.?in|credential|unauthori", re.I)

EventFn = Callable[[str, str, dict | None], Awaitable[None]]
M = TypeVar("M", bound=BaseModel)


class AgyUnavailable(RuntimeError):
    """agy is missing, disabled, logged out or out of quota."""


class AgyError(RuntimeError):
    """agy ran but produced no usable answer."""


@dataclass
class AgyResult:
    text: str
    model: str | None
    status: str | None
    error: str | None
    usage: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1
    duration_s: float = 0.0
    conversation_id: str | None = None


def _parse_stream(stdout: str) -> tuple[str | None, dict[str, Any]]:
    model: str | None = None
    result: dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("event") == "init" and model is None:
            model = (ev.get("init") or {}).get("model")
        elif ev.get("event") == "result":
            result = ev.get("result") or {}
    return model, result


class AgyClient:
    def __init__(self, binary: str | None = None, concurrency: int | None = None):
        self.binary = binary or settings.agy_bin
        self._sem = asyncio.Semaphore(concurrency or settings.agy_concurrency)
        self._cooldown_until = 0.0
        self._agents_synced = False

    # ── availability ──
    def resolve_binary(self) -> str | None:
        return shutil.which(self.binary)

    def status(self) -> dict[str, Any]:
        path = self.resolve_binary()
        cooling = max(0, int(self._cooldown_until - time.time()))
        reason = None
        if not settings.agy_enabled:
            reason = "disabled in settings"
        elif not path:
            reason = f"'{self.binary}' not found on PATH"
        elif cooling:
            reason = f"cooling down for {cooling}s after a quota/auth error"
        return {
            "available": reason is None,
            "reason": reason,
            "binary": path,
            "cooldown_seconds": cooling,
            "agents": sorted(p.stem for p in AGENTS_SRC_DIR.glob("*.md")),
        }

    def sync_agents(self) -> list[str]:
        """Install the app's read-only agent definitions where agy looks for them."""
        if not settings.agy_install_agents:
            return []
        dst_dir = Path(os.path.expanduser("~")) / ".gemini" / "config" / "agents"
        changed: list[str] = []
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            for src in AGENTS_SRC_DIR.glob("*.md"):
                dst = dst_dir / src.name
                body = src.read_bytes()
                if not dst.exists() or dst.read_bytes() != body:
                    dst.write_bytes(body)
                    changed.append(src.stem)
        except OSError as exc:
            logger.warning(f"Could not sync agy agents: {exc}")
        self._agents_synced = True
        return changed

    # ── one CLI call ──
    def _call(self, args: list[str], stdin: str | None, cwd: Path, timeout: int) -> tuple[int, str, str]:
        proc = subprocess.run(
            args,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd),
            timeout=timeout + 30,
        )
        return proc.returncode, proc.stdout, proc.stderr

    async def _once(
        self, prompt: str, *, agent: str, model: str, cwd: Path, timeout: int, conversation: str | None
    ) -> tuple[str | None, dict[str, Any], str]:
        exe = self.resolve_binary()
        if not exe:
            raise AgyUnavailable(f"'{self.binary}' not found on PATH")
        args = [exe, "--agent", agent, "--model", model, "--output-format", "stream-json",
                "--print-timeout", f"{timeout}s"]
        if conversation:
            args += ["--conversation", conversation]
        stdin = None
        if len(prompt) <= MAX_ARG_PROMPT_CHARS:
            args += ["-p", prompt]
        else:
            args += ["--input-format", "stream-json"]
            stdin = json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
        try:
            _rc, out, err = await asyncio.to_thread(self._call, args, stdin, cwd, timeout)
        except subprocess.TimeoutExpired as exc:
            raise AgyError(f"agy timed out after {timeout}s") from exc
        model_used, result = _parse_stream(out)
        return model_used, result, err

    async def run(
        self,
        prompt: str,
        *,
        agent: str,
        model: str,
        cwd: Path,
        timeout: int | None = None,
        fallback_model: str | None = None,
        on_event: EventFn | None = None,
    ) -> AgyResult:
        st = self.status()
        if not st["available"]:
            raise AgyUnavailable(st["reason"])
        if not self._agents_synced:
            self.sync_agents()
        timeout = timeout or settings.agy_timeout_seconds
        cwd.mkdir(parents=True, exist_ok=True)

        async with self._sem:
            started = time.time()
            attempts = 0
            plan: list[tuple[str, str | None, str]] = [(model, None, prompt)]
            last_err = None
            usage_total: dict[str, int] = {}
            while plan:
                cur_model, conv, cur_prompt = plan.pop(0)
                attempts += 1
                model_used, result, stderr = await self._once(
                    cur_prompt, agent=agent, model=cur_model, cwd=cwd, timeout=timeout, conversation=conv
                )
                for k, v in (result.get("usage") or {}).items():
                    if isinstance(v, (int, float)):
                        usage_total[k] = usage_total.get(k, 0) + int(v)
                status = result.get("status")
                text = (result.get("response") or "").strip()
                err = result.get("error")
                if isinstance(err, dict):
                    err = err.get("message") or json.dumps(err)
                if not err and not result:
                    err = (stderr or "").strip().splitlines()[0][:300] if stderr.strip() else "no result event"
                if text:
                    res = AgyResult(text, model_used or cur_model, status, err, usage_total, attempts,
                                    time.time() - started, result.get("conversation_id"))
                    if on_event:
                        await on_event("info", f"agy {agent} ({res.model}) answered",
                                       {"usage": usage_total, "attempts": attempts,
                                        "seconds": round(res.duration_s, 1)})
                    return res
                last_err = err or f"empty reply ({status})"
                if err and _QUOTA_RE.search(str(err)):
                    self._cooldown_until = time.time() + settings.agy_cooldown_seconds
                    raise AgyUnavailable(f"agy unavailable: {err}")
                if on_event:
                    await on_event("warn", f"agy {agent} gave no answer ({last_err}); retrying", None)
                conv_id = result.get("conversation_id")
                if status == "SUCCESS" and conv_id and conv is None:
                    plan.insert(0, (cur_model, conv_id, NUDGE))
                elif fallback_model and cur_model != fallback_model and not any(
                    p[0] == fallback_model for p in plan
                ):
                    plan.append((fallback_model, None, prompt))
            raise AgyError(f"agy produced no answer after {attempts} attempt(s): {last_err}")

    async def run_json(
        self,
        prompt: str,
        schema: type[M],
        *,
        agent: str,
        model: str,
        cwd: Path,
        timeout: int | None = None,
        fallback_model: str | None = None,
        on_event: EventFn | None = None,
    ) -> tuple[M, AgyResult]:
        """Run and validate the reply as `schema`; one repair turn on invalid JSON."""
        res = await self.run(prompt, agent=agent, model=model, cwd=cwd, timeout=timeout,
                             fallback_model=fallback_model, on_event=on_event)
        try:
            return schema.model_validate(extract_json(res.text)), res
        except (ValueError, ValidationError) as first_err:
            if on_event:
                await on_event("warn", f"agy reply was not valid JSON for {schema.__name__}; asking for a repair", None)
            repair = (
                f"{prompt}\n\nYour previous reply could not be parsed ({str(first_err)[:300]}). "
                "Reply again with ONLY the JSON object in the required shape, no prose, no fences."
            )
            res2 = await self.run(repair, agent=agent, model=model, cwd=cwd, timeout=timeout,
                                  fallback_model=fallback_model, on_event=on_event)
            try:
                return schema.model_validate(extract_json(res2.text)), res2
            except (ValueError, ValidationError) as exc:
                raise AgyError(f"agy reply did not match {schema.__name__}: {str(exc)[:300]}") from exc


agy_client = AgyClient()
