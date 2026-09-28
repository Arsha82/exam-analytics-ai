"""
Base agent contract.

Every agent in the pipeline follows this contract:
1. Read from the database (relational or vector store)
2. Execute deterministic or model-based logic
3. Write results back to the database
4. Emit progress events via Redis pub/sub

No file handoffs between agents. Idempotent writes keyed by stable IDs.
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base for all pipeline agents.

    Subclasses implement `run()` which performs the agent's core logic.
    The base class provides progress broadcasting and standardized logging.
    """

    name: str = "BaseAgent"

    def __init__(
        self,
        db: AsyncSession,
        vector_store: Any = None,
        config: Any = None,
        redis_client: Any = None,
    ):
        self.db = db
        self.vectors = vector_store
        self.config = config
        self.redis = redis_client
        self.logger = logging.getLogger(f"agent.{self.name}")

    @abstractmethod
    async def run(self, **kwargs) -> dict:
        """
        Execute the agent's core logic.

        Returns:
            A summary dict with at minimum:
            {
                "status": "complete" | "partial" | "failed",
                "items_processed": int,
                "items_flagged": int,
                "details": str
            }
        """
        ...

    async def emit_progress(self, stage: str, pct: int, detail: str = ""):
        """Broadcast a pipeline progress event via Redis pub/sub."""
        event = {
            "agent": self.name,
            "stage": stage,
            "progress": min(max(pct, 0), 100),
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.logger.info(f"[{stage}] {pct}% — {detail}")

        from app.services.event_bus import event_bus

        # Always publish to in-memory event bus for WebSockets
        try:
            await event_bus.publish(event)
        except Exception as e:
            self.logger.warning(f"Failed to publish to in-memory event bus: {e}")

        if self.redis:
            try:
                await self.redis.publish(
                    "pipeline:events", json.dumps(event)
                )
            except Exception as e:
                self.logger.warning(f"Failed to publish progress event to Redis: {e}")

    async def emit_complete(self, summary: dict):
        """Emit a completion event with the run summary."""
        await self.emit_progress(
            stage="complete",
            pct=100,
            detail=json.dumps(summary),
        )
