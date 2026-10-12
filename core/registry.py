"""Registry plugin: menemukan skill otomatis, membuat spesifikasi tool untuk LLM,
dan mengeksekusi aksi dengan penjagaan persetujuan."""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Any

import skills as skills_pkg
from skills.base import Skill

log = logging.getLogger("jarvis.registry")


class Registry:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.skills: dict[str, Skill] = {}
        self.errors: dict[str, str] = {}

    # ---- penemuan -------------------------------------------------------
    def discover(self, extra_dirs: list[str | Path] | None = None) -> None:
        disabled = set(self.ctx.settings.get("skills.disabled", []) or [])
        for mod in pkgutil.iter_modules(skills_pkg.__path__):
            if mod.name.startswith("_") or mod.name == "base":
                continue
            try:
                module = importlib.import_module(f"skills.{mod.name}")
                self._register_module(module, disabled)
            except Exception as e:  # skill rusak tidak boleh mematikan sistem
                self.errors[mod.name] = repr(e)
                log.exception("gagal memuat skill %s", mod.name)
        dirs = list(extra_dirs or []) + list(self.ctx.settings.get("skills.extra_dirs", []) or [])
        for d in dirs:
            for f in sorted(Path(d).glob("*.py")):
                if f.name.startswith("_"):
                    continue
                try:
                    spec = importlib.util.spec_from_file_location(f"jarvis_ext_{f.stem}", f)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    self._register_module(module, disabled)
                except Exception as e:
                    self.errors[f.stem] = repr(e)
                    log.exception("gagal memuat skill eksternal %s", f)

    def _register_module(self, module: Any, disabled: set[str]) -> None:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Skill) and obj is not Skill and obj.__module__ == module.__name__ and obj.name:
                if obj.name in disabled:
                    continue
                self.register(obj(self.ctx))

    def register(self, skill: Skill) -> None:
        self.skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def ingest_target(self, kind: str) -> Skill | None:
        return next((s for s in self.skills.values() if kind in s.INGESTS), None)

    # ---- spesifikasi tool untuk LLM ------------------------------------
    def tool_specs(self) -> list[dict]:
        specs = []
        for s in self.skills.values():
            for a in s.actions():
                note = " [butuh persetujuan pemilik]" if a.needs_approval else ""
                specs.append({
                    "name": f"{s.name}__{a.name}",
                    "description": f"{s.description} — {a.description}{note}"[:1000],
                    "input_schema": a.schema(),
                })
        return specs

    # ---- eksekusi -------------------------------------------------------
    async def call(self, skill_name: str, action_name: str, params: dict | None = None,
                   *, approved: bool = False, actor: str = "brain") -> dict:
        params = params or {}
        skill = self.get(skill_name)
        if skill is None:
            return {"error": f"skill tidak ditemukan: {skill_name}"}
        action = skill.action(action_name)
        if action is None:
            return {"error": f"aksi tidak ditemukan: {skill_name}.{action_name}"}
        missing = [r for r in action.required if r not in params]
        if missing:
            return {"error": f"parameter wajib hilang: {', '.join(missing)}"}
        if action.needs_approval and not approved:
            summary = action.summarize(params) if action.summarize else f"{skill_name}.{action_name} {params}"
            return await self.ctx.approvals.request(skill_name, action_name, params, summary)
        try:
            result = await skill.run(action_name, params)
        except Exception as e:
            log.exception("aksi gagal %s.%s", skill_name, action_name)
            result = {"error": f"{type(e).__name__}: {e}"}
        self.ctx.db.audit(actor, f"{skill_name}.{action_name}", {"params": _brief(params), "ok": "error" not in result})
        return result


def _brief(params: dict) -> dict:
    return {k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v) for k, v in params.items()}
