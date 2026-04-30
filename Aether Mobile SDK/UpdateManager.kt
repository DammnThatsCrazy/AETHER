// =============================================================================
// Aether SDK — Android OTA Update Manager (v5.0.0)
// Fetches remote manifest, syncs OTA data modules (chain registry, protocols,
// wallet labels, wallet classification) without requiring SDK reinstall.
// Runs entirely on Dispatchers.IO — never blocks the main thread.
// =============================================================================

package com.aether.sdk.update

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

// =============================================================================
// Manifest Types
// =============================================================================

data class DataModuleDescriptor(
    val version: String,
    val url: String,
    val hash: String,
    val size: Int,
    val updatedAt: String
)

data class SDKManifest(
    val latestVersion: String,
    val minimumVersion: String,
    val updateUrgency: String,
    val featureFlags: Map<String, Boolean>,
    val dataModules: Map<String, DataModuleDescriptor>,
    val checkIntervalMs: Long,
    val generatedAt: String
)

// =============================================================================
// AetherUpdateManager (Singleton)
// =============================================================================

/**
 * Singleton OTA data-module manager for Android.
 *
 * Usage:
 * ```kotlin
 * AetherUpdateManager.start(
 *     context = applicationContext,
 *     apiKey = "ak_...",
 *     endpoint = "https://api.aether.network",
 *     currentVersion = "5.0.0"
 * )
 *
 * // Later — read cached module:
 * val chains = AetherUpdateManager.getDataModule("chainRegistry", JSONObject::class.java)
 * ```
 */
object AetherUpdateManager {

    const val VERSION = "5.0.0"
    private const val TAG = "AetherUpdateManager"
    private const val PREFS_NAME = "com.aether.sdk.data"
    private const val MANIFEST_KEY = "_aether_manifest"
    private const val MODULE_PREFIX = "_aether_dm_"
    private const val CONNECT_TIMEOUT_MS = 10_000
    private const val READ_TIMEOUT_MS = 15_000

    // -------------------------------------------------------------------------
    // Internal state
    // -------------------------------------------------------------------------

    private var apiKey: String? = null
    private var endpoint: String? = null
    private var currentVersion: String? = null
    private var prefs: SharedPreferences? = null
    private var isRunning = false
    private var destroyed = false

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var checkJob: Job? = null

    // -------------------------------------------------------------------------
    // Listeners
    // -------------------------------------------------------------------------

    /** Callback invoked on the **main thread** when a critical update is available. */
    var onUpdateAvailable: ((version: String, urgency: String) -> Unit)? = null

    // -------------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------------

    /**
     * Start background update checks.
     *
     * @param context         Application context (used for SharedPreferences).
     * @param apiKey          Aether API key (sent as Bearer token).
     * @param endpoint        Base URL (e.g. `https://api.aether.network`).
     * @param currentVersion  The version string of the current SDK bundle.
     */
    fun start(context: Context, apiKey: String, endpoint: String, currentVersion: String) {
        if (destroyed) {
            log("Cannot start — manager was destroyed")
            return
        }
        if (isRunning) {
            log("Already running")
            return
        }

        this.apiKey = apiKey
        this.endpoint = endpoint
        this.currentVersion = currentVersion
        this.prefs = context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        this.isRunning = true

        log("Starting AetherUpdateManager v$VERSION")

        // Fire initial check (fire-and-forget).
        scope.launch { performUpdateCheck() }
    }

    /**
     * Retrieve a previously cached data module, deserialized into [clazz].
     *
     * Supported types:
     *  - `JSONObject::class.java` — returns the raw parsed JSON.
     *  - Any class with a `(String) -> T` constructor accepting a JSON string.
     *
     * @param key   Module key, e.g. `"chainRegistry"`.
     * @param clazz Target class.
     * @return The deserialized module, or `null` if not cached.
     */
    @Suppress("UNCHECKED_CAST")
    fun <T> getDataModule(key: String, clazz: Class<T>): T? {
        val raw = prefs?.getString(MODULE_PREFIX + key, null) ?: return null
        return try {
            val wrapper = JSONObject(raw)
            val data = wrapper.opt("data") ?: return null

            when {
                clazz == JSONObject::class.java -> {
                    when (data) {
                        is JSONObject -> data as T
                        is String -> JSONObject(data) as T
                        else -> null
                    }
                }
                clazz == String::class.java -> data.toString() as T
                else -> {
                    // Attempt construction via (String) constructor.
                    val ctor = clazz.getConstructor(String::class.java)
                    ctor.newInstance(data.toString())
                }
            }
        } catch (e: Exception) {
            log("Failed to decode cached module '$key': ${e.message}")
            null
        }
    }

