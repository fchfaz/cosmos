# Jarvis — personal assistant pribadi

Satu "otak" di laptop + agen kecil di tiap perangkat. Fase 1 ini bisa:

| Kemampuan | Status |
|---|---|
| Baca email masuk (Gmail), ringkas & prioritaskan | Kode + tes dengan Gmail palsu ✅ — belum dicoba dengan akun Gmail asli |
| Tulis & balas email (draf → persetujuan Anda → kirim di thread yang sama) | Kode + tes ✅ — belum dicoba dengan Gmail asli |
| Baca notifikasi dari beberapa HP Android → satu inbox, dedup, filter | Server + tes ✅ — agen di HP (MacroDroid/Termux/Kotlin) belum diuji di HP Anda |
| DM Instagram: baca via notifikasi (akun pribadi) atau Graph API (Business/Creator); balas selalu lewat persetujuan | Kode + tes (API dengan transport palsu) ✅ — belum dicoba dengan akun Meta asli |
| Antarmuka: bot Telegram (HP & iPad) dan PWA (iPad) | PWA & API diuji; bot Telegram belum dijalankan dengan token asli |
| Tanpa API key | Mode offline berbasis kata kunci tetap jalan ✅ |

Menambah fitur baru = menaruh **satu file** di `skills/` (lihat `docs/PROSES.md`, Bagian 6).

## Mulai cepat (di ThinkPad)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # lalu isi minimal JARVIS_API_KEY
python -m pytest -q                                    # harus lolos semua
uvicorn core.main:create_app --factory --host 0.0.0.0 --port 8765
```
Buka `http://localhost:8765` → masukkan `JARVIS_API_KEY` → ketik `status`, `catat tes`, `cek email`.

### Hubungkan perangkat
1. Pasang **Tailscale** di laptop, 4 HP, dan iPad (satu akun). Gunakan nama/IP Tailscale laptop sebagai host.
2. Per HP: `python -m scripts.add_device vivo-s1 --host <nama-tailscale-laptop>` → ikuti petunjuk yang dicetak (token tampil sekali).
3. Di HP: MacroDroid/Tasker (tanpa coding), `android/termux/relay.sh` (HP lama), atau `android/NotificationRelay` (app Kotlin).
4. iPad: buka `http://<host-tailscale>:8765` di Safari → Bagikan → *Add to Home Screen*.

### Hubungkan Gmail
Google Cloud Console → aktifkan Gmail API → OAuth client *Desktop app* → simpan sebagai `data/gmail_credentials.json` →
`python -m scripts.gmail_auth`. Scope hanya `gmail.readonly` + `gmail.send`.

### Hubungkan Telegram
@BotFather → buat bot → isi `TELEGRAM_BOT_TOKEN`; ID akun Anda (via @userinfobot) → `TELEGRAM_OWNER_ID`. Restart server.

### LLM
- Tanpa apa-apa: mode offline (perintah kata kunci).
- `ANTHROPIC_API_KEY` di `.env`: bahasa bebas + menulis draf + tool-calling.
- Ollama (opsional): `ollama pull qwen2.5:7b` untuk klasifikasi lokal tanpa kirim data keluar. Atur `llm.mode` di `config/settings.yaml`.

## Struktur
```
core/        otak: config, db, bus, registry, approval, llm, brain, safety, main (API)
skills/      plugin: email, notif, instagram, system, notes  (+ base.py = kontrak)
interfaces/  telegram_bot.py, web/ (PWA)
scripts/     add_device.py, gmail_auth.py
android/     relay.sh (Termux) dan kerangka app Kotlin
tests/       42 tes
docs/PROSES.md   penjelasan lengkap dari awal sampai jadi Jarvis
```

## Keamanan (ringkas)
Token per perangkat (hash disimpan, bisa dicabut) · aksi tulis wajib persetujuan · isi email/DM dibungkus sebagai data tak tepercaya + deteksi injection ·
OTP/kartu/NIK/password disamarkan sebelum ke LLM cloud · notifikasi bank/OTP tidak dikirim ke LLM · semua aksi tercatat di tabel audit ·
hanya lewat Tailscale (jangan buka port ke internet).
