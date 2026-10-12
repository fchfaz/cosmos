"""Router LLM: cloud (Claude) / lokal (Ollama) / offline (aturan kata kunci).

  * complete()  -> teks biasa. Tugas ringan (classify/summarize) diprioritaskan
                   ke model lokal pada mode hybrid; tugas menulis ke cloud.
  * chat()      -> percakapan dengan tool-calling (cloud). Tanpa cloud, jatuh
                   ke OfflineRouter sehingga sistem tetap berfungsi tanpa API key.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx

from core.config import Settings

log = logging.getLogger("jarvis.llm")


class LLM:
    def __init__(self, settings: Settings):
        self.s = settings
        self.mode: str = settings.get("llm.mode", "hybrid")
        self._client = None
        self._local_down_until = 0.0

    # ---- status ---------------------------------------------------------
    @property
    def api_key(self) -> str | None:
        return Settings.env("ANTHROPIC_API_KEY")

    @property
    def is_cloud(self) -> bool:
        return self.mode in ("cloud", "hybrid") and bool(self.api_key)

    @property
    def local_enabled(self) -> bool:
        return self.mode in ("local", "hybrid") and bool(self.s.get("llm.ollama_url")) and time.time() > self._local_down_until

    @property
    def has_any(self) -> bool:
        return self.is_cloud or self.local_enabled

    def describe(self) -> str:
        parts = []
        if self.is_cloud:
            parts.append(f"cloud:{self.s.get('llm.cloud_model')}")
        if self.local_enabled:
            parts.append(f"lokal:{self.s.get('llm.local_model')}")
        return "+".join(parts) or "offline (aturan kata kunci)"

    # ---- teks biasa -----------------------------------------------------
    def _order(self, task: str) -> list[str]:
        if self.mode == "offline":
            return []
        local_ok, cloud_ok = self.local_enabled, self.is_cloud
        if self.mode == "local":
            return ["local"] if local_ok else []
        if self.mode == "cloud":
            return ["cloud"] if cloud_ok else []
        light = task in ("classify", "summarize")
        pref = (("local", local_ok), ("cloud", cloud_ok)) if light else (("cloud", cloud_ok), ("local", local_ok))
        return [name for name, ok in pref if ok]

    async def complete(self, prompt: str, *, system: str = "", task: str = "write",
                       max_tokens: int | None = None) -> str:
        """Kembalikan teks; string kosong bila tidak ada model yang tersedia."""
        for provider in self._order(task):
            try:
                if provider == "local":
                    return await self._ollama(prompt, system)
                return await self._cloud_text(prompt, system, max_tokens)
            except Exception as e:
                log.warning("provider %s gagal: %s", provider, e)
                if provider == "local":
                    self._local_down_until = time.time() + 60  # jangan coba lagi selama 1 menit
        return ""

    async def _ollama(self, prompt: str, system: str) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{self.s.get('llm.ollama_url')}/api/chat",
                             json={"model": self.s.get("llm.local_model"), "messages": msgs, "stream": False})
            r.raise_for_status()
            return (r.json().get("message", {}).get("content") or "").strip()

    def _anthropic(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def _cloud_text(self, prompt: str, system: str, max_tokens: int | None) -> str:
        resp = await self._anthropic().messages.create(
            model=self.s.get("llm.cloud_model"),
            max_tokens=max_tokens or self.s.get("llm.max_tokens", 1024),
            system=system or "Jawab ringkas dan akurat.",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()

    # ---- percakapan + tool calling -------------------------------------
    async def chat(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        """Kembalikan {"text", "tool_calls":[{id,name,input}], "content":[blok], "provider"}."""
        if self.is_cloud:
            try:
                return await self._cloud_chat(system, messages, tools)
            except Exception as e:
                log.warning("chat cloud gagal, pakai router offline: %s", e)
        return OfflineRouter([t["name"] for t in tools]).respond(messages)

    async def _cloud_chat(self, system: str, messages: list[dict], tools: list[dict]) -> dict:
        resp = await self._anthropic().messages.create(
            model=self.s.get("llm.cloud_model"),
            max_tokens=self.s.get("llm.max_tokens", 1024),
            system=system, messages=messages, tools=tools,
        )
        content, calls, texts = [], [], []
        for b in resp.content:
            if b.type == "text":
                content.append({"type": "text", "text": b.text})
                texts.append(b.text)
            elif b.type == "tool_use":
                content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                calls.append({"id": b.id, "name": b.name, "input": dict(b.input)})
        return {"text": "".join(texts).strip(), "tool_calls": calls, "content": content, "provider": "cloud"}


# ---------------------------------------------------------------------------
class OfflineRouter:
    """Pemetaan perintah -> tool berbasis kata kunci. Tanpa LLM, tanpa internet."""

    HELP = (
        "Mode offline (belum ada API key LLM). Perintah yang saya pahami:\n"
        "• \"cek email\" / \"email belum dibaca\"\n"
        "• \"notifikasi terbaru\"\n"
        "• \"dm instagram\"\n"
        "• \"ringkasan hari ini\"\n"
        "• \"status\"\n"
        "• \"catat <teks>\" dan \"catatan\"\n"
        "Untuk membalas/menulis email, aktifkan LLM (isi ANTHROPIC_API_KEY)."
    )

    def __init__(self, tool_names: list[str]):
        self.tools = set(tool_names)

    def respond(self, messages: list[dict]) -> dict:
        last = messages[-1]
        if isinstance(last.get("content"), list) and last["content"] and last["content"][0].get("type") == "tool_result":
            return self._text("\n\n".join(self._render(b) for b in last["content"]))
        text = last["content"] if isinstance(last["content"], str) else ""
        call = self._route(text)
        if call is None:
            return self._text(self.HELP)
        name, params = call
        if name not in self.tools:
            return self._text(f"Fitur '{name}' belum aktif.\n\n{self.HELP}")
        block = {"type": "tool_use", "id": "off_" + uuid.uuid4().hex[:10], "name": name, "input": params}
        return {"text": "", "tool_calls": [{"id": block["id"], "name": name, "input": params}],
                "content": [block], "provider": "offline"}

    @staticmethod
    def _text(t: str) -> dict:
        return {"text": t, "tool_calls": [], "content": [{"type": "text", "text": t}], "provider": "offline"}

    @staticmethod
    def _render(block: dict) -> str:
        try:
            data = json.loads(block.get("content") or "{}")
        except (TypeError, ValueError):
            return str(block.get("content"))
        return data.get("text") or data.get("error") or json.dumps(data, ensure_ascii=False)[:1500]

    @staticmethod
    def _route(text: str) -> tuple[str, dict] | None:
        raw, t = text.strip(), text.lower().strip()
        has = lambda *w: any(x in t for x in w)  # noqa: E731
        if t.startswith("catat "):
            return "notes__add_note", {"text": raw[6:].strip()}
        if has("catatan"):
            return "notes__list_notes", {}
        if has("balas", "reply", "kirim email", "tulis email"):
            return None
        if has("instagram", " ig ", "dm "):
            return "instagram__recent_dms", {}
        if has("notifikasi", "notif"):
            return "notif__recent", {}
        if has("email", "surel", "gmail", "inbox"):
            return "email__list_unread", {}
        if has("ringkas", "rangkum", "digest", "rangkuman", "hari ini"):
            return "system__digest", {}
        if has("status", "skill", "perangkat"):
            return "system__status", {}
        return None
