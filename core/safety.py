"""Lapisan keamanan: redaksi data sensitif, pembungkus data tak tepercaya,
dan deteksi heuristik prompt-injection.

Prinsip: isi email / notifikasi / DM adalah DATA, bukan perintah.
"""
from __future__ import annotations

import re
from typing import Any

_OTP_CTX = re.compile(
    r"(?i)(otp|kode|code|verifikasi|verification|pin|token|passcode)([^\d\n]{0,40})(\d{4,8})\b"
)
_ONLY_OTP_HINT = re.compile(r"(?i)(jangan\s+(bagikan|beritahu)|do\s+not\s+share|rahasia|berlaku\s+\d+\s+menit|valid\s+for)")
_DIGIT_RUN = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_NIK = re.compile(r"\b\d{16}\b")
_PASSWORD = re.compile(r"(?i)\b(password|passwd|kata\s*sandi|sandi)(\s*[:=]\s*)(\S+)")

SENSITIVE_APP_HINTS = (
    "bca", "bri", "bni", "mandiri", "jenius", "seabank", "permata", "cimb", "ocbc", "bank",
    "dana", "ovo", "gopay", "shopeepay", "linkaja", "wallet", "paypal", "authenticator",
    "otp", "lastpass", "bitwarden", "1password",
)

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|prompts?)",
    r"abaikan\s+(semua\s+)?(instruksi|perintah)\s+(sebelumnya|di\s+atas)",
    r"disregard\s+.{0,30}(instructions|rules)",
    r"(system|developer)\s+prompt",
    r"you\s+are\s+now\s+",
    r"kamu\s+sekarang\s+adalah",
    r"(forward|kirim(kan)?|teruskan)\s+.{0,60}\s+(ke|to)\s+\S+@\S+",
    r"(reveal|tampilkan|bocorkan)\s+.{0,30}(password|kata\s*sandi|api\s*key|token)",
    r"</?\s*untrusted",
]
_INJECTION = [re.compile(p, re.I | re.S) for p in INJECTION_PATTERNS]


def luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total, alt = 0, False
    for n in reversed(nums):
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def looks_like_otp(text: str) -> bool:
    text = text or ""
    return bool(_OTP_CTX.search(text)) or bool(_ONLY_OTP_HINT.search(text) and re.search(r"\b\d{4,8}\b", text))


def is_sensitive_app(app: str | None) -> bool:
    a = (app or "").lower()
    return any(h in a for h in SENSITIVE_APP_HINTS)


def redact(text: str) -> str:
    """Hapus OTP, nomor kartu, NIK, dan password sebelum teks dikirim ke LLM cloud."""
    if not text:
        return text

    def card_or_nik(m: re.Match) -> str:
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if luhn_ok(digits):
            return "[NOMOR-KARTU]"
        if len(digits) == 16:
            return "[NIK]"
        return raw

    text = _DIGIT_RUN.sub(card_or_nik, text)
    text = _NIK.sub("[NIK]", text)
    text = _OTP_CTX.sub(lambda m: f"{m.group(1)}{m.group(2)}[KODE]", text)
    text = _PASSWORD.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    if _ONLY_OTP_HINT.search(text):
        text = re.sub(r"\b\d{4,8}\b", "[KODE]", text)
    return text


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [redact_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    return obj


def injection_flags(text: str) -> list[str]:
    return [p.pattern for p in _INJECTION if p.search(text or "")]


def wrap_untrusted(label: str, text: str, max_chars: int = 4000) -> str:
    """Bungkus konten luar. Tanda < > dinetralkan agar tag penutup tidak bisa dipalsukan."""
    body = (text or "")[:max_chars].replace("<", "‹").replace(">", "›")
    return f'<untrusted_data source="{label}">\n{body}\n</untrusted_data>'
