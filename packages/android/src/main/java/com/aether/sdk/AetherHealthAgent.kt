// =============================================================================
// Aether SDK — Android Health Agent
// Emits signed fleet heartbeats and fetches remote config manifest.
// Fire-and-forget: heartbeat failure never blocks the event pipeline.
// =============================================================================

package com.aether.sdk

import android.content.SharedPreferences
import kotlinx.coroutines.*
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.UUID

data class SDKHeartbeatPayload(
    val sdk_id: String,
    val sdk_version: String,
    val platform: String,
    val app_version: String,
    val queue_depth: Int,
    val retry_count: Int,
    val dropped_events: Int,
    val endpoint_latency_ms: Double,
    val ingestion_success_rate: Double,
    val schema_hash: String,
    val auth_valid: Boolean,
    val consent_valid: Boolean,
    val wallet_connected: Boolean,
    val config_version: String,
    val rollout_cohort: String
)

data class SDKManifest(
    val manifest_version: String,
    val min_sdk_version: String,
    val schema_version: String,
    val rollout_percentage: Int,
    val features: Map<String, Boolean>,
    val published_at: String,
    val signature: String
)

typealias ManifestUpdateCallback = (SDKManifest) -> Unit

class AetherHealthAgent(
    private val endpoint: String,
    private val apiKey: String,
    private val platform: String = "android",
    private val appVersion: String = "",
    private val heartbeatIntervalMs: Long = 60_000L,
    private val manifestRefreshMs: Long = 300_000L,
    private val prefs: SharedPreferences? = null
) {
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var heartbeatJob: Job? = null
    private var manifestJob: Job? = null
    private var isRunning = false

    private val sdkId: String = loadOrCreateSdkId()
    private var configVersion: String = "0"
    private val manifestCallbacks = mutableListOf<ManifestUpdateCallback>()

    // Metrics
    var droppedEvents: Int = 0
        private set
    var retryCount: Int = 0
        private set
    private var totalAttempts: Int = 0
    private var successfulAttempts: Int = 0
    private var lastLatencyMs: Double = 0.0

    /** Provide live state at heartbeat time */
    var getDynamicState: (() -> Triple<Int, Boolean, Boolean>)? = null // (queueDepth, consentValid, walletConnected)

    fun start() {
        if (isRunning) return
        isRunning = true

        heartbeatJob = scope.launch {
            sendHeartbeat()
            while (isActive) {
                delay(heartbeatIntervalMs)
                sendHeartbeat()
            }
        }
        manifestJob = scope.launch {
            fetchManifest()
            while (isActive) {
                delay(manifestRefreshMs)
                fetchManifest()
            }
        }
    }

    fun stop() {
        isRunning = false
        heartbeatJob?.cancel()
        manifestJob?.cancel()
    }

    fun onManifestUpdate(callback: ManifestUpdateCallback) {
        manifestCallbacks.add(callback)
    }

    fun recordDroppedEvents(count: Int) { droppedEvents += count }
    fun recordRetry() { retryCount++ }
    fun recordBatchAttempt(success: Boolean, latencyMs: Double) {
        totalAttempts++
        if (success) successfulAttempts++
        lastLatencyMs = latencyMs
    }

    private suspend fun sendHeartbeat() = withContext(Dispatchers.IO) {
        try {
            val state = getDynamicState?.invoke()
            val queueDepth = state?.first ?: 0
            val consentValid = state?.second ?: true
            val walletConnected = state?.third ?: false
            val rate = if (totalAttempts > 0) successfulAttempts.toDouble() / totalAttempts else 1.0

            val payload = JSONObject().apply {
                put("sdk_id", sdkId)
                put("sdk_version", "8.12.0")
                put("platform", platform)
                put("app_version", appVersion)
                put("queue_depth", queueDepth)
                put("retry_count", retryCount)
                put("dropped_events", droppedEvents)
                put("endpoint_latency_ms", lastLatencyMs)
                put("ingestion_success_rate", rate)
                put("schema_hash", schemaHash())
                put("auth_valid", apiKey.isNotEmpty())
                put("consent_valid", consentValid)
                put("wallet_connected", walletConnected)
                put("config_version", configVersion)
                put("rollout_cohort", "default")
            }

            val url = URL("$endpoint/v1/diagnostics/sdk/heartbeat")
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("Authorization", "Bearer $apiKey")
            conn.setRequestProperty("X-Aether-SDK", "android")
            conn.doOutput = true
            conn.connectTimeout = 5000
            conn.readTimeout = 5000
            conn.outputStream.use { it.write(payload.toString().toByteArray()) }
            conn.responseCode // consume response
            conn.disconnect()
        } catch (_: Exception) { /* fire-and-forget */ }
    }

    private suspend fun fetchManifest() = withContext(Dispatchers.IO) {
        try {
            val url = URL("$endpoint/v1/config/sdk/manifest")
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "GET"
            conn.setRequestProperty("Authorization", "Bearer $apiKey")
            conn.connectTimeout = 5000
            conn.readTimeout = 5000
            if (conn.responseCode == 200) {
                val body = conn.inputStream.bufferedReader().readText()
                conn.disconnect()
                val json = JSONObject(body)
                val manifestVersion = json.optString("manifest_version", "0")
                val previousVersion = configVersion
                configVersion = manifestVersion
                val featuresJson = json.optJSONObject("features")
                val features = mutableMapOf<String, Boolean>()
                featuresJson?.keys()?.forEach { key -> features[key] = featuresJson.optBoolean(key, false) }
                val manifest = SDKManifest(
                    manifest_version = manifestVersion,
                    min_sdk_version = json.optString("min_sdk_version", "0"),
                    schema_version = json.optString("schema_version", "0"),
                    rollout_percentage = json.optInt("rollout_percentage", 100),
                    features = features,
                    published_at = json.optString("published_at", ""),
                    signature = json.optString("signature", "")
                )
                if (manifestVersion != previousVersion) {
                    val callbacks = manifestCallbacks.toList()
                    withContext(Dispatchers.Main) { callbacks.forEach { it(manifest) } }
                }
            } else {
                conn.disconnect()
            }
        } catch (_: Exception) { /* non-blocking */ }
    }

    private fun schemaHash(): String {
        val types = listOf(
            "track", "page", "screen", "heartbeat", "error", "performance", "experiment",
            "journey_started", "journey_paused", "journey_resumed", "journey_continued",
            "journey_completed", "journey_abandoned", "journey_checkpoint",
            "identify", "consent", "conversion",
            "payment_initiated", "payment_completed", "payment_failed",
            "approval_requested", "approval_resolved",
            "entitlement_granted", "entitlement_revoked",
            "access_granted", "access_denied",
            "x402_payment", "x402_resource_requested", "x402_payment_required",
            "x402_quote_received", "x402_authorization_requested", "x402_authorization_resolved",
            "x402_payment_intent_created", "x402_payment_submitted", "x402_payment_settled",
            "x402_payment_failed", "x402_payment_timeout", "x402_receipt_verified",
            "x402_access_granted", "x402_access_denied", "x402_refund_or_reversal",
            "reward_action_queued", "reward_proof_generated", "reward_delivered", "reward_claim_submitted",
            "wallet", "transaction", "contract_action",
            "agent_task", "agent_decision", "a2h_interaction",
            "agent_registered", "agent_updated", "agent_authorized", "agent_deauthorized",
            "agent_capability_granted", "agent_capability_revoked",
            "agent_task_created", "agent_task_decomposed", "agent_task_started",
            "agent_task_completed", "agent_task_failed", "agent_tool_called",
            "agent_resource_requested", "agent_delegated_task", "agent_subagent_spawned",
            "agent_policy_evaluated", "agent_handoff", "agent_escalated_to_human", "agent_outcome_recorded"
        ).sorted().joinToString(",")
        val bytes = MessageDigest.getInstance("SHA-256").digest(types.toByteArray())
        return bytes.joinToString("") { "%02x".format(it) }
    }

    private fun loadOrCreateSdkId(): String {
        val key = "aether_sdk_id"
        return prefs?.getString(key, null) ?: run {
            val id = UUID.randomUUID().toString()
            prefs?.edit()?.putString(key, id)?.apply()
            id
        }
    }
}
