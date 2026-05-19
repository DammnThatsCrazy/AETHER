// =============================================================================
// Aether SDK — FEATURE FLAGS MODULE (Android)
// Client-side feature flag evaluation with remote configuration
// =============================================================================

package com.aether.sdk

import android.content.Context
import android.content.SharedPreferences
import android.os.Handler
import android.os.Looper
import android.util.Log
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap

// =============================================================================
// TYPES
// =============================================================================

data class AetherFeatureFlag(
    val key: String,
    val enabled: Boolean,
    val value: Any? = null,
    val variant: String? = null,
    val source: FlagSource = FlagSource.DEFAULT
) {
    enum class FlagSource(val value: String) {
        REMOTE("remote"),
        LOCAL("local"),
        DEFAULT("default"),
        OVERRIDE("override")
    }

    fun toMap(): Map<String, Any?> = mapOf(
        "key" to key,
        "enabled" to enabled,
        "value" to value,
        "variant" to variant,
        "source" to source.value
    )
}

data class AetherFlagConfig(
    val endpoint: String,
    val apiKey: String,
    val refreshIntervalMs: Long = 300_000L,
    val defaults: Map<String, AetherFeatureFlag> = emptyMap(),
    val overrides: Map<String, Any> = emptyMap()
)

// =============================================================================
// FEATURE FLAGS MODULE
// =============================================================================

object AetherFeatureFlags {
    private const val TAG = "AetherFeatureFlags"
    private const val PREFS_NAME = "com.aether.sdk.flags"
    private const val CACHE_KEY = "aether_feature_flags"

    private var prefs: SharedPreferences? = null
    private var config: AetherFlagConfig? = null
    @Volatile private var isConfigured = false

    /** Remote flags fetched from the server. */
    private val flags = ConcurrentHashMap<String, AetherFeatureFlag>()
    /** Local overrides for dev/testing. */
    private val overrides = ConcurrentHashMap<String, Any>()
    /** Default flag values set at configure time. */
    private val defaultFlags = ConcurrentHashMap<String, AetherFeatureFlag>()

    private val handler = Handler(Looper.getMainLooper())
    private var refreshRunnable: Runnable? = null

    // =========================================================================
    // CONFIGURATION
    // =========================================================================

    /**
     * Initialize the feature flags module.
     * Loads cache, applies defaults/overrides, and starts background refresh.
     */
    fun configure(context: Context, config: AetherFlagConfig) {
        this.config = config
        this.prefs = context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        this.isConfigured = true

        // Apply defaults and initial overrides
        defaultFlags.clear()
        defaultFlags.putAll(config.defaults)
        overrides.clear()
        overrides.putAll(config.overrides)

        // Load cached flags from disk
        loadCache()

        // Start background refresh
        startRefreshTimer(config.refreshIntervalMs)

        // Fire initial fetch on a background thread
        Thread { fetchFlags() }.start()
    }

    // =========================================================================
    // PUBLIC API
    // =========================================================================

    /** Simple boolean check for a flag key. */
    fun isEnabled(key: String): Boolean {
        val flag = resolveFlag(key)
        Aether.track("feature_flag_evaluated", mapOf(
            "flag_key" to key,
            "enabled" to flag.enabled,
            "source" to flag.source.value
        ))
        return flag.enabled
    }

    /** Get the full flag object with metadata. */
    fun getFlag(key: String): AetherFeatureFlag {
        val flag = resolveFlag(key)
        Aether.track("feature_flag_evaluated", mapOf(
            "flag_key" to key,
            "enabled" to flag.enabled,
            "source" to flag.source.value,
            "variant" to (flag.variant ?: "")
        ))
        return flag
    }

    /** Get a typed value from a flag, falling back to the provided default. */
    @Suppress("UNCHECKED_CAST")
    fun <T> getValue(key: String, default: T): T {
        val flag = resolveFlag(key)
        return try {
            (flag.value as? T) ?: default
        } catch (_: Exception) {
            default
        }
    }

