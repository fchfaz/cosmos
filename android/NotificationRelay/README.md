# Jarvis Notification Relay (opsional, Metode B)

Kerangka app Android kecil berbasis `NotificationListenerService`. **Belum dikompilasi/diuji.**
Untuk memulai tanpa coding, pakai MacroDroid/Tasker (lihat `docs/PROSES.md`) atau `android/termux/relay.sh`.

## Yang perlu Anda lengkapi
1. Buat proyek baru di Android Studio (Empty Activity, package `id.jarvis.relay`, minSdk 24 agar Android 7 / Redmi Note 4X tetap didukung).
2. Salin `RelayService.kt` ke package tersebut.
3. Tambahkan di `AndroidManifest.xml` (di dalam `<application>`):

```xml
<service
    android:name=".RelayService"
    android:exported="true"
    android:label="Jarvis Relay"
    android:permission="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE">
    <intent-filter>
        <action android:name="android.service.notification.NotificationListenerService" />
    </intent-filter>
</service>
```
4. Tambahkan `<uses-permission android:name="android.permission.INTERNET" />`.
5. Karena memakai HTTP (bukan HTTPS) lewat Tailscale, tambahkan `android:usesCleartextTraffic="true"` pada `<application>`
   (lalu lebih baik batasi ke domain `*.ts.net` lewat network security config).
6. Pasang, lalu beri akses notifikasi dan matikan penghemat baterai untuk app ini.
