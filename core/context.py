"""Context: satu objek yang menyatukan semua komponen inti dan dibagikan ke skill/antarmuka."""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from core.approval import ApprovalManager
from core.brain import Brain
from core.bus import EventBus
from core.config import Settings
from core.db import Database
from core.llm import LLM
from core.registry import Registry

log = logging.getLogger("jarvis.ctx")
Notifier = Callable[[str, str | None], Awaitable[None]]


class Context:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.path("storage.db_path"))
        self.bus = EventBus(self.db)
        self.llm = LLM(settings)
        self.registry = Registry(self)
        self.approvals = ApprovalManager(self)
        self.brain = Brain(self)
        self.scheduler: Any = None
        self.notifiers: list[Notifier] = []
        self.started_at = time.time()
        self.registry.discover()

    async def notify(self, text: str, approval_id: str | None = None) -> None:
        """Kirim pesan proaktif ke pemilik: selalu masuk outbox (PWA) + semua notifier (Telegram)."""
        self.db.add_outbox(text, approval_id)
        for n in list(self.notifiers):
            try:
                await n(text, approval_id)
            except Exception:
                log.exception("notifier gagal")

    async def start(self) -> None:
        self.bus.subscribe(self.brain.on_event)
        for skill in self.registry.skills.values():
            self.bus.subscribe(skill.on_event)
            await skill.start()
        hour = int(self.settings.get("notify.digest_hour", 7))
        if self.scheduler is not None and hour >= 0:
            self.scheduler.add_job(self.send_digest, "cron", hour=hour, minute=0, id="daily_digest", replace_existing=True)

    async def stop(self) -> None:
        for skill in self.registry.skills.values():
            try:
                await skill.stop()
            except Exception:
                log.exception("stop skill gagal")

    async def send_digest(self) -> None:
        res = await self.registry.call("system", "digest", {}, actor="scheduler")
        await self.notify("🗞️ Ringkasan pagi\n" + (res.get("text") or res.get("error", "")))
