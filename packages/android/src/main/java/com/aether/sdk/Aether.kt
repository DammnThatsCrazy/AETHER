// =============================================================================
// Aether SDK — Android (Kotlin)
// Core analytics, identity, session, consent, lifecycle tracking
// =============================================================================

package com.aether.sdk

import android.app.ActivityManager
import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.SystemClock
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
    val endpoint: String = "https://api.aether.io",
    val batchSize: Int = 10,
    val flushIntervalMs: Long = 5000L,
    val modules: ModuleConfig = ModuleConfig(),
    val privacy: PrivacyConfig = PrivacyConfig(),
    /**
     * Optional HMAC-SHA256 secret to verify the remote SDK manifest signature
     * before applying it (Truth Kernel §2.9). When set, unsigned/invalid
     * manifests are rejected and the last-known-good config is kept.
     */
    val manifestVerificationKey: String? = null,
    val autoResumeJourney: Boolean = true,
    val onJourneyResumed: ((resolvedAnonymousId: String, resolvedUserId: String?) -> Unit)? = null
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
    val experiments: Boolean = false
)

data class PrivacyConfig(
    val gdprMode: Boolean = false,
    val anonymizeIP: Boolean = true
)

data class CanonicalConsentReceiptInput(
    val tenantId: String,
    val subjectId: String? = null,
    val anonymousId: String? = null,
    val purposes: List<String>,
    val state: String,
    val source: String,
    val policyVersion: String,
    val provider: String? = null,
    val jurisdictionContext: String? = null,
    val mode: String? = null,
    val lawfulBasis: String? = null,
    val grantedAt: String? = null,
    val deniedAt: String? = null,
    val revokedAt: String? = null,
    val expiresAt: String? = null,
    val gpcObserved: Boolean? = null,
    val dntObserved: Boolean? = null,
    val providerConsentId: String? = null,
    val metadata: Map<String, Any?> = emptyMap(),
)

data class CanonicalConsentReceipt(
    val receiptId: String,
    val integrityHash: String,
    val idempotencyKey: String,
    val input: CanonicalConsentReceiptInput,
)

// =============================================================================
// IDENTITY
// =============================================================================

data class WalletEntry(
    val address: String,
    val vm: String = "evm",       // evm | svm | bitcoin | movevm | near | tvm | cosmos
    val walletType: String = "unknown",
    val chainId: String = "unknown",
)

data class IdentityData(
    val userId: String? = null,
    val email: String? = null,
    val walletAddress: String? = null,
    val walletType: String? = null,
    val chainId: Int? = null,
    val traits: Map<String, Any?> = emptyMap(),
    val wallets: List<WalletEntry> = emptyList(),
)

// =============================================================================
// BATCH HEALTH (Truth Kernel §2.8)
// =============================================================================

/**
 * Per-batch ingestion health counters. `accepted` / `duplicate` / `rejected`
 * are parsed from the backend BatchResponse (packages/shared/ingestion-contract.ts).
 * `droppedByConsent` and `queueDepth` are SDK-side truths: consent gating removes
 * events before they leave the device, and queueDepth reflects the local backlog
 * after send.
 */
data class BatchHealth(
    val accepted: Int,
    val duplicate: Int,
    val rejected: Int,
    val droppedByConsent: Int,
    val queueDepth: Int,
)

// =============================================================================
// MAIN SDK
// =============================================================================

object Aether : DefaultLifecycleObserver {
    private const val TAG = "AetherSDK"
    private const val VERSION = "8.12.0"
    private const val PREFS_NAME = "com.aether.sdk"

    private var config: AetherConfig? = null
    private var context: Context? = null
    private var prefs: SharedPreferences? = null

    private val eventQueue = ConcurrentLinkedQueue<JSONObject>()
    private var flushJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private const val MAX_QUEUE_SIZE = 1000
    private const val QUEUE_FORMAT_VERSION = 1
    private const val SESSION_TIMEOUT_MS = 30 * 60 * 1000L // 30 min

    private var healthAgent: AetherHealthAgent? = null

    /** Invoked after each processed batch with per-batch ingestion health (§2.8). */
    var onBatchResult: ((BatchHealth) -> Unit)? = null

    /** Consent-dropped events accumulated since the last batch send (§2.8). */
    private val pendingConsentDrops = java.util.concurrent.atomic.AtomicInteger(0)

