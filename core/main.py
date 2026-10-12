"""Server FastAPI: pintu masuk perangkat (ingest), antarmuka web/PWA, dan siklus hidup sistem.

Jalankan:  uvicorn core.main:create_app --factory --host 0.0.0.0 --port 8765
(Akses hanya lewat jaringan Tailscale; jangan buka port ke internet publik.)
"""
from __future__ import annotations

import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.config import ROOT, Settings
from core.context import Context
from core.util import sha

log = logging.getLogger("jarvis.api")
WEB = ROOT / "interfaces" / "web"
MAX_BODY = 64 * 1024
RATE_PER_MIN = 120


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    session: str = "web"


class DeviceIn(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{2,32}$")
    platform: str = "android"


class ApproveIn(BaseModel):
    edits: dict | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    ctx = Context(settings)
    hits: dict[str, deque] = defaultdict(deque)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx.scheduler = AsyncIOScheduler(timezone=settings.get("app.timezone", "Asia/Makassar"))
        ctx.scheduler.start()
        await ctx.start()
        telegram = None
        token, owner = Settings.env("TELEGRAM_BOT_TOKEN"), Settings.env("TELEGRAM_OWNER_ID")
        if settings.get("telegram.enabled", True) and token and owner:
            from interfaces.telegram_bot import TelegramInterface
            telegram = TelegramInterface(ctx, token, int(owner))
            await telegram.start()
        else:
            log.info("Telegram nonaktif (isi TELEGRAM_BOT_TOKEN dan TELEGRAM_OWNER_ID di .env)")
        log.info("Jarvis siap. Model: %s | Skill: %s", ctx.llm.describe(), ", ".join(ctx.registry.skills))
        yield
        if telegram:
            await telegram.stop()
        await ctx.stop()
        ctx.scheduler.shutdown(wait=False)

    app = FastAPI(title="Jarvis", lifespan=lifespan)
    app.state.ctx = ctx

    # ---- autentikasi -------------------------------------------------------
    def owner_auth(x_api_key: str = Header(default="")) -> None:
        key = Settings.env("JARVIS_API_KEY")
        if not key:
            raise HTTPException(503, "JARVIS_API_KEY belum diatur di .env")
        if not hmac.compare_digest(x_api_key.encode(), key.encode()):
            ctx.db.audit("unknown", "auth.owner_failed")
            raise HTTPException(401, "API key salah")

    def device_auth(x_device_token: str = Header(default="")) -> dict:
        dev = ctx.db.device_by_hash(sha(x_device_token)) if x_device_token else None
        if not dev:
            ctx.db.audit("unknown", "auth.device_failed")
            raise HTTPException(401, "token perangkat tidak valid")
        now, q = time.time(), hits[dev["name"]]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_PER_MIN:
            raise HTTPException(429, "terlalu banyak permintaan")
        q.append(now)
        ctx.db.touch_device(dev["name"])
        return dev

    # ---- publik ----------------------------------------------------------------
    @app.get("/health")
    async def health():
        return {"status": "ok", "model": ctx.llm.describe(), "skills": sorted(ctx.registry.skills)}

    # ---- dari perangkat ----------------------------------------------------
    @app.post("/ingest/{kind}")
    async def ingest(kind: str, request: Request, dev: dict = Depends(device_auth)):
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "payload terlalu besar")
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "JSON tidak valid")
        if not isinstance(payload, dict):
            raise HTTPException(400, "payload harus objek JSON")
        skill = ctx.registry.ingest_target(kind)
        if skill is None:
            raise HTTPException(404, f"tidak ada skill yang menangani '{kind}'")
        return await skill.ingest(kind, dev["name"], payload)  # nama perangkat dari token, bukan dari body

    # ---- dari pemilik (web/PWA) ----------------------------------------------
    @app.post("/chat", dependencies=[Depends(owner_auth)])
    async def chat(body: ChatIn):
        return await ctx.brain.handle(body.text, session=f"web:{body.session}")

    @app.get("/approvals", dependencies=[Depends(owner_auth)])
    async def approvals():
        return ctx.approvals.pending()

    @app.post("/approvals/{aid}/approve", dependencies=[Depends(owner_auth)])
    async def approve(aid: str, body: ApproveIn | None = None):
        return await ctx.approvals.approve(aid, (body.edits if body else None))

    @app.post("/approvals/{aid}/reject", dependencies=[Depends(owner_auth)])
    async def reject(aid: str):
        return await ctx.approvals.reject(aid)

    @app.get("/outbox", dependencies=[Depends(owner_auth)])
    async def outbox(after: int = 0):
        return ctx.db.outbox_after(after)

    @app.get("/events", dependencies=[Depends(owner_auth)])
    async def events(limit: int = 30, type: str | None = None):
        return ctx.db.recent_events(limit=min(limit, 200), type_=type)

    @app.get("/devices", dependencies=[Depends(owner_auth)])
    async def devices():
        return ctx.db.list_devices()

    @app.post("/devices", dependencies=[Depends(owner_auth)])
    async def add_device(body: DeviceIn):
        token = secrets.token_urlsafe(32)
        ctx.db.add_device(body.name, body.platform, sha(token))
        ctx.db.audit("owner", "device.added", {"name": body.name})
        return {"name": body.name, "token": token, "note": "Simpan token ini sekarang; tidak akan ditampilkan lagi."}

    @app.delete("/devices/{name}", dependencies=[Depends(owner_auth)])
    async def del_device(name: str):
        ok = ctx.db.remove_device(name)
        ctx.db.audit("owner", "device.removed", {"name": name, "ok": ok})
        return {"removed": ok}

    # ---- berkas statis PWA ----------------------------------------------------
    def _file(name: str, media: str | None = None):
        p = Path(WEB / name)
        if not p.exists():
            raise HTTPException(404, "berkas tidak ditemukan")
        return FileResponse(p, media_type=media)

    @app.get("/")
    async def index():
        return _file("index.html")

    @app.get("/manifest.webmanifest")
    async def manifest():
        return _file("manifest.webmanifest", "application/manifest+json")

    @app.get("/sw.js")
    async def sw():
        return _file("sw.js", "application/javascript")

    return app
