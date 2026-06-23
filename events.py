"""Shared SSE broadcaster for the unified /events stream.

Any router can call broadcast(payload) to push to all connected clients.
Register an on_connect callback to send initial state when a client connects.
"""

import asyncio
import json
import threading
from typing import Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

_clients: set = set()
_lock = threading.Lock()
_loop: Optional[asyncio.AbstractEventLoop] = None
_on_connect_hooks: list[Callable[[], dict]] = []


def set_loop(loop: asyncio.AbstractEventLoop):
    global _loop
    _loop = loop


def register_init_hook(fn: Callable[[], dict]):
    """Register a callback that returns a dict to include in the connect snapshot."""
    _on_connect_hooks.append(fn)


def broadcast(payload: dict):
    """Push payload to all connected SSE clients (thread-safe)."""
    with _lock:
        clients = list(_clients)
    if _loop and clients:
        for q in clients:
            _loop.call_soon_threadsafe(q.put_nowait, payload)


@router.get("/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    with _lock:
        _clients.add(q)

    async def generate():
        init = {}
        for hook in _on_connect_hooks:
            init.update(hook())
        yield f"data: {json.dumps(init)}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            with _lock:
                _clients.discard(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