    private var sessionId: String = UUID.randomUUID().toString()
    private var anonymousId: String = ""
    private var userId: String? = null
    private var email: String? = null
    private var walletAddress: String? = null
    private var traits: MutableMap<String, Any?> = mutableMapOf()
    private var screenCount = 0
    private var eventCount = 0
    // Monotonic per-session ordering index stamped as context.sequence.event
    // (web SDK wire parity); resets whenever sessionId rotates.
    private var eventSequence = 0
    private var isInitialized = false
    private var serverConfig: JSONObject = JSONObject()
    private var consentState: MutableList<String> = mutableListOf()
    private var fingerprintId: String = ""
    private var campaignContext: JSONObject? = null
    // Initialize the monotonic clock only when the Android runtime is available.
    // Loading the SDK object must remain safe in plain JVM unit tests.
    private var appStartTimeMs: Long = 0L
    private var foregroundStartMs: Long = 0L
    private var lastActivityMs: Long = 0L
    private var currentJourneyId: String? = null
    private var currentJourneyName: String? = null
    private val CLICK_ID_PARAMS = setOf(
        "gclid", "msclkid", "fbclid", "ttclid", "twclid",
        "li_fat_id", "rdt_cid", "scid", "dclid", "epik",
        "irclickid", "aff_id"
    )
    private val EVENT_CONSENT_PURPOSE = mapOf(
        "track" to "analytics", "page" to "analytics", "screen" to "analytics",
        "heartbeat" to "analytics", "error" to "analytics", "performance" to "analytics",
        "journey_started" to "analytics", "journey_paused" to "analytics",
        "journey_resumed" to "analytics", "journey_continued" to "analytics",
        "journey_completed" to "analytics", "journey_abandoned" to "analytics",
        "journey_checkpoint" to "analytics", "identify" to "analytics",
        "experiment" to "marketing", "conversion" to "marketing",
        "consent" to "analytics",
        "payment_initiated" to "commerce", "payment_completed" to "commerce",
        "payment_failed" to "commerce", "approval_requested" to "commerce",
        "approval_resolved" to "commerce", "entitlement_granted" to "commerce",
        "entitlement_revoked" to "commerce", "access_granted" to "commerce",
        "access_denied" to "commerce",
        // x402 — legacy + lifecycle
        "x402_payment" to "commerce",
        "x402_resource_requested" to "commerce", "x402_payment_required" to "commerce",
        "x402_quote_received" to "commerce", "x402_authorization_requested" to "commerce",
        "x402_authorization_resolved" to "commerce", "x402_payment_intent_created" to "commerce",
        "x402_payment_submitted" to "commerce", "x402_payment_settled" to "commerce",
        "x402_payment_failed" to "commerce", "x402_payment_timeout" to "commerce",
        "x402_receipt_verified" to "commerce", "x402_access_granted" to "commerce",
        "x402_access_denied" to "commerce", "x402_refund_or_reversal" to "commerce",
        // reward enablement (A6)
        "reward_action_queued" to "commerce", "reward_proof_generated" to "commerce",
        "reward_delivered" to "commerce", "reward_claim_submitted" to "commerce",
        "wallet" to "web3", "transaction" to "web3", "contract_action" to "web3",
        // Agent — legacy + lifecycle
        "agent_task" to "agent", "agent_decision" to "agent", "a2h_interaction" to "agent",
        "agent_registered" to "agent", "agent_updated" to "agent",
        "agent_authorized" to "agent", "agent_deauthorized" to "agent",
        "agent_capability_granted" to "agent", "agent_capability_revoked" to "agent",
        "agent_task_created" to "agent", "agent_task_decomposed" to "agent",
        "agent_task_started" to "agent", "agent_task_completed" to "agent",
        "agent_task_failed" to "agent", "agent_tool_called" to "agent",
        "agent_resource_requested" to "agent", "agent_delegated_task" to "agent",
        "agent_subagent_spawned" to "agent", "agent_policy_evaluated" to "agent",
        "agent_handoff" to "agent", "agent_escalated_to_human" to "agent",
        "agent_outcome_recorded" to "agent",
        // Agentic observability — account / MCP / tool
        "agentic_account_observed" to "agent", "agentic_account_connected_observed" to "agent",
        "agentic_account_disconnected_observed" to "agent", "agent_budget_observed" to "agent",
        "agent_budget_changed_observed" to "agent", "agent_permission_observed" to "agent",
        "agent_mcp_connection_observed" to "agent", "agent_tool_observed" to "agent",
        "agent_tool_invocation_observed" to "agent", "agent_activity_observed" to "agent",
        "agent_risk_signal_observed" to "agent", "agent_notification_observed" to "agent",
        // Agentic observability — Robinhood-style trading observation
        "agent_strategy_observed" to "agent", "agent_trade_intent_observed" to "agent",
        "agent_trade_order_observed" to "agent", "agent_trade_fill_observed" to "agent",
        "agent_trade_rejection_observed" to "agent", "agent_position_observed" to "agent",
        "agent_portfolio_snapshot_observed" to "agent", "agent_performance_snapshot_observed" to "agent",
        "agent_disconnect_observed" to "agent",
        // Agentic observability — AgentMail-style communication observation
        "agent_inbox_observed" to "agent", "agent_email_address_observed" to "agent",
        "agent_thread_observed" to "agent", "agent_message_received_observed" to "agent",
        "agent_message_sent_observed" to "agent", "agent_reply_observed" to "agent",
        "agent_attachment_observed" to "agent", "agent_attachment_parsed_observed" to "agent",
        "agent_otp_detected_observed" to "agent", "agent_invoice_detected_observed" to "agent",
        "agent_receipt_detected_observed" to "agent", "agent_calendar_intent_observed" to "agent",
        "agent_support_route_observed" to "agent", "agent_semantic_search_observed" to "agent",
        "agent_data_extraction_observed" to "agent",
        // x402 protocol observation family
        "x402_resource_request_observed" to "commerce", "x402_challenge_observed" to "commerce",
        "x402_payment_requirement_observed" to "commerce", "x402_signature_observed" to "commerce",
        "x402_verification_observed" to "commerce", "x402_settlement_observed" to "commerce",
        "x402_resource_access_observed" to "commerce", "x402_resource_access_denied_observed" to "commerce",
        "x402_failure_observed" to "commerce", "x402_replay_risk_observed" to "commerce",
        "x402_provider_observed" to "commerce",
        // Exposure family
        "content_impression" to "analytics", "recommendation_exposed" to "analytics",
        "offer_exposed" to "analytics", "feature_exposed" to "analytics",
        "search_result_exposed" to "analytics", "ad_exposed" to "marketing",
        "notification_presented" to "analytics", "decision_observed" to "analytics",
        // Outcome family
        "outcome_observed" to "analytics", "goal_achieved" to "analytics", "goal_failed" to "analytics",
        "recommendation_accepted" to "analytics", "recommendation_rejected" to "analytics",
        "feedback_submitted" to "analytics", "retention_observed" to "analytics",
        "churn_observed" to "analytics", "human_override_observed" to "analytics",
        // B2B family
        "organization_observed" to "analytics", "workspace_created" to "analytics", "workspace_updated" to "analytics",
        "member_invited" to "analytics", "member_joined" to "analytics", "member_removed" to "analytics",
        "role_changed" to "analytics", "seat_assigned" to "analytics", "seat_released" to "analytics",
        "integration_connected" to "analytics", "integration_disconnected" to "analytics",
        "service_account_created" to "analytics", "service_account_revoked" to "analytics",
        "api_key_created" to "analytics", "api_key_revoked" to "analytics",
        "project_created" to "analytics", "project_archived" to "analytics",
        "workflow_started" to "analytics", "workflow_completed" to "analytics", "workflow_failed" to "analytics",
        // Ecommerce extended family
        "cart_item_added" to "commerce", "cart_item_removed" to "commerce",
        "cart_updated" to "commerce", "checkout_step_completed" to "commerce",
        "order_completed" to "commerce", "order_cancelled" to "commerce",
        "order_refunded" to "commerce", "chargeback_observed" to "commerce",
        "subscription_started" to "commerce", "trial_started" to "commerce", "trial_converted" to "commerce",
        "subscription_renewed" to "commerce", "subscription_upgrade_observed" to "commerce",
        "subscription_downgrade_observed" to "commerce", "subscription_cancelled" to "commerce",
        "invoice_issued" to "commerce", "invoice_paid" to "commerce", "invoice_failed" to "commerce",
        "dunning_started" to "commerce", "dunning_resolved" to "commerce",
        // Friction family
        "dead_click_observed" to "analytics", "rage_click_observed" to "analytics",
        "scroll_depth_observed" to "analytics", "form_started" to "analytics",
        "form_field_interaction" to "analytics", "form_validation_failed" to "analytics",
        "form_submitted" to "analytics", "form_abandoned" to "analytics",
        "search_reformulated" to "analytics", "retry_observed" to "analytics",
        "journey_stalled" to "analytics", "backtrack_observed" to "analytics",
        // Interaction family
        "surface_entered" to "analytics", "surface_exited" to "analytics",
        "interaction_observed" to "analytics", "feature_started" to "analytics",
        "feature_completed" to "analytics", "feature_abandoned" to "analytics",
        "action_attempted" to "analytics", "action_succeeded" to "analytics",
        "action_failed" to "analytics", "action_cancelled" to "analytics",
        "active_interval_observed" to "analytics",
        // Server observation family
        "api_request_observed" to "analytics", "webhook_delivery_observed" to "analytics",
        "connector_sync_started" to "analytics", "connector_sync_completed" to "analytics",
        "connector_sync_failed" to "analytics", "job_started" to "analytics",
        "job_completed" to "analytics", "job_failed" to "analytics",
        "rate_limit_observed" to "analytics", "dependency_failure_observed" to "analytics",
        "export_completed" to "analytics",
        // Identity lifecycle family
        "signup_started" to "analytics", "signup_completed" to "analytics",
        "login_succeeded" to "analytics", "login_failed" to "analytics",
        "logout_observed" to "analytics", "sso_observed" to "analytics",
        "mfa_challenge_observed" to "analytics", "identity_verified" to "analytics",
        "alias_link_requested" to "analytics", "alias_link_confirmed" to "analytics",
        "alias_revoked" to "analytics", "account_recovery_started" to "analytics",
        "account_recovery_completed" to "analytics", "device_registered" to "analytics",
        "device_revoked" to "analytics",
        // Agent evaluation family
        "agent_evaluation_observed" to "agent", "agent_cost_observed" to "agent",
        "agent_grounding_observed" to "agent", "agent_guardrail_observed" to "agent",
        "agent_human_override_observed" to "agent", "ai_invocation_observed" to "agent",
        // Web3 lifecycle extensions
        "transaction_pending_observed" to "web3", "transaction_confirmed_observed" to "web3",
        "transaction_reverted_observed" to "web3", "transaction_reorged_observed" to "web3",
        "token_approval_observed" to "web3", "allowance_changed_observed" to "web3",
        "bridge_transfer_observed" to "web3", "settlement_finality_observed" to "web3",
        // Comms family
        "notification_delivered" to "analytics", "notification_clicked" to "analytics",
        "email_delivered" to "marketing", "email_opened" to "marketing",
        "email_clicked" to "marketing", "email_bounced" to "marketing",
        "email_queued" to "marketing", "email_processed" to "marketing",
        "email_sent" to "marketing", "email_deferred" to "marketing",
        "email_dropped" to "marketing", "email_replied" to "marketing",
        "email_spam_complaint" to "marketing", "email_suppressed" to "marketing",
        "message_replied_observed" to "analytics", "unsubscribe_observed" to "marketing",
        "support_case_created" to "analytics", "support_case_resolved" to "analytics",
        "support_case_escalated" to "analytics", "support_sla_breached" to "analytics",
        // Credit family (explicit opt-in)
        "credit_signal_observed" to "credit", "credit_account_observed" to "credit",
        "credit_decision_observed" to "credit",
        // Location family (explicit opt-in)
        "location_observed" to "location", "geofence_transition_observed" to "location",
        // Derivatives family (explicit financial_activity opt-in)
        "trading_account_connected" to "financial_activity", "trading_account_disconnected" to "financial_activity",
        "trading_account_authorized" to "financial_activity", "trading_account_deauthorized" to "financial_activity",
        "trading_agent_enabled" to "financial_activity", "trading_agent_disabled" to "financial_activity",
        "trade_intent_created" to "financial_activity", "trade_approval_requested" to "financial_activity",
        "trade_approval_resolved" to "financial_activity", "risk_policy_updated" to "financial_activity",
        "human_trade_override_recorded" to "financial_activity",
        // Stablecoin intelligence family (explicit opt-in)
        "stablecoin_transfer_observed" to "economic_observability", "stablecoin_payment_observed" to "economic_observability",
        "stablecoin_mint_observed" to "economic_observability", "stablecoin_burn_observed" to "economic_observability",
        "stablecoin_bridge_outbound_observed" to "economic_observability", "stablecoin_bridge_inbound_observed" to "economic_observability",
        "stablecoin_swap_observed" to "economic_observability", "stablecoin_x402_settlement_observed" to "economic_observability",
        "stablecoin_treasury_movement_observed" to "economic_observability", "stablecoin_payout_observed" to "economic_observability",
        "stablecoin_venue_deposit_observed" to "economic_observability", "stablecoin_venue_withdrawal_observed" to "economic_observability",
        "stablecoin_balance_snapshot_observed" to "economic_observability", "stablecoin_supply_snapshot_observed" to "economic_observability",
        "stablecoin_holder_concentration_observed" to "economic_observability", "stablecoin_valuation_observed" to "economic_observability",
        "stablecoin_depeg_detected" to "economic_observability", "stablecoin_depeg_resolved" to "economic_observability",
        "stablecoin_finality_confirmed" to "economic_observability", "stablecoin_reorg_detected" to "economic_observability",
        "stablecoin_observation_corrected" to "economic_observability", "stablecoin_reconciliation_run_completed" to "economic_observability",
        "stablecoin_reconciliation_variance_detected" to "economic_observability", "stablecoin_reconciliation_variance_resolved" to "economic_observability",
        "stablecoin_asset_registered" to "economic_observability", "stablecoin_deployment_registered" to "economic_observability",
        "stablecoin_support_asserted" to "economic_observability", "stablecoin_support_revoked" to "economic_observability",
        "stablecoin_flow_aggregate_materialized" to "economic_observability", "stablecoin_checkpoint_advanced" to "economic_observability",
        // Derivatives intelligence family (explicit opt-in)
        "derivatives_venue_registered" to "financial_activity", "derivatives_venue_deployment_registered" to "financial_activity",
        "derivatives_instrument_registered" to "financial_activity", "derivatives_market_registered" to "financial_activity",
        "derivatives_strategy_registered" to "financial_activity", "derivatives_strategy_version_registered" to "financial_activity",
        "derivatives_risk_policy_registered" to "financial_activity", "derivatives_account_linked" to "financial_activity",
        "derivatives_account_link_revoked" to "financial_activity", "derivatives_balance_snapshot_observed" to "financial_activity",
        "derivatives_collateral_change_observed" to "financial_activity", "derivatives_margin_snapshot_observed" to "financial_activity",
        "derivatives_order_observed" to "financial_activity", "derivatives_order_updated_observed" to "financial_activity",
        "derivatives_order_cancelled_observed" to "financial_activity", "derivatives_order_rejected_observed" to "financial_activity",
        "derivatives_order_expired_observed" to "financial_activity", "derivatives_fill_observed" to "financial_activity",
        "derivatives_fill_corrected" to "financial_activity", "derivatives_position_opened_observed" to "financial_activity",
        "derivatives_position_increased_observed" to "financial_activity", "derivatives_position_reduced_observed" to "financial_activity",
        "derivatives_position_closed_observed" to "financial_activity", "derivatives_position_liquidated_observed" to "financial_activity",
        "derivatives_position_adl_observed" to "financial_activity", "derivatives_position_settled_observed" to "financial_activity",
        "derivatives_position_corrected" to "financial_activity", "derivatives_funding_payment_observed" to "financial_activity",
        "derivatives_fee_observed" to "financial_activity", "derivatives_pnl_snapshot_materialized" to "financial_activity",
        "derivatives_exposure_snapshot_materialized" to "financial_activity", "derivatives_price_observation_recorded" to "financial_activity",
        "derivatives_market_status_changed" to "financial_activity", "derivatives_stream_gap_detected" to "financial_activity",
        "derivatives_stream_gap_recovered" to "financial_activity", "derivatives_stream_checkpoint_advanced" to "financial_activity",
        "derivatives_adapter_conformance_run" to "financial_activity", "derivatives_reconciliation_run_completed" to "financial_activity",
        "derivatives_reconciliation_variance_detected" to "financial_activity", "derivatives_reconciliation_variance_resolved" to "financial_activity",
        "derivatives_risk_threshold_breached" to "financial_activity",
        // Interoperability intelligence family (explicit opt-in)
        "interop_provider_registered" to "cross_chain_observability", "interop_gateway_registered" to "cross_chain_observability",
        "interop_path_registered" to "cross_chain_observability", "interop_application_registered" to "cross_chain_observability",
        "interop_verification_actor_registered" to "cross_chain_observability", "interop_message_discovered" to "cross_chain_observability",
        "interop_message_sent_observed" to "cross_chain_observability", "interop_message_source_confirmed" to "cross_chain_observability",
        "interop_message_verification_observed" to "cross_chain_observability", "interop_message_verified" to "cross_chain_observability",
        "interop_message_delivery_attempt_observed" to "cross_chain_observability", "interop_message_delivered" to "cross_chain_observability",
        "interop_message_executed_observed" to "cross_chain_observability", "interop_message_settled" to "cross_chain_observability",
        "interop_message_failed" to "cross_chain_observability", "interop_message_timeout" to "cross_chain_observability",
        "interop_message_expired" to "cross_chain_observability", "interop_message_cancelled" to "cross_chain_observability",
        "interop_message_refunded_observed" to "cross_chain_observability", "interop_message_recovered" to "cross_chain_observability",
        "interop_message_reorged" to "cross_chain_observability", "interop_message_corrected" to "cross_chain_observability",
        "interop_message_correlated" to "cross_chain_observability", "interop_intent_observed" to "cross_chain_observability",
        "interop_intent_fulfilled_observed" to "cross_chain_observability", "interop_asset_leg_locked_observed" to "cross_chain_observability",
        "interop_asset_leg_burned_observed" to "cross_chain_observability", "interop_asset_leg_minted_observed" to "cross_chain_observability",
        "interop_asset_leg_released_observed" to "cross_chain_observability", "interop_fee_observed" to "cross_chain_observability",
        "interop_security_policy_snapshot_recorded" to "cross_chain_observability", "interop_security_policy_changed" to "cross_chain_observability",
        "interop_verification_quorum_observed" to "cross_chain_observability", "interop_provider_checkpoint_advanced" to "cross_chain_observability",
        "interop_stream_gap_detected" to "cross_chain_observability", "interop_stream_gap_recovered" to "cross_chain_observability",
        "interop_reconciliation_run_completed" to "cross_chain_observability", "interop_reconciliation_variance_detected" to "cross_chain_observability",
        "interop_reconciliation_variance_resolved" to "cross_chain_observability"
    )
    private val CANONICAL_EVENT_TYPES = EVENT_CONSENT_PURPOSE.keys
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

