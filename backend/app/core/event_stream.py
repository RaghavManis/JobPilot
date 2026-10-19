import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, AsyncGenerator
from backend.app.core.logging import logger


class EventStreamService:
    """Manages real-time Server-Sent Event (SSE) streams for application sessions."""

    def __init__(self):
        # Map: session_id -> list of active client asyncio.Queue instances
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        # Map: session_id -> recent event history
        self._history: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, session_id: str, event_type: str, data: Dict[str, Any]):
        """Publish an event to all active subscribers for the session."""
        event_payload = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            **data
        }

        async with self._lock:
            if session_id not in self._history:
                self._history[session_id] = []
            self._history[session_id].append(event_payload)
            if len(self._history[session_id]) > 100:
                self._history[session_id].pop(0)

            queues = self._subscribers.get(session_id, [])
            for q in list(queues):
                try:
                    q.put_nowait(event_payload)
                except Exception as e:
                    logger.warning(f"Failed to push event to subscriber queue: {e}")

    async def log_action(
        self,
        session_id: str,
        message: str,
        level: str = "info",
        action: str = None,
        field_id: str = None,
        field_label: str = None,
        value: str = None
    ):
        """Helper to publish action and log event simultaneously."""
        data = {
            "message": message,
            "level": level,
        }
        if action:
            data["action"] = action
        if field_id:
            data["field_id"] = field_id
        if field_label:
            data["field_label"] = field_label
        if value is not None:
            data["value"] = value

        await self.publish(session_id, "log", data)

    async def update_status(self, session_id: str, status: str, detail: str = ""):
        """Publish status change event."""
        await self.publish(session_id, "status", {"status": status, "detail": detail})

    async def subscribe(self, session_id: str) -> AsyncGenerator[str, None]:
        """Subscribe to live events for a session, yielding SSE formatted strings."""
        queue = asyncio.Queue()

        async with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = []
            self._subscribers[session_id].append(queue)
            history = list(self._history.get(session_id, []))

        try:
            # Send initial replay events
            for event in history:
                yield f"data: {json.dumps(event)}\n\n"

            # Stream new events
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            async with self._lock:
                if session_id in self._subscribers and queue in self._subscribers[session_id]:
                    self._subscribers[session_id].remove(queue)
                    if not self._subscribers[session_id]:
                        del self._subscribers[session_id]


# Global event stream instance
event_stream = EventStreamService()
