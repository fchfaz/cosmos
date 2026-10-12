from __future__ import annotations

import hashlib
import time
from datetime import datetime
from zoneinfo import ZoneInfo


def now() -> float:
    return time.time()


def fmt_ts(ts: float, tz: str = "Asia/Makassar", fmt: str = "%d %b %H:%M") -> str:
    return datetime.fromtimestamp(ts, ZoneInfo(tz)).strftime(fmt)


def trunc(text: str | None, n: int = 120) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def chunk(text: str, size: int = 3800) -> list[str]:
    """Pecah teks panjang (batas pesan Telegram 4096)."""
    if len(text) <= size:
        return [text]
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > size and buf:
            out.append(buf)
            buf = ""
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        buf += line
    if buf:
        out.append(buf)
    return out
