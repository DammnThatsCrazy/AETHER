// =============================================================================
// AETHER SDK — Android (Kotlin)
// Core analytics, identity, session, consent, lifecycle tracking
// =============================================================================

package com.aether.sdk

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.lifecycle.*
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.ConcurrentLinkedQueue

// =============================================================================
// CONFIGURATION
// =============================================================================

data class AetherConfig(
    val apiKey: String,
    val environment: Environment = Environment.PRODUCTION,
    val debug: Boolean = false,
    val endpoint: String = "https://api.aether.network",
    val batchSize: Int = 10,
    val flushIntervalMs: Long = 5000L,
    val modules: ModuleConfig = ModuleConfig(),
    val privacy: PrivacyConfig = PrivacyConfig()
) {
    enum class Environment { PRODUCTION, STAGING, DEVELOPMENT }
}

data class ModuleConfig(
    val activityTracking: Boolean = true,
    val deepLinkAttribution: Boolean = true,
    val pushTracking: Boolean = true,
    val walletTracking: Boolean = false,
    val purchaseTracking: Boolean = true,
    val errorTracking: Boolean = true,
    val experiments: Boolean = true
)

data class PrivacyConfig(
    val gdprMode: Boolean = false,
    val anonymizeIP: Boolean = true
)

// =============================================================================
// IDENTITY
// =============================================================================

data class IdentityData(
    val userId: String? = null,
    val walletAddress: String? = null,
    val walletType: String? = null,
    val chainId: Int? = null,
    val traits: Map<String, Any?> = emptyMap()
)

// =============================================================================
// MAIN SDK
// =============================================================================

object Aether : DefaultLifecycleObserver {
    private const val TAG = "AetherSDK"
    private const val VERSION = "7.0.0"
    private const val PREFS_NAME = "com.aether.sdk"

    private var config: AetherConfig? = null
    private var context: Context? = null
    private var prefs: SharedPreferences? = null