    /**
     * Cancel all operations, release resources, and clear listeners.
     */
    fun destroy() {
        destroyed = true
        isRunning = false
        checkJob?.cancel()
        scope.coroutineContext.cancelChildren()
        onUpdateAvailable = null
        log("AetherUpdateManager destroyed")
    }

    /**
     * Clear all cached modules and the manifest from SharedPreferences.
     */
    fun clearCache() {
        val editor = prefs?.edit() ?: return
        prefs?.all?.keys?.filter { it.startsWith(MODULE_PREFIX) || it == MANIFEST_KEY }
            ?.forEach { editor.remove(it) }
        editor.apply()
        log("Cache cleared")
    }

    // -------------------------------------------------------------------------
    // Update Check Flow
    // -------------------------------------------------------------------------

    private suspend fun performUpdateCheck() {
        if (destroyed) return

        try {
            val manifest = fetchManifest()
            if (destroyed) return

            // Notify listener if a critical update is available.
            if (manifest.updateUrgency == "critical" &&
                manifest.latestVersion != currentVersion
            ) {
                withContext(Dispatchers.Main) {
                    onUpdateAvailable?.invoke(manifest.latestVersion, manifest.updateUrgency)
                }
            }

            // Sync data modules.
            syncDataModules(manifest)

            // Schedule next check.
            val intervalMs = resolveCheckInterval(manifest)
            scheduleNextCheck(intervalMs)
            log("Update check complete. Next in ${intervalMs / 1000}s")

        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            log("Update check failed: ${e.message}")
            // Retry in 5 minutes.
            scheduleNextCheck(300_000L)
        }
    }

    // -------------------------------------------------------------------------
    // Manifest Fetch
    // -------------------------------------------------------------------------

    private suspend fun fetchManifest(): SDKManifest = withContext(Dispatchers.IO) {
        val ep = endpoint ?: throw IllegalStateException("UpdateManager not configured")
        val urlString = "$ep/sdk/manifests/android/latest.json"
        log("Fetching manifest: $urlString")

        val url = URL(urlString)
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = READ_TIMEOUT_MS
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-Aether-SDK", "android")
            setRequestProperty("X-Aether-Version", currentVersion ?: "unknown")
            apiKey?.let { setRequestProperty("Authorization", "Bearer $it") }
        }

