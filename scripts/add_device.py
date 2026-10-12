"""Daftarkan perangkat baru dan cetak token-nya (hanya tampil sekali).

Contoh:  python -m scripts.add_device vivo-s1 --platform android
"""
from __future__ import annotations

import argparse
import re
import secrets

from core.config import Settings
from core.db import Database
from core.util import sha


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="nama unik, mis. oppo-a77s")
    ap.add_argument("--platform", default="android", choices=["android", "ios", "desktop"])
    ap.add_argument("--host", default="laptop.tailnet-anda.ts.net", help="nama/IP Tailscale laptop")
    ap.add_argument("--port", default=8765, type=int)
    a = ap.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{2,32}", a.name):
        raise SystemExit("Nama hanya boleh huruf/angka/_/- (2-32 karakter).")
    settings = Settings.load()
    db = Database(settings.path("storage.db_path"))
    token = secrets.token_urlsafe(32)
    db.add_device(a.name, a.platform, sha(token))
    db.audit("owner", "device.added", {"name": a.name})
    print(f"Perangkat : {a.name} ({a.platform})")
    print(f"Token     : {token}\n  (simpan sekarang — tidak bisa ditampilkan lagi)\n")
    print("Konfigurasi HTTP Request di MacroDroid/Tasker pada perangkat tersebut:")
    print(f"  URL     : http://{a.host}:{a.port}/ingest/notification")
    print("  Method  : POST   | Content-Type: application/json")
    print(f"  Header  : X-Device-Token: {token}")
    print('  Body    : {"app":"{package_name}","title":"{notification_title}","text":"{notification}"}')


if __name__ == "__main__":
    main()
