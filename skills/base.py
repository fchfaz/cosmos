"""Kontrak plugin. Menambah kemampuan baru = membuat satu file di skills/ yang
mewarisi Skill. Registry menemukannya otomatis; tidak ada kode inti yang diubah.

Konvensi:
  * Setiap aksi dideklarasikan di ACTIONS dan diimplementasikan sebagai
    `async def do_<nama_aksi>(self, **params)`.
  * Hasil aksi = dict. Sertakan kunci "text" (rendering manusia, bahasa
    Indonesia) agar tetap terbaca di mode offline / Telegram.
  * Aksi yang mengubah dunia luar (kirim email/DM, hapus, bayar) WAJIB
    needs_approval=True -> otomatis masuk antrean persetujuan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Action:
    name: str
    description: str
    params: dict[str, dict] = field(default_factory=dict)  # JSON-schema per parameter
    required: list[str] = field(default_factory=list)
    needs_approval: bool = False
    summarize: Callable[[dict], str] | None = None  # ringkasan untuk kartu persetujuan

    def schema(self) -> dict:
        return {"type": "object", "properties": self.params, "required": self.required}


class Skill:
    name: str = ""
    description: str = ""
    ACTIONS: list[Action] = []
    INGESTS: list[str] = []  # jenis data dari perangkat yang ditangani, mis. ["notification"]

    def __init__(self, ctx: Any):
        self.ctx = ctx

    # ---- metadata -------------------------------------------------------
    def actions(self) -> list[Action]:
        return list(self.ACTIONS)

    def action(self, name: str) -> Action | None:
        return next((a for a in self.actions() if a.name == name), None)

    # ---- siklus hidup (opsional) ---------------------------------------
    async def start(self) -> None:
        """Dipanggil saat server hidup (mis. jadwalkan polling)."""

    async def stop(self) -> None:
        """Dipanggil saat server berhenti."""

    async def on_event(self, event: dict) -> None:
        """Dipanggil untuk setiap event di bus."""

    async def ingest(self, kind: str, device: str, payload: dict) -> dict:
        """Dipanggil untuk data dari perangkat (POST /ingest/<kind>) bila kind ada di INGESTS."""
        raise NotImplementedError

    # ---- eksekusi -------------------------------------------------------
    async def run(self, action: str, params: dict) -> dict:
        spec = self.action(action)
        if spec is None:
            return {"error": f"aksi tidak dikenal: {self.name}.{action}"}
        fn = getattr(self, f"do_{action}", None)
        if fn is None:
            return {"error": f"aksi belum diimplementasikan: {self.name}.{action}"}
        allowed = {k: v for k, v in (params or {}).items() if k in spec.params}
        return await fn(**allowed)
