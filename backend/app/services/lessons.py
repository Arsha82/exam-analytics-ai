"""
Lessons: a narrated slide deck per topic, and an optional local MP4.

Deck: one `pyq-writer` agy call (low-thinking model) with the topic's syllabus line, its
real past questions (session + marks) and matching notes excerpts. The app plays decks
itself (animated slides + the browser's speech voice); the MP4 export is fully local:
slides drawn with matplotlib (mathtext for formulas), narration with the Windows speech
engine, assembled by ffmpeg with soft subtitles.
"""

import asyncio
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.config import settings
from app.database import async_session_factory
from app.models.catalog import Course, CourseTopic
from app.models.acquisition import SourceDocument
from app.models.paper import Paper, Question, QuestionTopic
from app.models.study import Lesson
from app.services.acquisition.sessions import session_label
from app.services.agy import agy_client
from app.services.jobs import JobContext
from app.services.notes import notes_text_path

SLIDE_KINDS = ("title", "concept", "formula", "steps", "example", "exam", "summary")


class Slide(BaseModel):
    kind: str = "concept"
    heading: str
    bullets: list[str] = Field(default_factory=list)
    latex: str | None = None
    narration: str
    ref: str | None = None  # e.g. "December 2022 · Q14(a)"

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        return v if v in SLIDE_KINDS else "concept"


class QuizItem(BaseModel):
    q: str
    answer: str


class Deck(BaseModel):
    title: str
    slides: list[Slide]
    quiz: list[QuizItem] = Field(default_factory=list)

    @field_validator("slides")
    @classmethod
    def _count(cls, v):
        if not 4 <= len(v) <= 14:
            raise ValueError("a deck needs 4-14 slides")
        return v


DECK_PROMPT = """Write a short narrated lesson (slides + voice-over) for one exam topic.

Course: {code} — {title}
Module {module}: {module_title}
Syllabus line: {syllabus}
Topic: {topic}

Real questions asked on this topic in past university exams:
{questions}

Notes excerpts (may be empty or noisy):
{notes}

Make 6-10 slides that teach exactly what these exam questions need:
1. "title" slide: topic and why it matters in this exam (how often / for how many marks, from the questions above).
2. "concept"/"formula" slides: the definitions, results and formulas needed (formulas in LaTeX in "latex").
3. "steps" slide: the standard method as numbered steps — the steps that earn marks.
4. "example" slide(s): work one of the real questions above briefly (cite it in "ref").
5. "exam" slide: how this topic is asked (Part A 3-mark vs Part B 7/14-mark patterns) and common mistakes.
6. "summary" slide.
Bullets: at most 5 per slide, each under 14 words, LaTeX inline as $...$.
"narration": what a teacher would say for that slide, 2-4 plain sentences, no LaTeX
(say formulas in words), friendly and exam-focused.
Also 3 quick quiz questions with short answers.

Reply with only this JSON:
{{"title": "...", "slides": [{{"kind": "title|concept|formula|steps|example|exam|summary", "heading": "...", "bullets": ["..."], "latex": null, "narration": "...", "ref": null}}], "quiz": [{{"q": "...", "answer": "..."}}]}}"""


