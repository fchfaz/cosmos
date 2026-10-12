"""Konfigurasi: default -> config/settings.yaml -> overrides (kode/test).

Rahasia (API key, token) TIDAK pernah disimpan di YAML; hanya dibaca dari
environment / file .env melalui Settings.env().
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "app": {"name": "Jarvis", "owner": "Pemilik", "timezone": "Asia/Makassar"},
    "storage": {"db_path": "data/jarvis.db"},
    "llm": {
        # offline | cloud | local | hybrid
        "mode": "hybrid",
        "cloud_model": "claude-sonnet-5-5",
        "local_model": "qwen2.5:7b",
        "ollama_url": "http://127.0.0.1:11434",
        "max_tokens": 1024,
        "max_tool_steps": 6,
    },
    "privacy": {"redact_for_cloud": True},
    "notify": {"min_priority": "high", "digest_hour": 7},
    "approvals": {"ttl_hours": 24},
    "triage": {"use_llm": True, "vip_senders": []},
    "notifications": {
        "dedup_seconds": 300,
        "ignore_apps": [
            "com.android.systemui",
            "com.miui.securitycenter",
            "com.coloros.safecenter",
            "com.iqoo.secure",
            "android",
        ],
    },
    "email": {
        "enabled": True,
        "poll_seconds": 120,
        "query": "is:unread in:inbox",
        "token_path": "data/gmail_token.json",
        "max_body_chars": 6000,
    },
    "instagram": {
        # notifications (aman, akun pribadi) | graph_api (akun Business/Creator)
        "mode": "notifications",
        "graph_version": "v21.0",
    },
    "telegram": {"enabled": True},
    "skills": {"disabled": [], "extra_dirs": []},
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    @classmethod
    def load(cls, path: str | Path | None = None, overrides: dict | None = None) -> "Settings":
        load_dotenv(ROOT / ".env")
        data = copy.deepcopy(DEFAULTS)
        yaml_path = Path(path) if path else ROOT / "config" / "settings.yaml"
        if yaml_path.exists():
            data = _merge(data, yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {})
        if overrides:
            data = _merge(data, overrides)
        return cls(data)

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    @staticmethod
    def env(name: str, default: str | None = None) -> str | None:
        val = os.environ.get(name)
        return val if val not in (None, "") else default

    def path(self, dotted: str) -> Path:
        """Ambil nilai setting sebagai path; relatif -> relatif ke ROOT proyek."""
        raw = Path(str(self.get(dotted)))
        return raw if raw.is_absolute() else ROOT / raw
