"""Event bus: format event seragam untuk semua sumber (email, notifikasi, DM, ...)."""
from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Awaitable, Callable

from core.db import Database

log = logging.getLogger("jarvis.bus")
Handler = Callable[[dict], Awaitable[None] | None]


class EventBus:
    def __init__(self, db: Database):
        self.db = db
        self.handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> None:
        self.handlers.append(handler)

    async def publish(self, source: str, type_: str, device: str | None = None,
                      payload: dict[str, Any] | None = None, store: bool = True) -> dict:
        payload = payload or {}
        event = {"source": source, "type": type_, "device": device, "payload": payload, "ts": time.time()}
        if store:
            event["id"] = self.db.insert_event(source, type_, device, payload, event["ts"])
        for handler in list(self.handlers):
            try:
                res = handler(event)
                if inspect.isawaitable(res):
                    await res
            except Exception:  # satu handler rusak tidak boleh menjatuhkan yang lain
                log.exception("handler event gagal untuk %s", type_)
        return event