def lesson_dir(lesson_id: int) -> Path:
    d = settings.storage_dir / "lessons" / str(lesson_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _context(lesson: Lesson) -> dict:
    async with async_session_factory() as db:
        course = await db.get(Course, lesson.course_code)
        topic = await db.get(CourseTopic, lesson.topic_id)
        if course is None or topic is None:
            raise ValueError("course or topic not found")
        module = next((m for m in course.catalog_json["modules"] if m["no"] == topic.module_no), {})
        rows = (await db.execute(
            select(Question, Paper).join(QuestionTopic, QuestionTopic.question_id == Question.question_id)
            .join(Paper, Paper.paper_id == Question.paper_id)
            .where(QuestionTopic.topic_id == topic.topic_id))).all()
        notes = list((await db.execute(select(SourceDocument).where(
            SourceDocument.course_code == course.code, SourceDocument.kind == "notes",
            (SourceDocument.module_no == topic.module_no) | (SourceDocument.module_no.is_(None))))).scalars())
    rows.sort(key=lambda r: ((r[1].session_year or 0) * 100 + (r[1].session_month or 0)), reverse=True)
    questions = "\n".join(
        f"- [{session_label(p.session_month, p.session_year)}, Q{q.number}{q.sub or ''}, {q.marks:g} marks] {q.text[:400]}"
        for q, p in rows[:10]) or "- (none recorded yet)"
    keys = [w.lower() for w in re.findall(r"[A-Za-z']{5,}", topic.name)] + [k.lower() for k in topic.keywords or []]
    excerpts: list[str] = []
    for n in notes:
        path = notes_text_path(n.sha256)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        low = text.lower()
        for k in keys:
            i = low.find(k)
            if i != -1:
                excerpts.append(re.sub(r"\s+", " ", text[max(0, i - 150): i + 650]))
                break
        if len(excerpts) >= 2:
            break
    return {"course": course, "topic": topic, "module": module, "questions": questions,
            "notes": "\n---\n".join(excerpts) or "(none)", "n_questions": len(rows)}


async def lesson_job(ctx: JobContext, params: dict) -> dict:
    lesson_id = int(params["lesson_id"])
    async with async_session_factory() as db:
        lesson = await db.get(Lesson, lesson_id)
    c = await _context(lesson)
    await ctx.info("lesson", f"Writing a lesson on '{c['topic'].name}' from {c['n_questions']} past question(s)", progress=10)
    prompt = DECK_PROMPT.format(code=c["course"].code, title=c["course"].title, module=c["topic"].module_no,
                                module_title=c["module"].get("title", ""), syllabus=c["module"].get("syllabus", "")[:600],
                                topic=c["topic"].name, questions=c["questions"], notes=c["notes"][:2500])
    try:
        deck, res = await agy_client.run_json(prompt, Deck, agent="pyq-writer", model=settings.agy_reader_model,
                                              cwd=lesson_dir(lesson_id), fallback_model=settings.agy_fallback_model,
                                              on_event=ctx.event_fn("lesson"))
    except Exception as exc:
        async with async_session_factory() as db:
            row = await db.get(Lesson, lesson_id)
            row.status, row.error = "failed", str(exc)[:500]
            await db.commit()
        raise
    async with async_session_factory() as db:
        row = await db.get(Lesson, lesson_id)
        row.deck, row.status, row.error = deck.model_dump(), "ready", None
        await db.commit()
    return {"lesson_id": lesson_id, "slides": len(deck.slides), "tokens": res.usage}


# ───────────────────────────── video export (local) ─────────────────────────────

PAPER, INK, INK2, INK3, RED, BLUE = "#f3efe6", "#1d1b16", "#4b463c", "#857e70", "#b4361f", "#1f4a73"


def _mathsafe(text: str) -> str:
    """matplotlib mathtext supports a LaTeX subset; drop what it can't draw."""
    t = text.replace("\\left", "").replace("\\right", "").replace("\\,", " ").replace("\\;", " ")
    t = re.sub(r"\\(text|mathrm|operatorname)\{([^}]*)\}", r"\\mathrm{\2}", t)
    return t


def render_slide_png(slide: dict, index: int, total: int, course_label: str, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def draw(math_ok: bool):
        fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
        fig.patch.set_facecolor(PAPER)
        fig.add_artist(plt.Line2D([0.06, 0.06], [0.70, 0.84], color=RED, linewidth=4))
        fig.text(0.075, 0.90, f"{course_label}  ·  {slide.get('kind', '').upper()}", color=INK3, fontsize=12,
                 family="monospace")
        fig.text(0.075, 0.78, slide["heading"], color=INK, fontsize=30, family="serif", va="center", wrap=True)
        y = 0.64
        if slide.get("latex"):
            expr = slide["latex"].strip().strip("$")
            fig.text(0.5, y, f"${_mathsafe(expr)}$" if math_ok else expr, color=BLUE, fontsize=26, ha="center", va="center")
            y -= 0.12
        for b in slide.get("bullets", [])[:5]:
            txt = _mathsafe(b) if math_ok else b.replace("$", "")
            fig.text(0.09, y, "•", color=RED, fontsize=20, va="top")
            fig.text(0.115, y, txt, color=INK2, fontsize=19, va="top", wrap=True)
            y -= 0.095
        if slide.get("ref"):
            fig.text(0.075, 0.07, f"Past paper: {slide['ref']}", color=INK3, fontsize=12, style="italic")
        fig.text(0.94, 0.07, f"{index + 1}/{total}", color=INK3, fontsize=12, ha="right", family="monospace")
        fig.savefig(out, facecolor=PAPER)
        plt.close(fig)

    try:
        draw(True)
    except Exception:  # noqa: BLE001 — unsupported LaTeX: draw it as plain text instead
        plt.close("all")
        draw(False)


_PS_TTS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
if ($voices -contains $env:PYQ_VOICE) { $s.SelectVoice($env:PYQ_VOICE) }
$s.Rate = [int]$env:PYQ_RATE
$s.SetOutputToWaveFile($env:PYQ_OUT)
$s.Speak([IO.File]::ReadAllText($env:PYQ_TEXT))
$s.Dispose()
"""


def tts_to_wav(text: str, out: Path, voice: str = "Microsoft Zira Desktop", rate: int = 0) -> float:
    """Local narration (Windows speech engine; espeak-ng on Linux, `say` on macOS). Returns seconds."""
    import shutil
    import sys

    txt = out.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    if sys.platform != "win32":
        if sys.platform == "darwin" and shutil.which("say"):
            cmd = ["say", "-f", str(txt), "-o", str(out), "--file-format=WAVE", "--data-format=LEI16@22050"]
        elif shutil.which("espeak-ng"):
            cmd = ["espeak-ng", "-f", str(txt), "-w", str(out), "-s", str(170 + 10 * rate)]
        else:
            raise RuntimeError("no speech engine found: install espeak-ng (Linux) to export lesson videos")
        subprocess.run(cmd, capture_output=True, timeout=180, check=True)
        with wave.open(str(out), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    script = out.with_suffix(".ps1")
    script.write_text(_PS_TTS, encoding="utf-8")
    env = {**__import__("os").environ, "PYQ_VOICE": voice, "PYQ_RATE": str(rate), "PYQ_OUT": str(out), "PYQ_TEXT": str(txt)}
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                   env=env, capture_output=True, timeout=180, check=True)
    with wave.open(str(out), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _srt_time(t: float) -> str:
    h, rem = divmod(int(t * 1000), 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def render_video(deck: dict, course_label: str, workdir: Path, voice: str, rate: int, ffmpeg: str) -> Path:
    workdir = workdir.resolve()
    slides = deck["slides"]
    segments, srt, t = [], [], 0.0
    for i, s in enumerate(slides):
        png, wav, seg = workdir / f"s{i:02d}.png", workdir / f"s{i:02d}.wav", workdir / f"s{i:02d}.mp4"
        render_slide_png(s, i, len(slides), course_label, png)
        dur = tts_to_wav(s["narration"], wav, voice, rate) + 0.8
        fade_out = max(0.0, dur - 0.35)
        subprocess.run([ffmpeg, "-y", "-loop", "1", "-t", f"{dur:.2f}", "-i", str(png), "-i", str(wav),
                        "-vf", f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out:.2f}:d=0.35,format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-r", "25",
                        "-c:a", "aac", "-ar", "44100", "-shortest", str(seg)],
                       capture_output=True, timeout=300, check=True)
        segments.append(seg)
        srt.append(f"{i + 1}\n{_srt_time(t)} --> {_srt_time(t + dur - 0.3)}\n{s['narration']}\n")
        t += dur
    concat = workdir / "concat.txt"
    concat.write_text("".join(f"file '{p.name}'\n" for p in segments), encoding="utf-8")
    subs = workdir / "lesson.srt"
    subs.write_text("\n".join(srt), encoding="utf-8")
    out = workdir / "lesson.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(subs),
                    "-map", "0:v", "-map", "0:a", "-map", "1:0", "-c:v", "copy", "-c:a", "copy",
                    "-c:s", "mov_text", "-metadata:s:s:0", "language=eng", str(out)],
                   capture_output=True, timeout=300, check=True, cwd=str(workdir))
    return out


async def video_job(ctx: JobContext, params: dict) -> dict:
    lesson_id = int(params["lesson_id"])
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH")
    async with async_session_factory() as db:
        lesson = await db.get(Lesson, lesson_id)
        lesson.video_status = "rendering"
        await db.commit()
        deck = lesson.deck
        course_label = f"{lesson.course_code}"
    if not deck:
        raise RuntimeError("lesson has no deck yet")
    await ctx.info("video", f"Rendering {len(deck['slides'])} slides with local narration", progress=10)
    workdir = lesson_dir(lesson_id) / "video"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        out = await asyncio.to_thread(render_video, deck, course_label, workdir, params.get("voice", "Microsoft Zira Desktop"),
                                      int(params.get("rate", 0)), ffmpeg)
    except Exception as exc:
        async with async_session_factory() as db:
            row = await db.get(Lesson, lesson_id)
            row.video_status, row.error = "failed", str(exc)[:500]
            await db.commit()
        raise
    async with async_session_factory() as db:
        row = await db.get(Lesson, lesson_id)
        row.video_path, row.video_status = str(out), "ready"
        await db.commit()
    return {"lesson_id": lesson_id, "video": str(out), "bytes": out.stat().st_size}
