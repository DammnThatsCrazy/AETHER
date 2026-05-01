// =============================================================================
// Aether SDK — Android (Kotlin)
// Core analytics, identity, session, consent, lifecycle tracking
// =============================================================================

package com.aether.sdk

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.util.DisplayMetrics
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
    private const val VERSION = "5.0.0"
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

        // Initialize semantic context collector
        SemanticContextCollector.initialize(application.applicationContext)
        SemanticContextCollector.resetSession()

        // Initialize Web2 modules
        AetherEcommerce.initialize(
            context = application.applicationContext,
            apiKey = config.apiKey,
            endpoint = config.endpoint
        )
        AetherFeatureFlags.initialize(
            context = application.applicationContext,
            apiKey = config.apiKey,
            endpoint = config.endpoint
        )
        AetherFeedback.initialize(
            context = application.applicationContext,
            apiKey = config.apiKey,
            endpoint = config.endpoint,
            userId = anonymousId
        )

        isInitialized = true
        log("Aether Android SDK initialized (v$VERSION) — Web2 + Web3 modules enabled")

        // Start OTA data module update manager (non-blocking, background)
        AetherUpdateManager.start(
            context = application.applicationContext,
            apiKey = config.apiKey,
            endpoint = config.endpoint,
            currentVersion = VERSION
        )
    }

    fun track(event: String, properties: Map<String, Any?> = emptyMap()) {
        val props = mutableMapOf<String, Any?>("event" to event)
        props.putAll(properties)
        enqueueEvent("track", props)
    }

    fun screenView(screenName: String, properties: Map<String, Any?> = emptyMap()) {
        screenCount++
        SemanticContextCollector.recordScreen(screenName)
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

        // Inject tiered semantic context into every event
        val enrichedProperties = properties.toMutableMap()
        try {
            enrichedProperties["_semantic"] = SemanticContextCollector.collect()
        } catch (_: Exception) {}

        val event = JSONObject().apply {
            put("id", UUID.randomUUID().toString())
            put("type", type)
            put("timestamp", dateFormat.format(Date()))
            put("sessionId", sessionId)
            put("anonymousId", anonymousId)
            put("userId", userId ?: JSONObject.NULL)
            put("properties", JSONObject(enrichedProperties.mapValues { it.value ?: JSONObject.NULL }))
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

    private fun buildContext(): JSONObject {
        val ctx = context ?: return JSONObject()
        val dm = ctx.resources.displayMetrics

        return JSONObject().apply {
            put("library", JSONObject().apply {
                put("name", "AetherSDK-Android")
                put("version", VERSION)
            })
            put("device", JSONObject().apply {
                put("type", if (ctx.resources.configuration.smallestScreenWidthDp >= 600) "tablet" else "mobile")
                put("os", "Android")
                put("osVersion", Build.VERSION.RELEASE)
                put("model", Build.MODEL)
                put("manufacturer", Build.MANUFACTURER)
                put("screenWidth", dm.widthPixels)
                put("screenHeight", dm.heightPixels)
                put("density", dm.density)
                put("language", Locale.getDefault().language)
                put("timezone", TimeZone.getDefault().id)
            })
        }
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
