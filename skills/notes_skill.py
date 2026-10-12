"""Skill paling sederhana — jadikan ini contoh/templat saat membuat fitur baru."""
from __future__ import annotations

import time

from core.util import fmt_ts
from skills.base import Action, Skill


class NotesSkill(Skill):
    name = "notes"
    description = "Catatan cepat milik pemilik"
    ACTIONS = [
        Action("add_note", "Simpan catatan baru", {"text": {"type": "string", "description": "isi catatan"}}, ["text"]),
        Action("list_notes", "Tampilkan catatan terbaru", {"limit": {"type": "integer", "description": "default 10"}}),
    ]

    async def do_add_note(self, text: str) -> dict:
        notes = self.ctx.db.kv_get("notes", [])
        notes.append({"ts": time.time(), "text": text.strip()[:2000]})
        self.ctx.db.kv_set("notes", notes[-500:])
        return {"status": "saved", "count": len(notes), "text": f"Tercatat ✅ (total {len(notes)} catatan)"}

    async def do_list_notes(self, limit: int = 10) -> dict:
        tz = self.ctx.settings.get("app.timezone")
        notes = self.ctx.db.kv_get("notes", [])[-int(limit):][::-1]
        if not notes:
            return {"items": [], "text": "Belum ada catatan."}
        lines = [f"• {fmt_ts(n['ts'], tz)} — {n['text']}" for n in notes]
        return {"items": notes, "text": "Catatan terbaru:\n" + "\n".join(lines)}