        try {
            val code = conn.responseCode
            if (code != 200) throw RuntimeException("HTTP $code fetching manifest")

            val body = conn.inputStream.bufferedReader().use(BufferedReader::readText)
            val json = JSONObject(body)

            // Cache raw manifest.
            prefs?.edit()?.putString(MANIFEST_KEY, body)?.apply()

            parseManifest(json)
        } finally {
            conn.disconnect()
        }
    }

    private fun parseManifest(json: JSONObject): SDKManifest {
        val featureFlags = mutableMapOf<String, Boolean>()
        json.optJSONObject("featureFlags")?.let { ff ->
            ff.keys().forEach { k -> featureFlags[k] = ff.optBoolean(k, false) }
        }

        val dataModules = mutableMapOf<String, DataModuleDescriptor>()
        json.optJSONObject("dataModules")?.let { dm ->
            dm.keys().forEach { k ->
                dm.optJSONObject(k)?.let { mod ->
                    dataModules[k] = DataModuleDescriptor(
                        version = mod.optString("version", ""),
                        url = mod.optString("url", ""),
                        hash = mod.optString("hash", ""),
                        size = mod.optInt("size", 0),
                        updatedAt = mod.optString("updatedAt", "")
                    )
                }
            }
        }

        return SDKManifest(
            latestVersion = json.optString("latestVersion", ""),
            minimumVersion = json.optString("minimumVersion", ""),
            updateUrgency = json.optString("updateUrgency", "none"),
            featureFlags = featureFlags,
            dataModules = dataModules,
            checkIntervalMs = json.optLong("checkIntervalMs", 3_600_000L),
            generatedAt = json.optString("generatedAt", "")
        )
    }

    // -------------------------------------------------------------------------
    // Data Module Sync
    // -------------------------------------------------------------------------

    private suspend fun syncDataModules(manifest: SDKManifest) {
        val jobs = manifest.dataModules.map { (name, descriptor) ->
            scope.async {
                // Check cached version — skip if identical.
                val cachedVersion = getCachedModuleVersion(name)
                if (cachedVersion == descriptor.version) {
                    log("Module '$name' v$cachedVersion up to date")
                    return@async
                }
                downloadAndCacheModule(name, descriptor)
            }
        }
        jobs.forEach {
            try { it.await() } catch (_: Exception) { /* individual failures are logged */ }
        }
    }

    private suspend fun downloadAndCacheModule(
        name: String,
        descriptor: DataModuleDescriptor
    ) = withContext(Dispatchers.IO) {
        log("Downloading module '$name' v${descriptor.version}")

        val url = URL(descriptor.url)
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = CONNECT_TIMEOUT_MS
            readTimeout = READ_TIMEOUT_MS
            setRequestProperty("Accept", "application/json")
            apiKey?.let { setRequestProperty("Authorization", "Bearer $it") }
        }

        try {
            val code = conn.responseCode
            if (code != 200) {
                log("HTTP $code downloading module '$name'")
                return@withContext
            }

            val bodyBytes = conn.inputStream.readBytes()
            val body = String(bodyBytes, Charsets.UTF_8)

            // Verify SHA-256 hash.
            if (descriptor.hash.isNotEmpty()) {
                val computedHash = sha256Hex(bodyBytes)
                if (computedHash != descriptor.hash) {
                    log("Hash mismatch for '$name': expected ${descriptor.hash}, got $computedHash")
                    return@withContext
                }
            }

            // Parse JSON to validate.
            val parsed = try { JSONObject(body) } catch (_: Exception) {
                log("Invalid JSON for module '$name'")
                return@withContext
            }

            // Build cache wrapper.
            val wrapper = JSONObject().apply {
                put("version", descriptor.version)
                put("data", parsed)
                put("hash", descriptor.hash)
                put("updatedAt", descriptor.updatedAt)
            }

            prefs?.edit()?.putString(MODULE_PREFIX + name, wrapper.toString())?.apply()
            log("Cached module '$name' v${descriptor.version}")

        } finally {
            conn.disconnect()
        }
    }

    // -------------------------------------------------------------------------
    // Cache Helpers
    // -------------------------------------------------------------------------

    private fun getCachedModuleVersion(name: String): String? {
        val raw = prefs?.getString(MODULE_PREFIX + name, null) ?: return null
        return try {
            JSONObject(raw).optString("version", null)
        } catch (_: Exception) {
            null
        }
    }

    // -------------------------------------------------------------------------
    // Scheduling
    // -------------------------------------------------------------------------

    private fun scheduleNextCheck(delayMs: Long) {
        checkJob?.cancel()
        checkJob = scope.launch {
            delay(delayMs)
            performUpdateCheck()
        }
    }

    private fun resolveCheckInterval(manifest: SDKManifest): Long {
        val ms = manifest.checkIntervalMs
        // Clamp: minimum 60s, maximum 24h.
        return ms.coerceIn(60_000L, 86_400_000L)
    }

    // -------------------------------------------------------------------------
    // SHA-256
    // -------------------------------------------------------------------------

    private fun sha256Hex(data: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val hash = digest.digest(data)
        return hash.joinToString("") { "%02x".format(it) }
    }

    // -------------------------------------------------------------------------
    // Logging
    // -------------------------------------------------------------------------

    private fun log(message: String) {
        Log.d(TAG, message)
    }
}
