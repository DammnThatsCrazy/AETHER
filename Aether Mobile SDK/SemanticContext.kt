// =============================================================================
// AETHER SDK — Android Tiered Semantic Context
// Enriches every event with layered context based on consent + configuration.
// Tier 1: Essential (always) → Tier 2: Functional → Tier 3: Rich
// =============================================================================

package com.aether.sdk

import android.content.Context
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.CopyOnWriteArrayList

// =============================================================================
// TYPES
// =============================================================================

enum class ContextTier(val level: Int) {
    ESSENTIAL(1),
    FUNCTIONAL(2),
    RICH(3);

    companion object {
        fun fromLevel(level: Int): ContextTier = entries.firstOrNull { it.level == level } ?: ESSENTIAL
    }
}

// =============================================================================
// COLLECTOR
// =============================================================================

object SemanticContextCollector {
    private const val SDK_VERSION = "5.0.0"
    private val dateFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }

    private var appContext: Context? = null

    // Tier 2 state
    private val screenPath = CopyOnWriteArrayList<String>()
    @Volatile private var eventSequence = 0
    @Volatile private var sessionStartMs = System.currentTimeMillis()
    @Volatile private var entryPoint = ""
    @Volatile private var screenDepth = 0
    @Volatile private var appState = "active"

    // Tier 3 state
    private val errorBuffer = CopyOnWriteArrayList<Triple<String, String, String>>()
    @Volatile private var backtrackCount = 0
    @Volatile private var interactionCount = 0

    // Consent
    @Volatile private var analyticsConsent = false
    @Volatile private var marketingConsent = false

    fun initialize(context: Context) {
        appContext = context.applicationContext
    }

    // =========================================================================
    // PUBLIC API
    // =========================================================================

    fun collect(): JSONObject {
        eventSequence++
        val tier = resolveTier()

        val envelope = JSONObject().apply {
            put("tier", tier.level)
            put("t1", collectTier1())
            if (tier.level >= 2) put("t2", collectTier2())
            if (tier.level >= 3) put("t3", collectTier3())
        }
        return envelope
    }

    fun recordScreen(name: String) {
        if (screenPath.size >= 2 && screenPath[screenPath.size - 2] == name) {
            backtrackCount++
        }
        screenPath.add(name)
        if (screenPath.size > 50) {
            val trimmed = screenPath.subList(screenPath.size - 50, screenPath.size).toList()
            screenPath.clear()
            screenPath.addAll(trimmed)
        }
        screenDepth++
        if (entryPoint.isEmpty()) entryPoint = name
    }

    fun recordError(message: String, type: String) {
        errorBuffer.add(Triple(message, type, dateFormat.format(Date())))
        if (errorBuffer.size > 100) errorBuffer.removeAt(0)
    }

    fun recordInteraction() { interactionCount++ }

    fun updateConsent(analytics: Boolean, marketing: Boolean) {
        analyticsConsent = analytics
        marketingConsent = marketing
    }

    fun updateAppState(state: String) { appState = state }

    fun resetSession() {
        screenPath.clear()
        eventSequence = 0
        sessionStartMs = System.currentTimeMillis()
        entryPoint = ""
        screenDepth = 0
        backtrackCount = 0
        interactionCount = 0
        errorBuffer.clear()
    }

    // =========================================================================
    // TIER COLLECTORS
    // =========================================================================

    private fun collectTier1(): JSONObject {
        val ctx = appContext
        return JSONObject().apply {
            put("eventId", UUID.randomUUID().toString())
            put("timestamp", dateFormat.format(Date()))
            put("sdkVersion", SDK_VERSION)
            put("platform", "android")
            put("device", JSONObject().apply {
                val isTablet = ctx?.resources?.configuration?.smallestScreenWidthDp?.let { it >= 600 } ?: false
                put("type", if (isTablet) "tablet" else "mobile")
                put("os", "Android ${Build.VERSION.RELEASE}")
                put("language", Locale.getDefault().language)
                put("online", true)
            })
        }
    }

    private fun collectTier2(): JSONObject {
        val elapsedMs = System.currentTimeMillis() - sessionStartMs
        return JSONObject().apply {
            put("journeyStage", inferJourneyStage(elapsedMs))
            put("screenPath", JSONArray(screenPath.takeLast(20)))
            put("sessionDuration", elapsedMs)
            put("appState", appState)
            put("screenDepth", screenDepth)
            put("eventSequenceIndex", eventSequence)
            put("entryPoint", entryPoint.ifEmpty { screenPath.firstOrNull() ?: "unknown" })
        }
    }

    private fun collectTier3(): JSONObject {
        val windowMs = 300_000L
        val cutoff = System.currentTimeMillis() - windowMs
        val recentErrors = errorBuffer.filter {
            try { dateFormat.parse(it.third)?.time?.let { ts -> ts >= cutoff } ?: false } catch (_: Exception) { false }
        }
        val errorRate = recentErrors.size.toDouble() / (windowMs / 60_000.0)

        val elapsedS = (System.currentTimeMillis() - sessionStartMs) / 1000.0
        val engagement = minOf(1.0, (screenDepth / 10.0) * 0.4 + minOf(elapsedS / 120.0, 1.0) * 0.6)
        val frustration = minOf(1.0, recentErrors.size * 0.2 / 5.0)
        val confusion = minOf(1.0, backtrackCount * 0.4 / 3.0)
        val urgency = if (eventSequence > 0) minOf(1.0, (screenDepth.toDouble() / eventSequence) * 2.0) else 0.0

        val lastErr = errorBuffer.lastOrNull()

        return JSONObject().apply {
            put("inferredIntent", JSONObject.NULL)
            put("sentimentSignals", JSONObject().apply {
                put("frustration", (frustration * 1000).toLong() / 1000.0)
                put("engagement", (engagement * 1000).toLong() / 1000.0)
                put("urgency", (urgency * 1000).toLong() / 1000.0)
                put("confusion", (confusion * 1000).toLong() / 1000.0)
            })
            put("errorLog", JSONObject().apply {
                put("errorCount", errorBuffer.size)
                if (lastErr != null) {
                    put("lastError", JSONObject().apply {
                        put("message", lastErr.first)
                        put("type", lastErr.second)
                        put("timestamp", lastErr.third)
                    })
                } else {
                    put("lastError", JSONObject.NULL)
                }
                put("errorRate", (errorRate * 100).toLong() / 100.0)
            })
        }
    }

    // =========================================================================
    // HELPERS
    // =========================================================================

    private fun resolveTier(): ContextTier {
        if (analyticsConsent && marketingConsent) return ContextTier.RICH
        if (analyticsConsent) return ContextTier.FUNCTIONAL
        return ContextTier.ESSENTIAL
    }

    private fun inferJourneyStage(elapsedMs: Long): String {
        if (elapsedMs < 10_000 && screenDepth <= 1) return "new"
        if (screenDepth > 5 || elapsedMs > 180_000) return "engaged"
        return "returning"
    }
}
