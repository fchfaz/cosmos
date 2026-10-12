"""Notifikasi HP (semua perangkat Android) -> satu inbox terpusat.

Data masuk lewat POST /ingest/notification dari agen di tiap HP
(MacroDroid/Tasker/Termux/app relay). Skill ini membersihkan, mendeduplikasi,
menandai yang sensitif, lalu menerbitkan event ke bus.
"""
from __future__ import annotations

import time

from core import safety
from core.util import fmt_ts, sha, trunc
from skills.base import Action, Skill

APP_LABELS = {
    "com.whatsapp": "WhatsApp", "com.whatsapp.w4b": "WhatsApp Business",
    "com.instagram.android": "Instagram", "org.telegram.messenger": "Telegram",
    "com.google.android.gm": "Gmail", "com.facebook.orca": "Messenger",
    "com.twitter.android": "X", "com.tokopedia.tkpd": "Tokopedia", "com.shopee.id": "Shopee",
    "com.google.android.apps.messaging": "Pesan", "com.line.android": "LINE",
}


def label(app: str) -> str:
    return APP_LABELS.get(app, app.rsplit(".", 1)[-1].capitalize() if "." in app else app)


class NotifSkill(Skill):
    name = "notif"
    description = "Inbox notifikasi gabungan dari semua HP"
    INGESTS = ["notification"]
    ACTIONS = [
        Action("recent", "Notifikasi terbaru dari semua perangkat", {
            "limit": {"type": "integer", "description": "jumlah, default 10"},
            "device": {"type": "string", "description": "filter nama perangkat"},
            "app": {"type": "string", "description": "filter nama aplikasi, mis. whatsapp"},
            "hours": {"type": "integer", "description": "batas jam ke belakang, default 24"},
        }),
        Action("search", "Cari notifikasi berdasarkan kata", {
            "query": {"type": "string"}, "hours": {"type": "integer", "description": "default 48"},
        }, ["query"]),
        Action("devices_status", "Status & aktivitas tiap perangkat"),
    ]

    # ---- ingest ---------------------------------------------------------
    async def ingest(self, kind: str, device: str, payload: dict) -> dict:
        app = str(payload.get("package") or payload.get("app") or "").strip()
        title = str(payload.get("title") or "").strip()[:300]
        text = str(payload.get("text") or payload.get("body") or "").strip()[:2000]
        if not (title or text):
            return {"status": "ignored", "reason": "kosong"}
        ignore = [a.lower() for a in self.ctx.settings.get("notifications.ignore_apps", [])]
        if app.lower() in ignore:
            return {"status": "ignored", "reason": "aplikasi diabaikan"}
        window = float(self.ctx.settings.get("notifications.dedup_seconds", 300))
        if self.ctx.db.seen_recently(sha("notif", app, title, text), window):
            return {"status": "ignored", "reason": "duplikat"}
        sensitive = safety.is_sensitive_app(app) or safety.looks_like_otp(f"{title} {text}")
        event = await self.ctx.bus.publish(
            source=app or "unknown", type_="notification", device=device,
            payload={"app": app, "title": title, "text": text, "sensitive": sensitive,
                     "device_ts": payload.get("ts")},
        )
        return {"status": "accepted", "event_id": event.get("id"), "sensitive": sensitive}

    # ---- util -----------------------------------------------------------
    def _events(self, hours: float, limit: int, device: str | None = None) -> list[dict]:
        return self.ctx.db.recent_events(limit=limit, type_="notification",
                                         since=time.time() - hours * 3600, device=device)

    def _line(self, e: dict) -> str:
        tz = self.ctx.settings.get("app.timezone")
        p = e["payload"]
        body = trunc(p.get("text"), 100)
        title = f"{p.get('title')}: " if p.get("title") else ""
        return f"• [{e['device']}] {label(p.get('app', ''))} — {title}{body} ({fmt_ts(e['ts'], tz, '%H:%M')})"

    # ---- aksi -----------------------------------------------------------
    async def do_recent(self, limit: int = 10, device: str | None = None, app: str | None = None,
                        hours: int = 24) -> dict:
        rows = self._events(hours, 500, device)
        if app:
            rows = [e for e in rows if app.lower() in (e["payload"].get("app", "") + label(e["payload"].get("app", ""))).lower()]
        rows = rows[: int(limit)]
        if not rows:
            return {"items": [], "text": "Tidak ada notifikasi baru."}
        items = [{"device": e["device"], "app": label(e["payload"].get("app", "")), "title": e["payload"].get("title"),
                  "text": e["payload"].get("text"), "ts": e["ts"], "sensitive": e["payload"].get("sensitive")} for e in rows]
        return {"items": items, "text": f"{len(rows)} notifikasi terbaru:\n" + "\n".join(self._line(e) for e in rows)}

    async def do_search(self, query: str, hours: int = 48) -> dict:
        q = query.lower()
        rows = [e for e in self._events(hours, 1000)
                if q in " ".join(str(e["payload"].get(k, "")) for k in ("app", "title", "text")).lower()][:15]
        if not rows:
            return {"items": [], "text": f"Tidak ada notifikasi yang cocok dengan '{query}'."}
        return {"items": [e["payload"] | {"device": e["device"], "ts": e["ts"]} for e in rows],
                "text": f"{len(rows)} hasil untuk '{query}':\n" + "\n".join(self._line(e) for e in rows)}

    async def do_devices_status(self) -> dict:
        tz = self.ctx.settings.get("app.timezone")
        counts: dict[str, int] = {}
        for e in self._events(24, 5000):
            counts[e["device"]] = counts.get(e["device"], 0) + 1
        devs = self.ctx.db.list_devices()
        if not devs:
            return {"devices": [], "text": "Belum ada perangkat terdaftar (python -m scripts.add_device)."}
        lines = []
        for d in devs:
            seen = fmt_ts(d["last_seen"], tz) if d["last_seen"] else "belum pernah"
            lines.append(f"• {d['name']} ({d['platform']}) — terakhir aktif: {seen}; 24 jam: {counts.get(d['name'], 0)} notif")
        return {"devices": devs, "text": "Perangkat:\n" + "\n".join(lines)}
