package id.jarvis.relay

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * Meneruskan setiap notifikasi ke Jarvis. Izin "Akses notifikasi" diberikan pengguna
 * secara manual: Pengaturan > Notifikasi > Akses notifikasi > Jarvis Relay.
 *
 * BELUM DIUJI di perangkat fisik — ini kerangka awal. Isi BASE_URL dan TOKEN
 * (jangan commit token). Untuk produksi, pindahkan ke SharedPreferences + layar pengaturan.
 */
class RelayService : NotificationListenerService() {
    private val io = Executors.newSingleThreadExecutor()

    companion object {
        const val BASE_URL = "http://laptop.tailnet-anda.ts.net:8765"
        const val TOKEN = "ISI_TOKEN_PERANGKAT"
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.isOngoing) return                       // abaikan notifikasi tetap (musik, VPN, dll.)
        val extras = sbn.notification.extras
        val body = JSONObject()
            .put("app", sbn.packageName)
            .put("title", extras.getCharSequence("android.title")?.toString() ?: "")
            .put("text", extras.getCharSequence("android.text")?.toString() ?: "")
            .put("ts", sbn.postTime)
        io.execute { post(body.toString()) }
    }

    private fun post(json: String) {
        try {
            val c = URL("$BASE_URL/ingest/notification").openConnection() as HttpURLConnection
            c.requestMethod = "POST"
            c.connectTimeout = 8000; c.readTimeout = 8000
            c.setRequestProperty("Content-Type", "application/json")
            c.setRequestProperty("X-Device-Token", TOKEN)
            c.doOutput = true
            c.outputStream.use { it.write(json.toByteArray()) }
            c.responseCode                                // paksa request terkirim
            c.disconnect()
        } catch (_: Exception) { /* offline: abaikan; versi lanjutan bisa antre lokal */ }
    }
}