        appStartTimeMs = SystemClock.elapsedRealtime()

        this.config = config
        this.context = application.applicationContext
        this.prefs = application.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        this.anonymousId = loadOrCreateAnonymousId()
        this.userId = prefs?.getString("userId", null)
        this.walletAddress = prefs?.getString("walletAddress", null)
        this.consentState = (prefs?.getStringSet("consentState", emptySet()) ?: emptySet()).toMutableList()
        this.sessionId = UUID.randomUUID().toString()
        this.eventSequence = 0

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

        loadPersistedQueue()

        // Health agent: fleet heartbeat + manifest fetch
        val hAgent = AetherHealthAgent(
            endpoint = config.endpoint,
            apiKey = config.apiKey,
            platform = "android",
            appVersion = try { application.packageManager.getPackageInfo(application.packageName, 0).versionName ?: "" } catch (_: Exception) { "" },
            prefs = prefs,
            manifestVerificationKey = config.manifestVerificationKey
        )
        hAgent.getDynamicState = {
            Triple(
                eventQueue.size,
                "analytics" in consentState,
                walletAddress != null
            )
        }
        healthAgent = hAgent
        if (config.privacy.gdprMode) {
            if ("analytics" in consentState) hAgent.start()
        } else {
            hAgent.start()
        }

        fetchConfig()
        emitSessionStart(application.applicationContext)

