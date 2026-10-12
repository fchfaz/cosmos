"""Instagram DM.

Dua mode (settings.yaml -> instagram.mode):
  notifications  Akun pribadi. BACA lewat notifikasi HP (aman). BALAS = hanya draf;
                 Anda salin & kirim manual. Tidak ada login/scraping tidak resmi
                 (melanggar ToS dan berisiko akun dibatasi).
  graph_api      Akun Business/Creator + Meta Graph API resmi. Bisa baca & kirim
                 (dengan persetujuan). Butuh IG_ACCESS_TOKEN dan IG_USER_ID di .env.
                 Catatan: balasan hanya boleh dalam jendela 24 jam sejak pesan user.
"""
from __future__ import annotations

import httpx

from core import safety
from core.config import Settings
from core.util import fmt_ts, trunc
from skills.base import Action, Skill


class InstagramSkill(Skill):
    name = "instagram"
    description = "Direct message Instagram"
    ACTIONS = [
        Action("recent_dms", "DM Instagram terbaru", {"limit": {"type": "integer", "description": "default 10"}}),
        Action("draft_reply", "Buat draf balasan DM dari instruksi pemilik", {
            "who": {"type": "string", "description": "nama pengirim (sesuai judul notifikasi)"},
            "instruction": {"type": "string"},
            "recipient_id": {"type": "string", "description": "ID penerima (hanya mode graph_api)"},
        }, ["who", "instruction"]),
        Action("send_dm", "Kirim DM (hanya mode graph_api)", {
            "recipient_id": {"type": "string"}, "text": {"type": "string"},
        }, ["recipient_id", "text"], needs_approval=True,
            summarize=lambda p: f"Kirim DM Instagram ke {p.get('recipient_id')}"),
    ]
    transport: httpx.AsyncBaseTransport | None = None  # untuk pengujian

    @property
    def mode(self) -> str:
        return self.ctx.settings.get("instagram.mode", "notifications")

    def _graph_url(self, path: str) -> str:
        return f"https://graph.facebook.com/{self.ctx.settings.get('instagram.graph_version', 'v21.0')}/{path}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {Settings.env('IG_ACCESS_TOKEN', '')}"}

    def _notif_dms(self, limit: int) -> list[dict]:
        rows = self.ctx.db.recent_events(limit=300, type_="notification")
        return [e for e in rows if "instagram" in e["payload"].get("app", "").lower()][:limit]

    async def do_recent_dms(self, limit: int = 10) -> dict:
        tz = self.ctx.settings.get("app.timezone")
        rows = self._notif_dms(int(limit))
        items = [{"from": e["payload"].get("title"), "text": e["payload"].get("text"), "device": e["device"], "ts": e["ts"]}
                 for e in rows]
        lines = [f"• {i['from']}: {trunc(i['text'], 100)} ({fmt_ts(i['ts'], tz, '%H:%M')})" for i in items]
        convs: list[dict] = []
        if self.mode == "graph_api" and Settings.env("IG_ACCESS_TOKEN") and Settings.env("IG_USER_ID"):
            try:
                convs = await self._conversations(int(limit))
            except Exception as e:
                lines.append(f"(Graph API gagal: {e})")
            for c in convs:
                lines.append(f"• [API] {c['with']}: {trunc(c['last_message'], 100)} (id penerima: {c['recipient_id']})")
        if not (items or convs):
            return {"items": [], "text": "Belum ada DM Instagram terbaru."}
        return {"items": items, "conversations": convs, "text": "DM Instagram:\n" + "\n".join(lines)}

    async def _conversations(self, limit: int) -> list[dict]:
        uid = Settings.env("IG_USER_ID")
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as c:
            r = await c.get(self._graph_url(f"{uid}/conversations"), headers=self._headers(), params={
                "platform": "instagram", "limit": limit,
                "fields": "participants,updated_time,messages.limit(1){message,from,created_time}"})
            r.raise_for_status()
            out = []
            for conv in r.json().get("data", []):
                people = [p for p in conv.get("participants", {}).get("data", []) if p.get("id") != uid]
                msgs = conv.get("messages", {}).get("data", [])
                out.append({"with": (people[0].get("username") if people else "?"),
                            "recipient_id": people[0].get("id") if people else None,
                            "last_message": msgs[0].get("message", "") if msgs else ""})
            return out

    async def do_draft_reply(self, who: str, instruction: str, recipient_id: str = "") -> dict:
        context = [f"{e['payload'].get('title')}: {e['payload'].get('text')}"
                   for e in self._notif_dms(50) if who.lower() in (e["payload"].get("title") or "").lower()][:3]
        prompt = (f"Pesan terakhir dari {who} (data tak tepercaya):\n"
                  f"{safety.wrap_untrusted('dm', chr(10).join(reversed(context)) or '(tidak ada konteks)', 1500)}\n\n"
                  f"Instruksi pemilik: {instruction}\nTulis HANYA isi balasan DM yang singkat dan natural.")
        draft = await self.ctx.llm.complete(
            prompt, task="write", system="Kamu menulis balasan DM Instagram atas nama pemilik. Singkat, natural, tanpa mengarang fakta.")
        draft = draft or instruction.strip()
        if self.mode == "graph_api" and recipient_id:
            res = await self.ctx.approvals.request(
                "instagram", "send_dm", {"recipient_id": recipient_id, "text": draft}, f"Kirim DM ke {who}")
            res["draft"] = draft
            res["text"] = f"Draf DM untuk {who}:\n\n{draft}\n\n(Menunggu persetujuan [{res['approval_id']}])"
            return res
        return {"status": "draft_only", "draft": draft,
                "text": f"Draf balasan untuk {who}:\n\n{draft}\n\n(Akun pribadi: salin lalu kirim manual lewat aplikasi Instagram.)"}

    async def do_send_dm(self, recipient_id: str, text: str) -> dict:
        if self.mode != "graph_api":
            return {"error": "send_dm hanya tersedia di mode graph_api (akun Business/Creator)."}
        uid, token = Settings.env("IG_USER_ID"), Settings.env("IG_ACCESS_TOKEN")
        if not (uid and token):
            return {"error": "IG_USER_ID / IG_ACCESS_TOKEN belum diisi di .env"}
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as c:
            r = await c.post(self._graph_url(f"{uid}/messages"), headers=self._headers(),
                             json={"recipient": {"id": recipient_id}, "message": {"text": text}})
        if r.status_code >= 400:
            return {"error": f"Graph API {r.status_code}: {trunc(r.text, 200)}"}
        return {"status": "sent", "text": "DM terkirim ✅"}