    /** Set a local override for a flag (useful for dev/testing). */
    fun setOverride(key: String, value: Any) {
        overrides[key] = value
    }

    /** Clear a local override for a flag. */
    fun clearOverride(key: String) {
        overrides.remove(key)
    }

    /** Clear all local overrides. */
    fun clearAllOverrides() {
        overrides.clear()
    }

    /** Force a remote fetch of flags. */
    fun refresh() {
        Thread { fetchFlags() }.start()
    }

    /** Stop the background refresh timer and clean up. */
    fun destroy() {
        refreshRunnable?.let { handler.removeCallbacks(it) }
        refreshRunnable = null
        isConfigured = false
    }

    // =========================================================================
    // FLAG RESOLUTION — Priority: overrides > remote > defaults
    // =========================================================================

    private fun resolveFlag(key: String): AetherFeatureFlag {
        // 1. Check overrides
        val overrideValue = overrides[key]
        if (overrideValue != null) {
            val enabled = (overrideValue as? Boolean) ?: true
            return AetherFeatureFlag(
                key = key,
                enabled = enabled,
                value = overrideValue,
                source = AetherFeatureFlag.FlagSource.OVERRIDE
            )
        }

        // 2. Check remote flags
        flags[key]?.let { return it }

        // 3. Check defaults
        defaultFlags[key]?.let { return it }

        // 4. Unknown flag — disabled by default
        return AetherFeatureFlag(key = key, enabled = false)
    }

    // =========================================================================
    // REMOTE FETCH
    // =========================================================================

    private fun fetchFlags() {
        val cfg = config ?: return

        try {
            val url = URL("${cfg.endpoint}/sdk/flags")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 10_000
                readTimeout = 10_000
                setRequestProperty("Accept", "application/json")
                setRequestProperty("Authorization", "Bearer ${cfg.apiKey}")
                setRequestProperty("X-Aether-SDK", "android")
            }

            try {
                val code = conn.responseCode
                if (code != 200) return

                val body = conn.inputStream.bufferedReader().use(BufferedReader::readText)
                parseAndCacheFlags(body)
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            Log.d(TAG, "Flag fetch failed: ${e.message}")
        }
    }

    private fun parseAndCacheFlags(body: String) {
        try {
            val json = JSONObject(body)
            val flagsArray = json.optJSONArray("flags") ?: return

            for (i in 0 until flagsArray.length()) {
                val obj = flagsArray.getJSONObject(i)
                val key = obj.optString("key", "")
                if (key.isEmpty()) continue

                val flag = AetherFeatureFlag(
                    key = key,
                    enabled = obj.optBoolean("enabled", false),
                    value = if (obj.has("value")) obj.opt("value") else null,
                    variant = obj.optString("variant", null),
                    source = AetherFeatureFlag.FlagSource.REMOTE
                )
                flags[key] = flag
            }

            // Persist to cache
            prefs?.edit()?.putString(CACHE_KEY, body)?.apply()
        } catch (_: Exception) {
            // Malformed response — ignore
        }
    }

    // =========================================================================
    // CACHE
    // =========================================================================

    private fun loadCache() {
        val raw = prefs?.getString(CACHE_KEY, null) ?: return
        parseAndCacheFlags(raw)
        // Re-tag cached flags as local (from cache, not live remote)
        for ((key, flag) in flags) {
            flags[key] = flag.copy(source = AetherFeatureFlag.FlagSource.LOCAL)
        }
    }

    // =========================================================================
    // BACKGROUND REFRESH
    // =========================================================================

    private fun startRefreshTimer(intervalMs: Long) {
        refreshRunnable?.let { handler.removeCallbacks(it) }

        val runnable = object : Runnable {
            override fun run() {
                Thread { fetchFlags() }.start()
                handler.postDelayed(this, intervalMs)
            }
        }
        refreshRunnable = runnable
        handler.postDelayed(runnable, intervalMs)
    }
}