        if (config.autoResumeJourney) {
            scope.launch { resolveIdentity(walletAddress = walletAddress, userId = null, email = null) }
        }
    }

    fun track(event: String, properties: Map<String, Any?> = emptyMap()) {
        val props = mutableMapOf<String, Any?>("event" to event)
        props.putAll(properties)
        enqueueEvent("track", props)
    }

    /**
     * Canonical low-level observation API (Truth Kernel §2.6). Emits a
     * first-class backend event [type] directly. Semantics mirror the web SDK:
     *
     * - [type] must be a canonical registry event type; unknown types are a
     *   production-safe no-op (with a debug log), never a silent mislabel.
     * - Payloads asserting `execution_by_aether == true` are rejected — Aether
     *   observes, it never executes.
     * - Consent gating, sensitive-field scrubbing, batching, and the max
     *   queue-size bound all run on the shared [enqueueEvent] path.
     */
    fun observe(type: String, properties: Map<String, Any?> = emptyMap()) {
        if (!CANONICAL_EVENT_TYPES.contains(type)) {
            log("observe(): '$type' is not a canonical event type — ignored")
            return
        }
        if (properties["execution_by_aether"] == true) {
            log("observe(): event '$type' dropped — execution_by_aether must never be true")
            return
        }
        enqueueEvent(type, properties)
    }

    /** Current event-queue depth (Truth Kernel §2.6 queue-depth awareness). */
    fun queueDepth(): Int = eventQueue.size

    fun startJourney(nameOrType: String, properties: Map<String, Any?> = emptyMap()) {
        currentJourneyId = (properties["journeyId"] as? String) ?: UUID.randomUUID().toString()
        currentJourneyName = nameOrType
        enqueueEvent("journey_started", properties + mapOf("journeyId" to currentJourneyId, "journeyName" to nameOrType, "journeyType" to nameOrType, "journeyStatus" to "started"))
    }

    fun pauseJourney(reason: String? = null, properties: Map<String, Any?> = emptyMap()) {
        currentJourneyId ?: return
        enqueueEvent("journey_paused", properties + mapOf("journeyId" to currentJourneyId, "pauseReason" to (reason ?: ""), "journeyStatus" to "paused"))
    }

    fun resumeJourney(reason: String? = null, properties: Map<String, Any?> = emptyMap()) {
        if (currentJourneyId == null) currentJourneyId = (properties["journeyId"] as? String) ?: UUID.randomUUID().toString()
        enqueueEvent("journey_resumed", properties + mapOf("journeyId" to currentJourneyId, "resumeReason" to (reason ?: ""), "journeyStatus" to "resumed"))
    }

    fun continueJourney(stepIdOrName: String, properties: Map<String, Any?> = emptyMap()) {
        currentJourneyId ?: return
        enqueueEvent("journey_continued", properties + mapOf("journeyId" to currentJourneyId, "stepId" to stepIdOrName, "stepName" to stepIdOrName, "journeyStatus" to "continued"))
    }

    fun completeJourney(reason: String? = null, properties: Map<String, Any?> = emptyMap()) {
        currentJourneyId ?: return
        enqueueEvent("journey_completed", properties + mapOf("journeyId" to currentJourneyId, "completionReason" to (reason ?: ""), "journeyStatus" to "completed"))
        currentJourneyId = null
    }

    fun abandonJourney(reason: String? = null, properties: Map<String, Any?> = emptyMap()) {
        currentJourneyId ?: return
        enqueueEvent("journey_abandoned", properties + mapOf("journeyId" to currentJourneyId, "abandonmentReason" to (reason ?: ""), "journeyStatus" to "abandoned"))
        currentJourneyId = null
    }

    fun checkpointJourney(stepIdOrName: String, properties: Map<String, Any?> = emptyMap()) {
        currentJourneyId ?: return
        enqueueEvent("journey_checkpoint", properties + mapOf("journeyId" to currentJourneyId, "stepId" to stepIdOrName, "stepName" to stepIdOrName, "journeyStatus" to "checkpoint"))
    }

    fun getCurrentJourney(): Map<String, Any?>? = currentJourneyId?.let { mapOf("journeyId" to it, "journeyName" to currentJourneyName) }

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
        val priorUserId = userId
        val priorEmail = email
        data.userId?.let { userId = it }
        data.email?.let { email = it }
        traits.putAll(data.traits)
        data.walletAddress?.let {
            walletAddress = it
            prefs?.edit()?.putString("walletAddress", it)?.apply()
        }
        // Multi-wallet: connect each wallet as a proper wallet event
        for (w in data.wallets) {
            walletConnected(w.address, w.walletType, w.chainId)
        }

        val walletsJson = JSONArray().apply {
            for (w in data.wallets) {
                put(JSONObject().apply {
                    put("address", w.address); put("vm", w.vm)
                    put("walletType", w.walletType); put("chainId", w.chainId)
                })
            }
        }
        val props = mutableMapOf<String, Any?>(
            "userId" to (userId ?: ""),
            "traits" to traits,
            "walletAddress" to (data.walletAddress ?: ""),
            "walletsCount" to data.wallets.size,
            "wallets" to walletsJson.toString(),
        )
        enqueueEvent("identify", props)
        prefs?.edit()?.putString("userId", userId)?.apply()

        // Cross-device: fire resolve when userId or email just became known
        if (config?.autoResumeJourney == true) {
            val uidChanged = userId != null && userId != priorUserId
            val emailChanged = email != null && email != priorEmail
            if (uidChanged || emailChanged) {
                scope.launch { resolveIdentity(walletAddress = walletAddress, userId = userId, email = email) }
            }
        }
    }

    fun getAnonymousId(): String = anonymousId
    fun getUserId(): String? = userId
    fun getFingerprintId(): String = fingerprintId

    fun reset() {
        flush()
        flushJob?.cancel()
        userId = null
        walletAddress = null
        email = null
        traits.clear()
        consentState.clear()
        anonymousId = UUID.randomUUID().toString()
        sessionId = UUID.randomUUID().toString()
        eventSequence = 0
        prefs?.edit()
            ?.remove("userId")
            ?.remove("walletAddress")
            ?.remove("consentState")
            ?.putString("anonymousId", anonymousId)
            ?.apply()
        log("SDK reset")
    }

    fun flush() {
        scope.launch { sendBatch() }
    }

    // =========================================================================
    // DURABLE QUEUE PERSISTENCE
    // =========================================================================

    private fun queueFile() = context?.filesDir?.resolve("aether_event_queue.json")

    @Synchronized
    private fun persistQueue() {
        try {
            val file = queueFile() ?: return
            val items = eventQueue.toList().takeLast(MAX_QUEUE_SIZE)
            if (items.isEmpty()) {
                file.delete()
                return
            }
            val events = JSONArray()
            items.forEach { events.put(it) }
            val envelope = JSONObject().apply {
                put("version", QUEUE_FORMAT_VERSION)
                put("savedAt", dateFormat.format(Date()))
                put("events", events)
            }
            val temp = file.resolveSibling(file.name + ".tmp")
            temp.writeText(envelope.toString())
            if (!temp.renameTo(file)) {
                file.writeText(temp.readText())
                temp.delete()
            }
        } catch (error: Exception) {
            log("Failed to persist durable queue: " + error.javaClass.simpleName)
        }
    }

    private fun loadPersistedQueue() {
        val file = queueFile() ?: return
        if (!file.exists()) return
        try {
            val text = file.readText()
            val events = if (text.trimStart().startsWith("[")) {
                JSONArray(text) // v0 compatibility
            } else {
                val envelope = JSONObject(text)
                require(envelope.optInt("version", 0) == QUEUE_FORMAT_VERSION)
                envelope.getJSONArray("events")
            }
            val capacity = maxOf(0, MAX_QUEUE_SIZE - eventQueue.size)
            val count = minOf(events.length(), capacity)
            for (i in 0 until count) {
                val value = events.get(i)
                eventQueue.add(
                    if (value is JSONObject) value else JSONObject(value.toString())
                )
            }
            persistQueue()
            log("Restored $count events from durable queue")
        } catch (error: Exception) {
            val quarantine = file.resolveSibling(
                file.name + ".corrupt." + System.currentTimeMillis()
            )
            file.renameTo(quarantine)
            log("Quarantined corrupt durable queue: " + error.javaClass.simpleName)
        }
    }

    @Synchronized
    private fun requeueBatch(batch: List<JSONObject>) {
        val retained = (batch + eventQueue.toList()).take(MAX_QUEUE_SIZE)
        eventQueue.clear()
        retained.forEach { eventQueue.add(it) }
        persistQueue()
    }

    private fun clearPersistedQueue() { queueFile()?.delete() }

    fun handleDeepLink(url: String) {
        try {
            val uri = java.net.URI(url)
            val params = uri.query?.split("&")?.associate {
                val parts = it.split("=", limit = 2)
                parts[0] to (parts.getOrNull(1) ?: "")
            } ?: emptyMap()

            val attribution = mutableMapOf<String, Any?>("url" to url)
            val clickIds = JSONObject()
            params.forEach { (key, value) ->
                if (key.startsWith("utm_")) {
                    attribution[key] = value
                }
                if (key in CLICK_ID_PARAMS) {
                    clickIds.put(key, value)
                    attribution[key] = value
                }
            }

            // Store campaign context for inclusion in event context
            campaignContext = JSONObject().apply {
                put("source", params["utm_source"] ?: "")
                put("medium", params["utm_medium"] ?: "")
                put("campaign", params["utm_campaign"] ?: "")
                put("content", params["utm_content"] ?: "")
                put("term", params["utm_term"] ?: "")
                put("clickIds", clickIds)
                put("referrerDomain", uri.host ?: "")
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
        val normalized = normalizeWalletAddress(address)
        walletAddress = normalized
        prefs?.edit()?.putString("walletAddress", normalized)?.apply()
        enqueueEvent("wallet", mapOf(
            "action" to "connect", "address" to normalized,
            "walletType" to walletType, "chainId" to chainId
        ))
        if (config?.autoResumeJourney == true) {
            scope.launch { resolveIdentity(walletAddress = normalized, userId = userId, email = email) }
        }
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

    fun contractAction(contract: String, action: String, vm: String = "evm", properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("contract_action", properties + mapOf("contract" to contract, "action" to action, "vm" to vm))
    }

    // =========================================================================
    // GOOGLE PAY TRACKING
    // Call this from your PaymentsClient result callbacks with the payment status.
    // =========================================================================

    fun trackGooglePayPayment(
        status: String,
        amount: Double? = null,
        currency: String? = null,
        properties: Map<String, Any?> = emptyMap()
    ) {
        val props = mutableMapOf<String, Any?>(
            "action"   to status,
            "provider" to "google_pay"
        )
        amount?.let { props["amount"] = it }
        currency?.let { props["currency"] = it }
        props.putAll(properties)
        val eventType = when (status) {
            "completed" -> "payment_completed"
            "failed"    -> "payment_failed"
            else        -> "payment_initiated"
        }
        enqueueEvent(eventType, props)
    }

    // =========================================================================
    // WALLETCONNECT TRACKING
    // Call this after a WalletConnect v2 session is established or resumed.
    // =========================================================================

    fun trackWalletConnectSession(
        topic: String,
        address: String? = null,
        chainId: String? = null,
        properties: Map<String, Any?> = emptyMap()
    ) {
        val props = mutableMapOf<String, Any?>(
            "action"   to "walletconnect_session",
            "topic"    to topic,
            "provider" to "walletconnect"
        )
        address?.let { props["address"] = normalizeWalletAddress(it) }
        chainId?.let { props["chainId"] = it }
        props.putAll(properties)
        if (address != null) {
            walletConnected(address, "walletconnect", chainId ?: "unknown")
        } else {
            enqueueEvent("wallet", props)
        }
    }

    // =========================================================================
    // WALLET CAPABILITY API
    // Returns which wallet/payment capabilities are active for this session.
    // =========================================================================

    fun getWalletCapabilities(): Map<String, Any?> = mapOf(
        "connected"    to (walletAddress != null),
        "addresses"    to listOfNotNull(walletAddress?.let {
            mapOf("address" to it, "vm" to "evm", "walletType" to "unknown")
        }),
        "supportedVMs" to listOf("evm", "svm", "bitcoin", "movevm", "near", "tvm", "cosmos"),
        "googlePay"    to false,
        "applePay"     to false,
    )

    // =========================================================================
    // CONSENT MANAGEMENT
    //
    // Canonical purposes (see packages/shared/consent.ts):
    //   "analytics", "marketing", "web3", "agent", "commerce"
    // Callers SHOULD only pass these strings. Backend validator ignores others.
    // =========================================================================

    val canonicalConsentPurposes: List<String> =
        listOf("analytics", "marketing", "personalization", "web3", "agent", "commerce", "credit", "location")

    /** Purposes that always require explicit opt-in and are never granted by grantAll(). */
    val explicitOptInPurposes: List<String> = listOf("credit", "location")

    /**
     * Extended opt-in purposes used by the event gating map beyond the canonical
     * set; stamped into per-event context.consent for web ConsentState parity.
     */
    private val extendedConsentPurposes: List<String> =
        listOf("financial_activity", "economic_observability", "cross_chain_observability")

    fun grantConsent(categories: List<String>) {
        consentState.addAll(categories)
        consentState = consentState.distinct().toMutableList()
        prefs?.edit()?.putStringSet("consentState", consentState.toSet())?.apply()
        enqueueEvent("consent", mapOf("action" to "grant", "categories" to categories))
        // Start health agent when analytics consent is granted in GDPR mode (post-init opt-in flow)
        if (config?.privacy?.gdprMode == true && "analytics" in categories) {
            healthAgent?.start()
        }
    }

    /**
     * Grant all non-explicit-opt-in purposes (excludes credit and location).
     * Call grantConsent(listOf("credit")) or grantConsent(listOf("location")) explicitly
     * to grant those purposes after displaying required consent UI.
     */
    fun grantAll() {
        grantConsent(canonicalConsentPurposes.filter { it !in explicitOptInPurposes })
    }

    fun revokeConsent(categories: List<String>) {
        consentState.removeAll(categories.toSet())
        prefs?.edit()?.putStringSet("consentState", consentState.toSet())?.apply()
        enqueueEvent("consent", mapOf("action" to "revoke", "categories" to categories))
    }

    fun getConsentState(): List<String> = consentState.toList()

    /**
     * Build and persist an authoritative consent receipt. The tenant ID must
     * match the tenant resolved from the configured API key.
     */
    fun buildCanonicalConsentReceipt(input: CanonicalConsentReceiptInput): CanonicalConsentReceipt {
        require(input.tenantId.isNotBlank()) { "tenantId is required" }
        require(!input.subjectId.isNullOrBlank() || !input.anonymousId.isNullOrBlank()) {
            "subjectId or anonymousId is required"
        }
        require(input.purposes.isNotEmpty()) { "at least one purpose is required" }
        val normalized = input.copy(purposes = input.purposes.distinct().sorted())
        val digest = sha256Canonical(canonicalConsentReceiptPreimage(normalized))
        return CanonicalConsentReceipt(
            receiptId = "ccr_${digest.take(32)}",
            integrityHash = "sha256:$digest",
            idempotencyKey = "consent-receipt:$digest",
            input = normalized,
        )
    }

    suspend fun recordConsentReceipt(input: CanonicalConsentReceiptInput): CanonicalConsentReceipt {
        val cfg = config ?: throw IllegalStateException("Aether SDK is not initialized")
        val receipt = buildCanonicalConsentReceipt(input)
        withContext(Dispatchers.IO) {
            val connection = URL("${cfg.endpoint.trimEnd('/')}/v1/consent/records")
                .openConnection() as HttpURLConnection
            try {
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setRequestProperty("Authorization", "Bearer ${cfg.apiKey}")
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use {
                    it.write(consentReceiptRequestJson(receipt).toString().toByteArray(Charsets.UTF_8))
                }
                if (connection.responseCode !in 200..299) {
                    throw IllegalStateException("Consent receipt request failed (${connection.responseCode})")
                }
            } finally {
                connection.disconnect()
            }
        }
        return receipt
    }

    // =========================================================================
    // ECOMMERCE TRACKING
    // =========================================================================

    fun trackProductView(product: Map<String, Any>) {
        enqueueEvent("track", mapOf("event" to "product_viewed", "product" to product))
    }

    fun trackAddToCart(item: Map<String, Any>) {
        enqueueEvent("track", mapOf("event" to "cart_item_added", "item" to item))
    }

    fun trackPurchase(orderId: String, total: Double, currency: String = "USD", items: List<Map<String, Any>>? = null) {
        val props = mutableMapOf<String, Any>(
            "event" to "order_completed", "orderId" to orderId,
            "total" to total, "currency" to currency
        )
        items?.let { props["items"] = it }
        enqueueEvent("conversion", props)
    }

    fun paymentInitiated(paymentId: String, amount: Double, currency: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("payment_initiated", properties + mapOf("paymentId" to paymentId, "amount" to amount, "currency" to currency))
    }

    fun paymentCompleted(paymentId: String, amount: Double, currency: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("payment_completed", properties + mapOf("paymentId" to paymentId, "amount" to amount, "currency" to currency))
    }

    fun paymentFailed(paymentId: String, reason: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("payment_failed", properties + mapOf("paymentId" to paymentId, "reason" to reason))
    }

    fun approvalRequested(approvalId: String, scope: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("approval_requested", properties + mapOf("approvalId" to approvalId, "scope" to scope))
    }

    fun approvalResolved(approvalId: String, approved: Boolean, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("approval_resolved", properties + mapOf("approvalId" to approvalId, "approved" to approved))
    }

    fun entitlementGranted(entitlementId: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("entitlement_granted", properties + mapOf("entitlementId" to entitlementId))
    }

    fun entitlementRevoked(entitlementId: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("entitlement_revoked", properties + mapOf("entitlementId" to entitlementId))
    }

    fun accessGranted(resource: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("access_granted", properties + mapOf("resource" to resource))
    }

    fun accessDenied(resource: String, reason: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("access_denied", properties + mapOf("resource" to resource, "reason" to reason))
    }

    fun agentTask(taskId: String, actorId: String, actorKind: String = "agent", properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("agent_task", properties + mapOf("taskId" to taskId, "actorId" to actorId, "actorKind" to actorKind))
    }

    fun agentDecision(decisionId: String, actorId: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("agent_decision", properties + mapOf("decisionId" to decisionId, "actorId" to actorId))
    }

    fun a2hInteraction(interactionId: String, actorId: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("a2h_interaction", properties + mapOf("interactionId" to interactionId, "actorId" to actorId))
    }

    fun x402Payment(paymentId: String, amount: String, currency: String, network: String, properties: Map<String, Any?> = emptyMap()) {
        enqueueEvent("x402_payment", properties + mapOf("paymentId" to paymentId, "amount" to amount, "currency" to currency, "network" to network))
    }

    // Agent Lifecycle (Granular)
    fun agentRegistered(agentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_registered", properties + mapOf("agentId" to agentId))
    fun agentUpdated(agentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_updated", properties + mapOf("agentId" to agentId))
    fun agentAuthorized(agentId: String, delegationId: String? = null, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_authorized", properties + mapOf("agentId" to agentId, "delegationId" to delegationId))
    fun agentDeauthorized(agentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_deauthorized", properties + mapOf("agentId" to agentId))
    fun agentCapabilityGranted(agentId: String, capability: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_capability_granted", properties + mapOf("agentId" to agentId, "capability" to capability))
    fun agentCapabilityRevoked(agentId: String, capability: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_capability_revoked", properties + mapOf("agentId" to agentId, "capability" to capability))
    fun agentTaskCreated(taskId: String, actorId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_task_created", properties + mapOf("taskId" to taskId, "actorId" to actorId))
    fun agentTaskDecomposed(taskId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_task_decomposed", properties + mapOf("taskId" to taskId))
    fun agentTaskStarted(taskId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_task_started", properties + mapOf("taskId" to taskId))
    fun agentTaskCompleted(taskId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_task_completed", properties + mapOf("taskId" to taskId))
    fun agentTaskFailed(taskId: String, reason: String? = null, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_task_failed", properties + mapOf("taskId" to taskId, "reason" to reason))
    fun agentToolCalled(taskId: String, tool: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_tool_called", properties + mapOf("taskId" to taskId, "tool" to tool))
    fun agentResourceRequested(resourceId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_resource_requested", properties + mapOf("resourceId" to resourceId))
    fun agentDelegatedTask(taskId: String, toAgentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_delegated_task", properties + mapOf("taskId" to taskId, "toAgentId" to toAgentId))
    fun agentSubagentSpawned(parentId: String, childId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_subagent_spawned", properties + mapOf("parentId" to parentId, "childId" to childId))
    fun agentPolicyEvaluated(policyId: String, outcome: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_policy_evaluated", properties + mapOf("policyId" to policyId, "outcome" to outcome))
    fun agentHandoff(fromId: String, toId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_handoff", properties + mapOf("fromId" to fromId, "toId" to toId))
    fun agentEscalatedToHuman(taskId: String, reason: String? = null, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_escalated_to_human", properties + mapOf("taskId" to taskId, "reason" to reason))
    fun agentOutcomeRecorded(taskId: String, outcome: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("agent_outcome_recorded", properties + mapOf("taskId" to taskId, "outcome" to outcome))

    // x402 Lifecycle (Granular)
    fun x402ResourceRequested(resourceId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_resource_requested", properties + mapOf("resourceId" to resourceId))
    fun x402PaymentRequired(resourceId: String, amount: Double, currency: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_payment_required", properties + mapOf("resourceId" to resourceId, "amount" to amount, "currency" to currency))
    fun x402QuoteReceived(quoteId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_quote_received", properties + mapOf("quoteId" to quoteId))
    fun x402AuthorizationRequested(paymentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_authorization_requested", properties + mapOf("paymentId" to paymentId))
    fun x402AuthorizationResolved(paymentId: String, authorized: Boolean, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_authorization_resolved", properties + mapOf("paymentId" to paymentId, "authorized" to authorized))
    fun x402PaymentIntentCreated(intentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_payment_intent_created", properties + mapOf("intentId" to intentId))
    fun x402PaymentSubmitted(paymentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_payment_submitted", properties + mapOf("paymentId" to paymentId))
    fun x402PaymentSettled(paymentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_payment_settled", properties + mapOf("paymentId" to paymentId))
    fun x402PaymentFailed(paymentId: String, reason: String? = null, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_payment_failed", properties + mapOf("paymentId" to paymentId, "reason" to reason))
    fun x402PaymentTimeout(paymentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_payment_timeout", properties + mapOf("paymentId" to paymentId))
    fun x402ReceiptVerified(receiptId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_receipt_verified", properties + mapOf("receiptId" to receiptId))
    fun x402AccessGranted(resourceId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_access_granted", properties + mapOf("resourceId" to resourceId))
    fun x402AccessDenied(resourceId: String, reason: String? = null, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_access_denied", properties + mapOf("resourceId" to resourceId, "reason" to reason))
    fun x402RefundOrReversal(paymentId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("x402_refund_or_reversal", properties + mapOf("paymentId" to paymentId))

    // Rewards (Thin Observation Emitters)
    fun rewardActionQueued(campaignId: String, ruleId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("reward_action_queued", properties + mapOf("campaignId" to campaignId, "ruleId" to ruleId))
    fun rewardProofGenerated(campaignId: String, proofId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("reward_proof_generated", properties + mapOf("campaignId" to campaignId, "proofId" to proofId))
    fun rewardDelivered(campaignId: String, rewardId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("reward_delivered", properties + mapOf("campaignId" to campaignId, "rewardId" to rewardId))
    fun rewardClaimSubmitted(campaignId: String, claimId: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("reward_claim_submitted", properties + mapOf("campaignId" to campaignId, "claimId" to claimId))

    // Ecommerce Additions
    fun trackRemoveFromCart(item: Map<String, Any?>) = enqueueEvent("track", item + mapOf("event" to "cart_item_removed"))
    fun trackApplyCoupon(couponCode: String, properties: Map<String, Any?> = emptyMap()) = enqueueEvent("track", properties + mapOf("event" to "coupon_applied", "couponCode" to couponCode))
    fun trackBeginCheckout(cartValue: Double, currency: String = "USD", properties: Map<String, Any?> = emptyMap()) = enqueueEvent("conversion", properties + mapOf("event" to "checkout_started", "cartValue" to cartValue, "currency" to currency))

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
        val now = SystemClock.elapsedRealtime()
        if (lastActivityMs == 0L || (now - lastActivityMs) > SESSION_TIMEOUT_MS) {
            sessionId = UUID.randomUUID().toString()
            eventSequence = 0
        }
        foregroundStartMs = now
        lastActivityMs = now
        track("app_foreground", mapOf("networkType" to getNetworkType()))
        continueJourney("app_foreground", mapOf("resumeReason" to "process_start"))
    }

    override fun onStop(owner: LifecycleOwner) {
        persistQueue()
        val now = SystemClock.elapsedRealtime()
        lastActivityMs = now
        val sessionDurationMs = if (foregroundStartMs > 0) now - foregroundStartMs else 0L
        track("app_background", mapOf("sessionDurationMs" to sessionDurationMs))
        pauseJourney("process_stop", mapOf("sessionDurationMs" to sessionDurationMs))
        flush()
    }

    // =========================================================================
    // PRIVATE
    // =========================================================================

    private fun enqueueEvent(type: String, properties: Map<String, Any?>) {
        if (!isInitialized) return
        if (!CANONICAL_EVENT_TYPES.contains(type)) {
            log("Dropping non-canonical event type: $type. Use track(eventName, properties) for custom events.")
            return
        }
        val purpose = EVENT_CONSENT_PURPOSE[type]
        val gdprMode = config?.privacy?.gdprMode ?: false
        if (type != "consent" && gdprMode && (purpose == null || !consentState.contains(purpose))) {
            log("Dropping $type before enqueue because $purpose consent is not granted")
            // Consent gating is intentional, not a delivery failure — it is
            // surfaced as the BatchHealth.droppedByConsent counter (§2.8).
            pendingConsentDrops.incrementAndGet()
            healthAgent?.recordDroppedEvents(1)
            return
        }

        val scrubbed = scrubSensitiveFields(properties)
        // Single occurrence instant shared by the timestamp and the temporal
        // provenance so zone/offset evidence matches the stamped clock reading.
        val eventDate = Date()
        val event = JSONObject().apply {
            put("id", UUID.randomUUID().toString())
            put("type", type)
            put("timestamp", dateFormat.format(eventDate))
            put("sessionId", sessionId)
            put("anonymousId", anonymousId)
            put("userId", userId ?: JSONObject.NULL)
            put("properties", JSONObject(scrubbed.mapValues { it.value ?: JSONObject.NULL }))
            put("context", buildContext(eventDate))
        }

        // Enforce max queue size to prevent OOM under prolonged offline
        while (eventQueue.size >= MAX_QUEUE_SIZE) { eventQueue.poll() }
        eventQueue.add(event)
        eventCount++
        eventSequence++
        persistQueue()

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
        persistQueue()

        sendBatchWithRetry(batch, cfg, retryCount = 0)
    }

    private suspend fun sendBatchWithRetry(
        batch: List<JSONObject>,
        cfg: AetherConfig,
        retryCount: Int,
    ): Unit = withContext(Dispatchers.IO) {
        val maxRetries = 3
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

            val sendStart = System.currentTimeMillis()
            connection.outputStream.use { it.write(payload.toString().toByteArray()) }
            val responseCode = connection.responseCode
            val latencyMs = (System.currentTimeMillis() - sendStart).toDouble()
            // Read the body on success (before disconnect) so per-batch health
            // counters can be parsed from the BatchResponse (§2.8).
            val responseBody = if (responseCode in 200..299) {
                try { connection.inputStream.bufferedReader().readText() } catch (_: Exception) { "" }
            } else ""
            connection.disconnect()

            when {
                responseCode in 200..299 -> {
                    healthAgent?.recordBatchAttempt(true, latencyMs)
                    persistQueue()
                    emitBatchHealth(batch.size, responseBody)
                }
                responseCode == 429 -> {
                    val retryAfterSec = connection.getHeaderField("Retry-After")?.toLongOrNull() ?: 5L
                    if (retryCount < maxRetries) {
                        healthAgent?.recordRetry()
                        delay(retryAfterSec * 1000)
                        sendBatchWithRetry(batch, cfg, retryCount + 1)
                    } else {
                        healthAgent?.recordBatchAttempt(false, latencyMs)
                        requeueBatch(batch)
                        log("Batch retained after $maxRetries retries (rate limited)")
                    }
                }
                // 408 / 425 are transient like 5xx — the request can be safely re-sent.
                responseCode == 408 || responseCode == 425 || responseCode >= 500 -> {
                    if (retryCount < maxRetries) {
                        healthAgent?.recordRetry()
                        val backoff = minOf(1000L * (1L shl retryCount), 30000L)
                        delay(backoff)
                        sendBatchWithRetry(batch, cfg, retryCount + 1)
                    } else {
                        healthAgent?.recordBatchAttempt(false, latencyMs)
                        requeueBatch(batch)
                        log("Batch retained after $maxRetries retries (retryable error $responseCode)")
                    }
                }
                responseCode >= 400 -> {
                    healthAgent?.recordBatchAttempt(false, latencyMs)
                    healthAgent?.recordDroppedEvents(batch.size)
                    persistQueue()
                    log("Batch rejected (client error $responseCode) — not retrying")
                }
            }
        } catch (e: Exception) {
            log("Batch send failed: ${e.message}")
            if (retryCount < maxRetries) {
                healthAgent?.recordRetry()
                val backoff = minOf(1000L * (1L shl retryCount), 30000L)
                delay(backoff)
                sendBatchWithRetry(batch, cfg, retryCount + 1)
            } else {
                healthAgent?.recordBatchAttempt(false, 0.0)
                healthAgent?.recordDroppedEvents(batch.size)
                // Permanent transport failure — retain for a later flush cycle.
                requeueBatch(batch)
            }
        }
    }

    /**
     * Parse per-batch acceptance counters from the /v1/batch response body and
     * surface a [BatchHealth] via [onBatchResult] (Truth Kernel §2.8). The backend
     * BatchResponse uses `accepted` / `duplicates` / `rejected`; the singular
     * `duplicate` is also accepted. Falls back to treating the whole batch as
     * accepted when the body is absent or unparseable.
     */
    private fun emitBatchHealth(sentCount: Int, responseBody: String) {
        val cb = onBatchResult ?: return
        var accepted = sentCount
        var duplicate = 0
        var rejected = 0
        if (responseBody.isNotEmpty()) {
            try {
                val json = JSONObject(responseBody)
                if (json.has("accepted")) accepted = json.optInt("accepted", sentCount)
                duplicate = when {
                    json.has("duplicate") -> json.optInt("duplicate", 0)
                    json.has("duplicates") -> json.optInt("duplicates", 0)
                    else -> 0
                }
                rejected = json.optInt("rejected", 0)
            } catch (_: Exception) { /* keep optimistic defaults */ }
        }
        val health = BatchHealth(
            accepted = accepted,
            duplicate = duplicate,
            rejected = rejected,
            droppedByConsent = pendingConsentDrops.getAndSet(0),
            queueDepth = eventQueue.size,
        )
        cb(health)
    }

    private fun fetchConfig() {
        val endpoint = config?.endpoint ?: return
        scope.launch(Dispatchers.IO) {
            try {
                val url = URL("$endpoint/v1/config/sdk/manifest")
                val conn = url.openConnection() as HttpURLConnection
                conn.setRequestProperty("Authorization", "Bearer ${config?.apiKey ?: ""}")
                conn.connectTimeout = 5000
                conn.readTimeout = 5000
                val response = conn.inputStream.bufferedReader().readText()
                serverConfig = JSONObject(response)
                if (config?.debug == true) log("Config loaded")
                conn.disconnect()
            } catch (_: Exception) { }
        }
    }

    private fun buildContext(eventDate: Date): JSONObject = JSONObject().apply {
        put("os", JSONObject().apply {
            put("name", "Android")
            put("version", Build.VERSION.RELEASE)
            put("sdkInt", Build.VERSION.SDK_INT)
        })
        put("device", JSONObject().apply {
            put("manufacturer", Build.MANUFACTURER)
            put("model", Build.MODEL)
        })
        put("locale", Locale.getDefault().toLanguageTag())
        put("timezone", TimeZone.getDefault().id)
        // Temporal provenance at the event's occurrence instant (offset is
        // zone-at-instant, so DST transitions are captured correctly).
        put("utcOffsetMinutes", TimeZone.getDefault().getOffset(eventDate.time) / 60000)
        put("timeZoneSource", "device")
        put("clockSource", "device")
        put("network", JSONObject().apply {
            put("type", getNetworkType())
        })
        put("library", JSONObject().apply {
            put("name", "aether-android")
            put("version", VERSION)
        })
        // fingerprint omitted in GDPR mode until analytics consent is granted
        if (config?.privacy?.gdprMode != true || "analytics" in consentState) {
            put("fingerprint", JSONObject().apply {
                put("id", fingerprintId)
            })
        }
        campaignContext?.let { put("campaign", it) }
        // Active journey snapshot on every event (web SDK context.journey parity);
        // journeyName doubles as journeyType, exactly as startJourney stamps them.
        currentJourneyId?.let { journeyId ->
            put("journey", JSONObject().apply {
                put("journeyId", journeyId)
                currentJourneyName?.let { put("journeyName", it); put("journeyType", it) }
            })
        }
        put("consent", JSONObject().apply {
            val granted = consentState.toSet()
            canonicalConsentPurposes.forEach { put(it, it in granted) }
            extendedConsentPurposes.forEach { put(it, it in granted) }
        })
        // Monotonic ordering counter for gap/reorder detection at ingest.
        put("sequence", JSONObject().apply {
            put("event", eventSequence)
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
                scope.launch { sendBatch() }
            } catch (_: Exception) {}
            defaultHandler?.uncaughtException(thread, throwable)
        }
    }

    private fun emitSessionStart(ctx: Context) {
        val memInfo = ActivityManager.MemoryInfo()
        (ctx.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager)?.getMemoryInfo(memInfo)
        val startupMs = SystemClock.elapsedRealtime() - appStartTimeMs

        enqueueEvent("track", mapOf(
            "event" to "session_start",
            "startupTimeMs"       to startupMs,
            "totalMemoryMB"       to (memInfo.totalMem / 1048576L),
            "availableMemoryMB"   to (memInfo.availMem / 1048576L),
            "lowMemory"           to memInfo.lowMemory,
            "networkType"         to getNetworkType(),
            "osVersion"           to Build.VERSION.RELEASE,
            "sdkInt"              to Build.VERSION.SDK_INT,
            "device"              to "${Build.MANUFACTURER} ${Build.MODEL}",
        ))
    }

    private fun getNetworkType(): String {
        val cm = context?.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return "unknown"
        val nc = cm.getNetworkCapabilities(cm.activeNetwork) ?: return "none"
        return when {
            nc.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)     -> "wifi"
            nc.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            nc.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "other"
        }
    }

    private fun sha256(input: String): String {
        val bytes = java.security.MessageDigest.getInstance("SHA-256")
            .digest(input.lowercase().trim().toByteArray())
        return bytes.joinToString("") { "%02x".format(it) }
    }

    private val canonicalConsentReceiptHashFields = listOf(
        "tenant_id", "subject_id", "anonymous_id", "purposes", "state", "source",
        "provider", "policy_version", "jurisdiction_context", "mode", "lawful_basis",
        "granted_at", "denied_at", "revoked_at", "expires_at", "gpc_observed",
        "dnt_observed", "provider_consent_id", "metadata",
    )

    private fun sha256Canonical(input: String): String =
        java.security.MessageDigest.getInstance("SHA-256")
            .digest(input.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }

    private fun canonicalConsentReceiptValues(input: CanonicalConsentReceiptInput): Map<String, Any?> = mapOf(
        "tenant_id" to input.tenantId,
        "subject_id" to input.subjectId,
        "anonymous_id" to input.anonymousId,
        "purposes" to input.purposes,
        "state" to input.state,
        "source" to input.source,
        "provider" to input.provider,
        "policy_version" to input.policyVersion,
        "jurisdiction_context" to input.jurisdictionContext,
        "mode" to input.mode,
        "lawful_basis" to input.lawfulBasis,
        "granted_at" to input.grantedAt,
        "denied_at" to input.deniedAt,
        "revoked_at" to input.revokedAt,
        "expires_at" to input.expiresAt,
        "gpc_observed" to input.gpcObserved,
        "dnt_observed" to input.dntObserved,
        "provider_consent_id" to input.providerConsentId,
        "metadata" to input.metadata,
    )

    private fun canonicalConsentReceiptPreimage(input: CanonicalConsentReceiptInput): String {
        val values = canonicalConsentReceiptValues(input)
        return buildString {
            append("aether-consent-receipt/v1\n")
            canonicalConsentReceiptHashFields.forEach { field ->
                val value = canonicalConsentHashValue(values[field])
                append(field).append('=').append(value.toByteArray(Charsets.UTF_8).size)
                    .append(':').append(value).append('\n')
            }
        }
    }

    private fun canonicalConsentHashValue(value: Any?): String = when (value) {
        null -> ""
        is Boolean -> value.toString()
        is Collection<*> -> value.map { it?.toString() ?: "null" }
            .distinct().sorted().joinToString("\u001f")
        is Map<*, *> -> if (value.isEmpty()) "" else canonicalJson(value)
        else -> value.toString()
    }

    private fun canonicalJson(value: Any?): String = when (value) {
        null -> "null"
        is String -> JSONObject.quote(value)
        is Number, is Boolean -> value.toString()
        is Collection<*> -> value.joinToString(prefix = "[", postfix = "]") { canonicalJson(it) }
        is Map<*, *> -> value.entries.sortedBy { it.key.toString() }.joinToString(
            prefix = "{", postfix = "}",
        ) { (key, item) -> "${JSONObject.quote(key.toString())}:${canonicalJson(item)}" }
        else -> JSONObject.quote(value.toString())
    }

    private fun canonicalConsentReceiptJson(receipt: CanonicalConsentReceipt): JSONObject {
        val json = JSONObject()
        canonicalConsentReceiptValues(receipt.input).forEach { (key, value) ->
            json.put(key, if (value == null) JSONObject.NULL else JSONObject.wrap(value))
        }
        json.put("receipt_id", receipt.receiptId)
        json.put("integrity_hash", receipt.integrityHash)
        json.put("idempotency_key", receipt.idempotencyKey)
        return json
    }

    private fun consentReceiptRequestJson(receipt: CanonicalConsentReceipt): JSONObject =
        JSONObject().apply {
            put("user_id", receipt.input.subjectId)
            put("subject_id", receipt.input.subjectId)
            put("anonymous_id", receipt.input.anonymousId)
            put("purposes", JSONArray(receipt.input.purposes))
            put("granted", receipt.input.state == "granted")
            put("source", receipt.input.source)
            put("mode", receipt.input.mode)
            put("jurisdiction", receipt.input.jurisdictionContext)
            put("gpc_observed", receipt.input.gpcObserved)
            put("dnt_observed", receipt.input.dntObserved)
            put("idempotency_key", receipt.idempotencyKey)
            put("canonical_receipt", canonicalConsentReceiptJson(receipt))
        }

    private suspend fun resolveIdentity(walletAddress: String?, userId: String?, email: String?) = withContext(Dispatchers.IO) {
        val cfg = config ?: return@withContext
        try {
            val url = URL("${cfg.endpoint}/sdk/identity/resolve")
            val connection = url.openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("x-api-key", cfg.apiKey)
            connection.doOutput = true
            connection.connectTimeout = 5000
            connection.readTimeout = 5000

            val wallets = JSONArray()
            if (!walletAddress.isNullOrEmpty()) {
                wallets.put(JSONObject().apply { put("address", walletAddress); put("vm", "evm") })
            }
            val body = JSONObject().apply {
                put("wallets", wallets)
                put("anonymous_id", anonymousId)
                put("device_fingerprint", fingerprintId)
                put("platform", "android")
                if (userId != null) put("user_id", userId)
                if (!email.isNullOrBlank()) put("email_hash", sha256(email))
                // fingerprint_signals omitted in GDPR mode until analytics consent is granted
                if (config?.privacy?.gdprMode != true || "analytics" in consentState) {
                    put("fingerprint_signals", org.json.JSONObject().apply {
                        put("android_id", android.provider.Settings.Secure.getString(context?.contentResolver, android.provider.Settings.Secure.ANDROID_ID) ?: "")
                        put("model", android.os.Build.MODEL)
                        put("manufacturer", android.os.Build.MANUFACTURER)
                        put("os_version", android.os.Build.VERSION.RELEASE)
                        put("locale", java.util.Locale.getDefault().toString())
                        put("timezone", java.util.TimeZone.getDefault().id)
                    })
                }
            }

            connection.outputStream.use { it.write(body.toString().toByteArray()) }

            if (connection.responseCode != 200) { connection.disconnect(); return@withContext }

            val response = JSONObject(connection.inputStream.bufferedReader().readText())
            connection.disconnect()

            if (!response.optBoolean("resolved")) return@withContext

            val identity = response.optJSONObject("identity") ?: return@withContext
            val resolvedAnonymousId = identity.optString("anonymous_id")
            val resolvedUserId = identity.optString("user_id").takeIf { it.isNotEmpty() }

            if (resolvedAnonymousId.isEmpty() || resolvedAnonymousId == anonymousId) return@withContext

            resolvedUserId?.let { uid -> this@Aether.userId = uid; prefs?.edit()?.putString("userId", uid)?.apply() }
            enqueueEvent("journey_resumed", mapOf(
                "resolvedAnonymousId" to resolvedAnonymousId,
                "resolvedUserId" to (resolvedUserId ?: "")
            ))
            log("Journey resumed from prior device")
            cfg.onJourneyResumed?.invoke(resolvedAnonymousId, resolvedUserId)
        } catch (_: Exception) { }
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
