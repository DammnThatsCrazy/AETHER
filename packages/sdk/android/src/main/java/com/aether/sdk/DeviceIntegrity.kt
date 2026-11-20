package com.aether.sdk

import android.content.SharedPreferences
import org.json.JSONObject

/**
 * Google Play Integrity for agent-detection device-integrity evidence.
 *
 * Opt in with `AetherConfig(deviceIntegrity = true)` and add the Play Integrity
 * library to the app (`com.google.android.play:integrity`); the SDK links it
 * `compileOnly`, so apps that do not opt in carry no Play dependency. The SDK
 * asks Aether for a single-use challenge, requests an integrity token with it as
 * the nonce, and receives a short-lived integrity token that rides on every
 * event as `context.device.integrity`.
 *
 * Integrity proves a genuine app on a genuine device. It is evidence against
 * spoofed / scripted clients, never proof that a human is acting.
 * See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
 */
internal class DeviceIntegrityManager(
    private val prefs: SharedPreferences,
    private val post: suspend (path: String, body: JSONObject) -> JSONObject?,
    private val requestPlayToken: suspend (nonce: String) -> String?,
    private val packageName: String,
    private val now: () -> Long = { System.currentTimeMillis() / 1000 },
) {
    @Volatile private var inFlight = false

    fun currentToken(anonymousId: String): String? {
        val stored = load() ?: return null
        if (stored.optString("anonymousId") != anonymousId) return null
        if (stored.optLong("expiresAt") <= now()) return null
        return stored.optString("token").ifEmpty { null }
    }

    fun needsRefresh(anonymousId: String): Boolean {
        val stored = load() ?: return true
        if (stored.optString("anonymousId") != anonymousId) return true
        return stored.optLong("expiresAt") - REFRESH_MARGIN_SECONDS <= now()
    }

    fun clear() {
        prefs.edit().remove(PREFS_KEY).apply()
    }

    /** Attest when due. Never throws. */
    suspend fun refreshIfNeeded(anonymousId: String) {
        if (!needsRefresh(anonymousId) || inFlight) return
        inFlight = true
        try {
            val challenge = post(
                "/sdk/device-integrity/challenge",
                JSONObject().put("platform", "android").put("anonymousId", anonymousId),
            )?.optString("challenge")?.ifEmpty { null } ?: return
            val integrityToken = requestPlayToken(challenge) ?: return
            val result = post(
                "/sdk/device-integrity/verify",
                JSONObject()
                    .put("platform", "android")
                    .put("anonymousId", anonymousId)
                    .put("challenge", challenge)
                    .put("integrityToken", integrityToken)
                    .put("packageName", packageName),
            )
            store(result, anonymousId)
        } catch (_: Throwable) {
            // Integrity is best-effort evidence; never break the host app.
        } finally {
            inFlight = false
        }
    }

    /** Persist a verify response (`integrityToken`, `expiresAt`). */
    fun store(result: JSONObject?, anonymousId: String) {
        val token = result?.optString("integrityToken")?.ifEmpty { null } ?: return
        val expires = result.optLong("expiresAt", 0L)
        if (expires <= 0L) return
        val stored = JSONObject().put("token", token).put("expiresAt", expires).put("anonymousId", anonymousId)
        prefs.edit().putString(PREFS_KEY, stored.toString()).apply()
    }

    private fun load(): JSONObject? = try {
        prefs.getString(PREFS_KEY, null)?.let { JSONObject(it) }
    } catch (_: Exception) {
        null
    }

    companion object {
        const val PREFS_KEY = "aether_device_integrity_token"
        const val REFRESH_MARGIN_SECONDS = 6L * 3600L
        private const val PLAY_INTEGRITY_CLASS =
            "com.google.android.play.core.integrity.IntegrityManagerFactory"

        /** True when the host app ships the Play Integrity library. */
        fun playIntegrityAvailable(): Boolean = try {
            Class.forName(PLAY_INTEGRITY_CLASS, false, DeviceIntegrityManager::class.java.classLoader)
            true
        } catch (_: Throwable) {
            false
        }
    }
}
