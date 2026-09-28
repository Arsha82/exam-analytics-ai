"""
PYQ Analyzer — Pipeline Event Bus.

Provides async pub/sub for real-time progress events.
Supports both in-memory WebSocket subscribers and optional Redis fallback.
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)


class EventBus:
    """In-memory event hub for pipeline progress broadcasting."""

    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        """Register a new subscriber queue."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Unregister a subscriber queue."""
        self._subscribers.discard(q)

    async def publish(self, event: dict[str, Any]):
        """Broadcast an event to all active subscribers."""
        dead_queues = set()
        for q in self._subscribers:
            try:
                # Discard oldest if queue is full to avoid memory leaks
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(event)
            except Exception as e:
                logger.debug(f"Error pushing to subscriber queue: {e}")
                dead_queues.add(q)

        for dead in dead_queues:
            self._subscribers.discard(dead)

    async def listen(self) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator yielding events for a subscriber."""
        q = self.subscribe()
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            self.unsubscribe(q)


event_bus = EventBus()
