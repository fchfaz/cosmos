#!/data/data/com.termux/files/usr/bin/bash
# Relay notifikasi Android -> Jarvis, tanpa membuat app (cocok untuk HP lama, mis. Redmi Note 4X).
#
# Persiapan di HP (sekali):
#   1. Pasang Termux dan Termux:API dari F-Droid (satu sumber yang sama untuk keduanya).
#   2. Beri "Akses notifikasi" ke Termux:API (Pengaturan > Notifikasi > Akses notifikasi).
#   3. Di Termux:  pkg install termux-api curl jq
#   4. Pasang Tailscale di HP & login (agar laptop terjangkau).
#   5. Matikan penghemat baterai untuk Termux & Termux:API; aktifkan Autostart (MIUI/ColorOS/FuntouchOS).
#   6. Jalankan:  termux-wake-lock; JARVIS_URL=http://laptop:8765 JARVIS_TOKEN=xxxx bash relay.sh
#
# CATATAN: skrip ini belum diuji di perangkat fisik Anda; uji dengan 1 HP dulu.
set -u
URL="${JARVIS_URL:?isi JARVIS_URL, mis. http://laptop.tailnet.ts.net:8765}"
TOKEN="${JARVIS_TOKEN:?isi JARVIS_TOKEN dari: python -m scripts.add_device <nama>}"
INTERVAL="${INTERVAL:-5}"
SEEN="${HOME}/.jarvis_seen"
touch "$SEEN"

while true; do
  termux-notification-list 2>/dev/null \
  | jq -c '.[] | select(.packageName != "com.termux.api" and .packageName != "com.termux") | {key:.key, app:.packageName, title:(.title // ""), text:(.content // ""), ts:.when}' \
  | while read -r n; do
      key=$(printf '%s' "$n" | jq -r '.key')
      grep -qxF "$key" "$SEEN" && continue
      if curl -fsS -m 10 -X POST "$URL/ingest/notification" \
           -H "Content-Type: application/json" -H "X-Device-Token: $TOKEN" \
           -d "$(printf '%s' "$n" | jq -c 'del(.key)')" >/dev/null; then
        echo "$key" >> "$SEEN"
      fi
    done
  tail -n 500 "$SEEN" > "$SEEN.tmp" && mv "$SEEN.tmp" "$SEEN"
  sleep "$INTERVAL"
done