    private val eventQueue = ConcurrentLinkedQueue<JSONObject>()
    private var flushJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private var sessionId: String = UUID.randomUUID().toString()
    private var anonymousId: String = ""
    private var userId: String? = null
    private var traits: MutableMap<String, Any?> = mutableMapOf()
    private var screenCount = 0
    private var eventCount = 0
    private var isInitialized = false
    private var serverConfig: JSONObject = JSONObject()
    private var consentState: MutableList<String> = mutableListOf()
    private var fingerprintId: String = ""
    private val dateFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }

    // =========================================================================
    // PUBLIC API
    // =========================================================================

    fun initialize(application: Application, config: AetherConfig) {
        if (isInitialized) {
            log("Already initialized")
            return
        }

        this.config = config
        this.context = application.applicationContext
        this.prefs = application.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        this.anonymousId = loadOrCreateAnonymousId()
        this.userId = prefs?.getString("userId", null)
        this.sessionId = UUID.randomUUID().toString()

        // Lifecycle tracking
        ProcessLifecycleOwner.get().lifecycle.addObserver(this)

        // Auto Activity tracking
        if (config.modules.activityTracking) {
            application.registerActivityLifecycleCallbacks(ActivityTracker())
        }

        // Uncaught exception handler
        if (config.modules.errorTracking) {
            setupErrorTracking()
        }

        // Start flush timer
        startFlushTimer()

        fingerprintId = DeviceFingerprint.generate(application.applicationContext)

        isInitialized = true
        log("Aether Android SDK initialized (v$VERSION)")

        fetchConfig()
    }

    fun track(event: String, properties: Map<String, Any?> = emptyMap()) {
        val props = mutableMapOf<String, Any?>("event" to event)
        props.putAll(properties)
        enqueueEvent("track", props)
    }

    fun screenView(screenName: String, properties: Map<String, Any?> = emptyMap()) {
        screenCount++
        val props = mutableMapOf<String, Any?>("screen" to screenName)
        props.putAll(properties)
        enqueueEvent("screen", props)
    }

    fun conversion(event: String, value: Double? = null, properties: Map<String, Any?> = emptyMap()) {
        val props = mutableMapOf<String, Any?>("event" to event)
        if (value != null) props["value"] = value
        props.putAll(properties)
        enqueueEvent("conversion", props)
    }

    fun hydrateIdentity(data: IdentityData) {
        data.userId?.let { userId = it }
        traits.putAll(data.traits)

        val props = mutableMapOf<String, Any?>(
            "userId" to (userId ?: ""),
            "traits" to traits,
            "walletAddress" to (data.walletAddress ?: "")
        )
        enqueueEvent("identify", props)

        prefs?.edit()?.putString("userId", userId)?.apply()
    }

    fun getAnonymousId(): String = anonymousId
    fun getUserId(): String? = userId

    fun reset() {
        flush()
        userId = null
        traits.clear()
        anonymousId = UUID.randomUUID().toString()
        sessionId = UUID.randomUUID().toString()
        prefs?.edit()
            ?.remove("userId")
            ?.putString("anonymousId", anonymousId)
            ?.apply()
        log("SDK reset")
    }

    fun flush() {
        scope.launch { sendBatch() }
    }

    fun handleDeepLink(url: String) {
        try {
            val uri = java.net.URI(url)
            val params = uri.query?.split("&")?.associate {
                val parts = it.split("=", limit = 2)
                parts[0] to (parts.getOrNull(1) ?: "")
            } ?: emptyMap()

            val attribution = mutableMapOf<String, Any?>("url" to url)
            params.forEach { (key, value) ->
                if (key.startsWith("utm_") || key in listOf("gclid", "fbclid", "msclkid")) {
                    attribution[key] = value
                }
            }
            track("deep_link_opened", attribution)
        } catch (e: Exception) {
            log("Failed to parse deep link: ${e.message}")
        }
    }

    fun trackPushOpened(data: Map<String, String>) {
        track("push_notification_opened", mapOf(
            "campaignId" to (data["campaign_id"] ?: ""),
            "messageId" to (data["message_id"] ?: "")
        ))
    }

    // =========================================================================
    // WALLET TRACKING
    // =========================================================================

    fun walletConnected(address: String, walletType: String = "unknown", chainId: String = "unknown") {
        enqueueEvent("wallet", mapOf(
            "action" to "connect", "address" to address,
            "walletType" to walletType, "chainId" to chainId
        ))
    }

    fun walletDisconnected(address: String) {
        enqueueEvent("wallet", mapOf("action" to "disconnect", "address" to address))
    }

    fun walletTransaction(txHash: String, chainId: String, value: String? = null, properties: Map<String, Any>? = null) {
        val props = mutableMapOf<String, Any>(
            "action" to "transaction", "txHash" to txHash, "chainId" to chainId
        )
        value?.let { props["value"] = it }
        properties?.let { props.putAll(it) }
        enqueueEvent("transaction", props)
    }

    // =========================================================================
    // CONSENT MANAGEMENT
    // =========================================================================

    fun grantConsent(categories: List<String>) {
        consentState.addAll(categories)
        enqueueEvent("consent", mapOf("action" to "grant", "categories" to categories))
    }

    fun revokeConsent(categories: List<String>) {
        consentState.removeAll(categories)
        enqueueEvent("consent", mapOf("action" to "revoke", "categories" to categories))
    }

    fun getConsentState(): List<String> = consentState.toList()

    // =========================================================================
    // ECOMMERCE TRACKING
    // =========================================================================

    fun trackProductView(product: Map<String, Any>) {
        enqueueEvent("track", mapOf("event" to "product_viewed", "product" to product))
    }

    fun trackAddToCart(item: Map<String, Any>) {
        enqueueEvent("track", mapOf("event" to "product_added", "item" to item))
    }

    fun trackPurchase(orderId: String, total: Double, currency: String = "USD", items: List<Map<String, Any>>? = null) {
        val props = mutableMapOf<String, Any>(
            "event" to "order_completed", "orderId" to orderId,
            "total" to total, "currency" to currency
        )
        items?.let { props["items"] = it }
        enqueueEvent("conversion", props)
    }

    // =========================================================================
    // FEATURE FLAGS
    // =========================================================================

    fun isFeatureEnabled(key: String, default: Boolean = false): Boolean {
        return try {
            serverConfig.optJSONObject("featureFlags")?.optBoolean(key, default) ?: default
        } catch (_: Exception) { default }
    }

    fun getFeatureValue(key: String, default: Any? = null): Any? {
        return try {
            serverConfig.optJSONObject("featureFlags")?.opt(key) ?: default
        } catch (_: Exception) { default }
    }

    // =========================================================================
    // LIFECYCLE
    // =========================================================================

    override fun onStart(owner: LifecycleOwner) {
        sessionId = UUID.randomUUID().toString()
        track("app_foreground")
    }

    override fun onStop(owner: LifecycleOwner) {
        track("app_background")
        flush()
    }

    // =========================================================================
    // PRIVATE
    // =========================================================================

    private fun enqueueEvent(type: String, properties: Map<String, Any?>) {
        if (!isInitialized) return

        val event = JSONObject().apply {
            put("id", UUID.randomUUID().toString())
            put("type", type)
            put("timestamp", dateFormat.format(Date()))
            put("sessionId", sessionId)
            put("anonymousId", anonymousId)
            put("userId", userId ?: JSONObject.NULL)
            put("properties", JSONObject(properties.mapValues { it.value ?: JSONObject.NULL }))
            put("context", buildContext())
        }

        eventQueue.add(event)
        eventCount++

        if (eventQueue.size >= (config?.batchSize ?: 10)) {
            scope.launch { sendBatch() }
        }
    }

    private suspend fun sendBatch() = withContext(Dispatchers.IO) {
        val cfg = config ?: return@withContext
        if (eventQueue.isEmpty()) return@withContext

        val batch = mutableListOf<JSONObject>()
        repeat(minOf(cfg.batchSize, eventQueue.size)) {
            eventQueue.poll()?.let { batch.add(it) }
        }
        if (batch.isEmpty()) return@withContext

        try {
            val url = URL("${cfg.endpoint}/v1/batch")
            val connection = url.openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("Authorization", "Bearer ${cfg.apiKey}")
            connection.setRequestProperty("X-Aether-SDK", "android")
            connection.doOutput = true
            connection.connectTimeout = 10000
            connection.readTimeout = 10000

            val payload = JSONObject().apply {
                put("batch", JSONArray(batch))
                put("sentAt", dateFormat.format(Date()))
            }

            connection.outputStream.use { it.write(payload.toString().toByteArray()) }

            val responseCode = connection.responseCode
            if (responseCode >= 400) {
                log("Batch send HTTP error: $responseCode")
                batch.forEach { eventQueue.add(it) } // Re-enqueue
            }
            connection.disconnect()
        } catch (e: Exception) {
            log("Batch send failed: ${e.message}")
            batch.forEach { eventQueue.add(it) }
        }
    }

    private fun fetchConfig() {
        val endpoint = config?.endpoint ?: return
        scope.launch(Dispatchers.IO) {
            try {
                val url = URL("$endpoint/v1/config?apiKey=${config?.apiKey ?: ""}")
                val conn = url.openConnection() as HttpURLConnection
                conn.connectTimeout = 5000
                conn.readTimeout = 5000
                val response = conn.inputStream.bufferedReader().readText()
                serverConfig = JSONObject(response)
                if (config?.debug == true) log("Config loaded")
                conn.disconnect()
            } catch (_: Exception) { }
        }
    }

    private fun buildContext(): JSONObject = JSONObject().apply {
        put("os", JSONObject().apply {
            put("name", "Android")
            put("version", Build.VERSION.RELEASE)
        })
        put("locale", Locale.getDefault().toLanguageTag())
        put("timezone", TimeZone.getDefault().id)
        put("library", JSONObject().apply {
            put("name", "aether-android")
            put("version", VERSION)
        })
        put("fingerprint", JSONObject().apply {
            put("id", fingerprintId)
        })
    }

    private fun loadOrCreateAnonymousId(): String {
        prefs?.getString("anonymousId", null)?.let { return it }
        val id = UUID.randomUUID().toString()
        prefs?.edit()?.putString("anonymousId", id)?.apply()
        return id
    }

    private fun startFlushTimer() {
        flushJob?.cancel()
        flushJob = scope.launch {
            while (isActive) {
                delay(config?.flushIntervalMs ?: 5000L)
                sendBatch()
            }
        }
    }

    private fun setupErrorTracking() {
        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            try {
                enqueueEvent("error", mapOf(
                    "type" to "uncaught_exception",
                    "message" to (throwable.message ?: "Unknown"),
                    "stack" to (throwable.stackTraceToString().take(2000)),
                    "thread" to thread.name
                ))
                runBlocking { sendBatch() }
            } catch (_: Exception) {}
            defaultHandler?.uncaughtException(thread, throwable)
        }
    }

    private fun log(message: String) {
        if (config?.debug == true) Log.d(TAG, message)
    }

    // =========================================================================
    // DEVICE FINGERPRINT
    // =========================================================================

    private object DeviceFingerprint {
        fun generate(context: Context): String {
            val signals = listOf(
                Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: "",
                Build.MODEL,
                Build.MANUFACTURER,
                Build.VERSION.RELEASE,
                context.resources.displayMetrics.widthPixels.toString(),
                context.resources.displayMetrics.heightPixels.toString(),
                context.resources.displayMetrics.density.toString(),
                Locale.getDefault().toString(),
                TimeZone.getDefault().id,
                Runtime.getRuntime().availableProcessors().toString(),
            )
            return sha256(signals.joinToString("|"))
        }

        private fun sha256(input: String): String {
            val bytes = java.security.MessageDigest.getInstance("SHA-256").digest(input.toByteArray())
            return bytes.joinToString("") { "%02x".format(it) }
        }
    }

    // =========================================================================
    // ACTIVITY TRACKER
    // =========================================================================

    private class ActivityTracker : Application.ActivityLifecycleCallbacks {
        override fun onActivityResumed(activity: android.app.Activity) {
            val name = activity.javaClass.simpleName
            if (!name.startsWith("_")) {
                screenView(name)
            }
        }
        override fun onActivityCreated(a: android.app.Activity, s: android.os.Bundle?) {}
        override fun onActivityStarted(a: android.app.Activity) {}
        override fun onActivityPaused(a: android.app.Activity) {}
        override fun onActivityStopped(a: android.app.Activity) {}
        override fun onActivitySaveInstanceState(a: android.app.Activity, s: android.os.Bundle) {}
        override fun onActivityDestroyed(a: android.app.Activity) {}
    }
}
