"""Pipeline router — status, WebSocket progress, review queue."""

import asyncio
import json
import logging
from typing import Any
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.paper import Paper, Question
from app.models.attempt import AttemptScore
from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/status")
async def pipeline_status():
    """Get current pipeline run status."""
    return {"status": "ready", "service": "pyq-pipeline"}


@router.websocket("/ws")
async def pipeline_ws(websocket: WebSocket):
    """
    WebSocket endpoint for real-time pipeline progress events.
    Streams events as agents execute OCR, Structuring, Correlation, etc.
    """
    await websocket.accept()
    queue = event_bus.subscribe()
    
    # Task to listen for incoming messages from client (e.g. ping/heartbeat)
    async def receive_loop():
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass

    receiver_task = asyncio.create_task(receive_loop())

    try:
        # Send initial connected event
        await websocket.send_json({
            "type": "connection",
            "status": "connected",
            "message": "Connected to PYQ Analyzer pipeline event stream"
        })

        while True:
            # Wait for event from event bus
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.warning(f"WebSocket send error: {e}")
    finally:
        event_bus.unsubscribe(queue)
        receiver_task.cancel()


@router.get("/review-queue")
async def get_review_queue(db: AsyncSession = Depends(get_db)):
    """Get all needs_review items across papers, questions, and attempt evaluations."""
    items = []

    # 1. Papers needing review
    paper_query = select(Paper).where(Paper.needs_review == True)
    paper_res = await db.execute(paper_query)
    for p in paper_res.scalars().all():
        items.append({
            "id": p.paper_id,
            "type": "paper",
            "title": f"Paper {p.subject} ({p.year})",
            "reason": f"OCR or structuring flagged paper (Status: {p.ocr_status})",
            "subject": p.subject,
            "year": p.year,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "meta": {"total_marks": p.total_marks, "source_file": p.source_file},
        })

    # 2. Questions needing review
    q_query = select(Question).where(Question.needs_review == True)
    q_res = await db.execute(q_query)
    for q in q_res.scalars().all():
        items.append({
            "id": q.question_id,
            "type": "question",
            "title": f"Question {q.question_no} ({q.year})",
            "reason": q.review_reason or "Low confidence or mark mismatch flagged",
            "unit": q.unit_guess,
            "confidence": q.unit_confidence,
            "marks": q.marks,
            "text": q.text,
            "created_at": q.created_at.isoformat() if q.created_at else None,
        })

    # 3. Attempt scores with low confidence
    score_query = select(AttemptScore).where(AttemptScore.low_confidence == True)
    score_res = await db.execute(score_query)
    for s in score_res.scalars().all():
        items.append({
            "id": str(s.id),
            "type": "attempt_score",
            "title": f"Grading for Q {s.question_id}",
            "reason": f"Evaluation agent low confidence ({s.marks_awarded}/{s.max_marks} marks)",
            "marks_awarded": s.marks_awarded,
            "max_marks": s.max_marks,
            "reasoning": s.reasoning,
        })

    return {"items": items, "total": len(items)}


@router.patch("/review-queue/{item_type}/{item_id}")
async def resolve_review_item(
    item_type: str,
    item_id: str,
    payload: dict[str, Any] | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Resolve a review item (approve or override)."""
    if item_type == "question":
        res = await db.execute(select(Question).where(Question.question_id == item_id))
        q = res.scalar_one_or_none()
        if q:
            q.needs_review = False
            if payload:
                if "unit_guess" in payload:
                    q.unit_guess = payload["unit_guess"]
                if "marks" in payload:
                    q.marks = float(payload["marks"])
                if "text" in payload:
                    q.text = payload["text"]
            await db.commit()
            return {"status": "resolved", "item_id": item_id}
            
    elif item_type == "paper":
        res = await db.execute(select(Paper).where(Paper.paper_id == item_id))
        p = res.scalar_one_or_none()
        if p:
            p.needs_review = False
            await db.commit()
            return {"status": "resolved", "item_id": item_id}

    elif item_type == "attempt_score":
        res = await db.execute(select(AttemptScore).where(AttemptScore.id == int(item_id)))
        s = res.scalar_one_or_none()
        if s:
            s.low_confidence = False
            if payload and "marks_awarded" in payload:
                s.marks_awarded = float(payload["marks_awarded"])
            await db.commit()
            return {"status": "resolved", "item_id": item_id}

    return {"status": "not_found", "item_id": item_id}
