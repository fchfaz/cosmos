"""Antrean persetujuan: aksi yang mengubah dunia luar tidak pernah langsung jalan.

Alur: skill meminta aksi -> disimpan 'pending' -> pemilik diberi tahu (Telegram/PWA)
-> approve / edit / reject -> baru dieksekusi.
"""
from __future__ import annotations

import time
from typing import Any

from core.util import trunc


class ApprovalManager:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    @property
    def db(self):
        return self.ctx.db

    @staticmethod
    def preview(params: dict) -> str:
        for key in ("body", "text", "message"):
            if isinstance(params.get(key), str):
                return params[key]
        return ""

    async def request(self, skill: str, action: str, params: dict, summary: str) -> dict:
        aid = self.db.create_approval(skill, action, params, summary)
        self.db.audit("system", "approval.requested", {"id": aid, "skill": skill, "action": action})
        body = self.preview(params)
        msg = f"✋ Persetujuan [{aid}]\n{summary}"
        if body:
            msg += f"\n\n— Draf —\n{body}"
        await self.ctx.notify(msg, approval_id=aid)
        return {
            "status": "pending_approval",
            "approval_id": aid,
            "summary": summary,
            "text": f"Menunggu persetujuan Anda [{aid}]: {trunc(summary, 160)}",
        }

    async def approve(self, aid: str, edits: dict | None = None) -> dict:
        row = self.db.get_approval(aid)
        if not row:
            return {"error": "persetujuan tidak ditemukan"}
        if row["status"] != "pending":
            return {"error": f"sudah diproses (status: {row['status']})"}
        ttl = float(self.ctx.settings.get("approvals.ttl_hours", 24)) * 3600
        if time.time() - row["ts"] > ttl:
            self.db.update_approval(aid, status="expired", decided=time.time())
            return {"error": "persetujuan kedaluwarsa; minta ulang"}
        params = {**row["params"], **(edits or {})}
        self.db.update_approval(aid, status="approved", params=params, decided=time.time())
        result = await self.ctx.registry.call(row["skill"], row["action"], params, approved=True, actor="owner")
        status = "failed" if "error" in result else "executed"
        self.db.update_approval(aid, status=status, result=result)
        self.db.audit("owner", "approval.approved", {"id": aid, "status": status})
        return {"status": status, "result": result, "text": result.get("text") or result.get("error", "selesai")}

    async def reject(self, aid: str) -> dict:
        row = self.db.get_approval(aid)
        if not row or row["status"] != "pending":
            return {"error": "tidak ada persetujuan pending dengan ID itu"}
        self.db.update_approval(aid, status="rejected", decided=time.time())
        self.db.audit("owner", "approval.rejected", {"id": aid})
        return {"status": "rejected", "text": f"Dibatalkan [{aid}]."}

    async def edit(self, aid: str, new_text: str) -> dict:
        """Ganti isi draf (parameter body/text/message) lalu tampilkan ulang untuk disetujui."""
        row = self.db.get_approval(aid)
        if not row or row["status"] != "pending":
            return {"error": "tidak ada persetujuan pending dengan ID itu"}
        params = dict(row["params"])
        key = next((k for k in ("body", "text", "message") if k in params), None)
        if key is None:
            return {"error": "persetujuan ini tidak punya teks yang bisa diedit"}
        params[key] = new_text
        self.db.update_approval(aid, params=params)
        await self.ctx.notify(f"✏️ Draf diperbarui [{aid}]\n{row['summary']}\n\n— Draf —\n{new_text}", approval_id=aid)
        return {"status": "pending", "text": f"Draf [{aid}] diperbarui."}

    def pending(self) -> list[dict]:
        return self.db.pending_approvals()
