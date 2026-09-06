// =============================================================================
// Aether SDK — iOS (Swift)
// Core analytics, identity, session, consent, Web3 tracking
// =============================================================================

import Foundation
import CryptoKit
import Network

#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

#if canImport(MetricKit)
import MetricKit
#endif

#if canImport(AppTrackingTransparency)
import AppTrackingTransparency
#endif

#if canImport(AdSupport)
import AdSupport
#endif

// MARK: - Configuration

public struct AetherConfig {
    public let apiKey: String
    public var environment: Environment = .production
    public var debug: Bool = false
    public var endpoint: String = "https://api.aether.io"
    public var modules: ModuleConfig = ModuleConfig()
    public var privacy: PrivacyConfig = PrivacyConfig()
    public var batchSize: Int = 10
    public var flushInterval: TimeInterval = 5.0
    /// Optional HMAC-SHA256 secret to verify the remote SDK manifest signature
    /// before applying it (Truth Kernel §2.9). When set, unsigned/invalid
    /// manifests are rejected and the last-known-good config is kept.
    public var manifestVerificationKey: String? = nil
    public var autoResumeJourney: Bool = true
    public var onJourneyResumed: ((_ resolvedAnonymousId: String, _ resolvedUserId: String?) -> Void)? = nil

    public init(apiKey: String) {
        self.apiKey = apiKey
    }

    public enum Environment: String, Codable {
        case production, staging, development
    }
}

public struct ModuleConfig {
    public var screenTracking: Bool = true
    public var deepLinkAttribution: Bool = true
    public var pushNotificationTracking: Bool = true
    public var walletTracking: Bool = true
    public var purchaseTracking: Bool = true
    public var errorTracking: Bool = true
    public var experiments: Bool = false

    public init() {}
}

public struct PrivacyConfig {
    public var gdprMode: Bool = false
    public var anonymizeIP: Bool = true
    public var respectATT: Bool = true

    public init() {}
}

public struct CanonicalConsentReceiptInput {
    public let tenantId: String
    public var subjectId: String?
    public var anonymousId: String?
    public var purposes: [String]
    public let state: String
    public let source: String
    public let policyVersion: String
    public var provider: String?
    public var jurisdictionContext: String?
    public var mode: String?
    public var lawfulBasis: String?
    public var grantedAt: String?
    public var deniedAt: String?
    public var revokedAt: String?
    public var expiresAt: String?
    public var gpcObserved: Bool?
    public var dntObserved: Bool?
    public var providerConsentId: String?
    public var metadata: [String: AnyCodable]

    public init(
        tenantId: String,
        subjectId: String? = nil,
        anonymousId: String? = nil,
        purposes: [String],
        state: String,
        source: String,
        policyVersion: String,
        provider: String? = nil,
        jurisdictionContext: String? = nil,
        mode: String? = nil,
        lawfulBasis: String? = nil,
        grantedAt: String? = nil,
        deniedAt: String? = nil,
        revokedAt: String? = nil,
        expiresAt: String? = nil,
        gpcObserved: Bool? = nil,
        dntObserved: Bool? = nil,
        providerConsentId: String? = nil,
        metadata: [String: AnyCodable] = [:]
    ) {
        self.tenantId = tenantId; self.subjectId = subjectId
        self.anonymousId = anonymousId; self.purposes = purposes
        self.state = state; self.source = source; self.policyVersion = policyVersion
        self.provider = provider; self.jurisdictionContext = jurisdictionContext
        self.mode = mode; self.lawfulBasis = lawfulBasis; self.grantedAt = grantedAt
        self.deniedAt = deniedAt; self.revokedAt = revokedAt; self.expiresAt = expiresAt
        self.gpcObserved = gpcObserved; self.dntObserved = dntObserved
        self.providerConsentId = providerConsentId; self.metadata = metadata
    }
}

public struct CanonicalConsentReceipt {
    public let receiptId: String
    public let integrityHash: String
    public let idempotencyKey: String
    public let input: CanonicalConsentReceiptInput
}

public enum ConsentReceiptError: Error {
    case invalidInput(String)
    case notInitialized
    case invalidEndpoint
    case requestFailed(Int)
}

// MARK: - Event Types

public enum AetherEventType: String, Codable, CaseIterable {
// @generated-start aether-event-types/ios-enum
// @generated — DO NOT EDIT. Source: packages/shared/contracts/event-registry.json
// Contract version: 8.12.0 — Run: python scripts/generate_contracts.py
    // core
    case track
    case page
    case screen
    case heartbeat
    case error
    case performance
    case experiment
    // journey
    case journey_started
    case journey_paused
    case journey_resumed
    case journey_continued
    case journey_completed
    case journey_abandoned
    case journey_checkpoint
    case navigation_intent
    case navigation_arrival
    case deep_link_opened
    case app_install_attributed
    case deferred_attribution_resolved
    case qr_code_scanned
    case nfc_tag_read
    case app_clip_invoked
    // identity
    case identify
    // consent
    case consent
    // commerce
    case conversion
    case payment_initiated
    case payment_completed
    case payment_failed
    case approval_requested
    case approval_resolved
    case entitlement_granted
    case entitlement_revoked
    case access_granted
    case access_denied
    // wallet
    case wallet
    case transaction
    case contract_action
    // agent
    case agent_task
    case agent_decision
    case a2h_interaction
    case agent_registered
    case agent_updated
    case agent_authorized
    case agent_deauthorized
    case agent_capability_granted
    case agent_capability_revoked
    case agent_task_created
    case agent_task_decomposed
    case agent_task_started
    case agent_task_completed
    case agent_task_failed
    case agent_tool_called
    case agent_resource_requested
    case agent_delegated_task
    case agent_subagent_spawned
    case agent_policy_evaluated
    case agent_handoff
    case agent_escalated_to_human
    case agent_outcome_recorded
    case agentic_account_observed
    case agentic_account_connected_observed
    case agentic_account_disconnected_observed
    case agent_budget_observed
    case agent_budget_changed_observed
    case agent_permission_observed
    case agent_mcp_connection_observed
    case agent_tool_observed
    case agent_tool_invocation_observed
    case agent_activity_observed
    case agent_risk_signal_observed
    case agent_notification_observed
    case agent_strategy_observed
    case agent_trade_intent_observed
    case agent_trade_order_observed
    case agent_trade_fill_observed
    case agent_trade_rejection_observed
    case agent_position_observed
    case agent_portfolio_snapshot_observed
    case agent_performance_snapshot_observed
    case agent_disconnect_observed
    case agent_inbox_observed
    case agent_email_address_observed
    case agent_thread_observed
    case agent_message_received_observed
    case agent_message_sent_observed
    case agent_reply_observed
    case agent_attachment_observed
    case agent_attachment_parsed_observed
    case agent_otp_detected_observed
    case agent_invoice_detected_observed
    case agent_receipt_detected_observed
    case agent_calendar_intent_observed
    case agent_support_route_observed
    case agent_semantic_search_observed
    case agent_data_extraction_observed
    case agent_evaluation_observed
    case agent_cost_observed
    case ai_invocation_observed
    case agent_grounding_observed
    case agent_guardrail_observed
    case agent_human_override_observed
    // reward
    case reward_action_queued
    case reward_proof_generated
    case reward_delivered
    case reward_claim_submitted
    // x402
    case x402_payment
    case x402_resource_requested
    case x402_payment_required
    case x402_quote_received
    case x402_authorization_requested
    case x402_authorization_resolved
    case x402_payment_intent_created
    case x402_payment_submitted
    case x402_payment_settled
    case x402_payment_failed
    case x402_payment_timeout
    case x402_receipt_verified
    case x402_access_granted
    case x402_access_denied
    case x402_refund_or_reversal
    case x402_resource_request_observed
    case x402_challenge_observed
    case x402_payment_requirement_observed
    case x402_signature_observed
    case x402_verification_observed
    case x402_settlement_observed
    case x402_resource_access_observed
    case x402_resource_access_denied_observed
    case x402_failure_observed
    case x402_replay_risk_observed
    case x402_provider_observed
    // exposure
    case content_impression
    case recommendation_exposed
    case offer_exposed
    case feature_exposed
    case search_result_exposed
    case ad_exposed
    case notification_presented
    case decision_observed
    // outcome
    case outcome_observed
    case goal_achieved
    case goal_failed
    case recommendation_accepted
    case recommendation_rejected
    case feedback_submitted
    case retention_observed
    case churn_observed
    case human_override_observed
    // b2b
    case organization_observed
    case workspace_created
    case workspace_updated
    case member_invited
    case member_joined
    case member_removed
    case role_changed
    case seat_assigned
    case seat_released
    case integration_connected
    case integration_disconnected
    case service_account_created
    case service_account_revoked
    case api_key_created
    case api_key_revoked
    case project_created
    case project_archived
    case workflow_started
    case workflow_completed
    case workflow_failed
    // ecommerce
    case product_viewed
    case cart_item_added
    case cart_item_removed
    case cart_updated
    case coupon_applied
    case checkout_started
    case checkout_step_completed
    case order_completed
    case order_cancelled
    case order_refunded
    case chargeback_observed
    case subscription_started
    case trial_started
    case trial_converted
    case subscription_renewed
    case subscription_upgrade_observed
    case subscription_downgrade_observed
    case subscription_cancelled
    case invoice_issued
    case invoice_paid
    case invoice_failed
    case dunning_started
    case dunning_resolved
    // friction
    case dead_click_observed
    case rage_click_observed
    case scroll_depth_observed
    case form_started
    case form_field_interaction
    case form_validation_failed
    case form_submitted
    case form_abandoned
    case search_reformulated
    case retry_observed
    case journey_stalled
    case backtrack_observed
    // interaction
    case surface_entered
    case surface_exited
    case interaction_observed
    case ui_interaction_observed
    case feature_started
    case feature_completed
    case feature_abandoned
    case action_attempted
    case action_succeeded
    case action_failed
    case action_cancelled
    case active_interval_observed
    // server
    case api_request_observed
    case webhook_delivery_observed
    case connector_sync_started
    case connector_sync_completed
    case connector_sync_failed
    case job_started
    case job_completed
    case job_failed
    case rate_limit_observed
    case dependency_failure_observed
    case export_completed
    // identity_lc
    case signup_started
    case signup_completed
    case login_succeeded
    case login_failed
    case logout_observed
    case sso_observed
    case mfa_challenge_observed
    case identity_verified
    case alias_link_requested
    case alias_link_confirmed
    case alias_revoked
    case account_recovery_started
    case account_recovery_completed
    case device_registered
    case device_revoked
    // web3_lc
    case transaction_pending_observed
    case transaction_confirmed_observed
    case transaction_reverted_observed
    case transaction_reorged_observed
    case token_approval_observed
    case allowance_changed_observed
    case bridge_transfer_observed
    case settlement_finality_observed
    // comms
    case notification_delivered
    case notification_opened
    case notification_clicked
    case email_delivered
    case email_opened
    case email_clicked
    case email_bounced
    case email_queued
    case email_processed
    case email_sent
    case email_deferred
    case email_dropped
    case email_replied
    case email_spam_complaint
    case email_suppressed
    case message_received_observed
    case message_sent_observed
    case message_replied_observed
    case unsubscribe_observed
    case support_case_created
    case support_case_resolved
    case support_case_escalated
    case support_sla_breached
    // credit
    case credit_signal_observed
    case credit_account_observed
    case credit_decision_observed
    // location
    case location_observed
    case geofence_transition_observed
    // derivatives
    case trading_account_connected
    case trading_account_disconnected
    case trading_account_authorized
    case trading_account_deauthorized
    case trading_agent_enabled
    case trading_agent_disabled
    case trade_intent_created
    case trade_approval_requested
    case trade_approval_resolved
    case risk_policy_updated
    case human_trade_override_recorded
    case derivatives_venue_registered
    case derivatives_venue_deployment_registered
    case derivatives_instrument_registered
    case derivatives_market_registered
    case derivatives_strategy_registered
    case derivatives_strategy_version_registered
    case derivatives_risk_policy_registered
    case derivatives_account_linked
    case derivatives_account_link_revoked
    case derivatives_balance_snapshot_observed
    case derivatives_collateral_change_observed
    case derivatives_margin_snapshot_observed
    case derivatives_order_observed
    case derivatives_order_updated_observed
    case derivatives_order_cancelled_observed
    case derivatives_order_rejected_observed
    case derivatives_order_expired_observed
    case derivatives_fill_observed
    case derivatives_fill_corrected
    case derivatives_position_opened_observed
    case derivatives_position_increased_observed
    case derivatives_position_reduced_observed
    case derivatives_position_closed_observed
    case derivatives_position_liquidated_observed
    case derivatives_position_adl_observed
    case derivatives_position_settled_observed
    case derivatives_position_corrected
    case derivatives_funding_payment_observed
    case derivatives_fee_observed
    case derivatives_pnl_snapshot_materialized
    case derivatives_exposure_snapshot_materialized
    case derivatives_price_observation_recorded
    case derivatives_market_status_changed
    case derivatives_stream_gap_detected
    case derivatives_stream_gap_recovered
    case derivatives_stream_checkpoint_advanced
    case derivatives_adapter_conformance_run
    case derivatives_reconciliation_run_completed
    case derivatives_reconciliation_variance_detected
    case derivatives_reconciliation_variance_resolved
    case derivatives_risk_threshold_breached
    // stablecoin
    case stablecoin_transfer_observed
    case stablecoin_payment_observed
    case stablecoin_mint_observed
    case stablecoin_burn_observed
    case stablecoin_bridge_outbound_observed
    case stablecoin_bridge_inbound_observed
    case stablecoin_swap_observed
    case stablecoin_x402_settlement_observed
    case stablecoin_treasury_movement_observed
    case stablecoin_payout_observed
    case stablecoin_venue_deposit_observed
    case stablecoin_venue_withdrawal_observed
    case stablecoin_balance_snapshot_observed
    case stablecoin_supply_snapshot_observed
    case stablecoin_holder_concentration_observed
    case stablecoin_valuation_observed
    case stablecoin_depeg_detected
    case stablecoin_depeg_resolved
    case stablecoin_finality_confirmed
    case stablecoin_reorg_detected
    case stablecoin_observation_corrected
    case stablecoin_reconciliation_run_completed
    case stablecoin_reconciliation_variance_detected
    case stablecoin_reconciliation_variance_resolved
    case stablecoin_asset_registered
    case stablecoin_deployment_registered
    case stablecoin_support_asserted
    case stablecoin_support_revoked
    case stablecoin_flow_aggregate_materialized
    case stablecoin_checkpoint_advanced
    // interop
    case interop_provider_registered
    case interop_gateway_registered
    case interop_path_registered
    case interop_application_registered
    case interop_verification_actor_registered
    case interop_message_discovered
    case interop_message_sent_observed
    case interop_message_source_confirmed
    case interop_message_verification_observed
    case interop_message_verified
    case interop_message_delivery_attempt_observed
    case interop_message_delivered
    case interop_message_executed_observed
    case interop_message_settled
    case interop_message_failed
    case interop_message_timeout
    case interop_message_expired
    case interop_message_cancelled
    case interop_message_refunded_observed
    case interop_message_recovered
    case interop_message_reorged
    case interop_message_corrected
    case interop_message_correlated
    case interop_intent_observed
    case interop_intent_fulfilled_observed
    case interop_asset_leg_locked_observed
    case interop_asset_leg_burned_observed
    case interop_asset_leg_minted_observed
    case interop_asset_leg_released_observed
    case interop_fee_observed
    case interop_security_policy_snapshot_recorded
    case interop_security_policy_changed
    case interop_verification_quorum_observed
    case interop_provider_checkpoint_advanced
    case interop_stream_gap_detected
    case interop_stream_gap_recovered
    case interop_reconciliation_run_completed
    case interop_reconciliation_variance_detected
    case interop_reconciliation_variance_resolved
    // privacy
    case data_subject_request_received
    case data_subject_request_queued
    case data_subject_request_denied
    case erasure_completed
    case erasure_failed
// @generated-end aether-event-types/ios-enum
}

public struct AetherEvent: Codable {
    public let id: String
    public let type: AetherEventType
    public let timestamp: String
    public let sessionId: String
    public let anonymousId: String
    public var userId: String?
    public var properties: [String: AnyCodable]
    public var context: EventContext
}


private struct PersistedQueueEnvelope: Codable {
    let version: Int
    let savedAt: String
    let events: [AetherEvent]
}

public struct EventContext: Codable {
    public let library: LibraryInfo
    public var device: DeviceInfo?
    public var campaign: CampaignInfo?
    // Active acquisition evidence (shared AcquisitionEvidence schema v3,
    // packages/shared/acquisition-evidence.ts). Stamped on every outgoing
    // event while unexpired evidence exists, mirroring campaign attachment.
    // The SDK only OBSERVES evidence — the backend classifier owns the
    // resulting source classification.
    public var acquisitionEvidence: [String: AnyCodable]?
    public var fingerprint: FingerprintInfo?
    public var network: String?
    public var thermalState: String?
    public var consent: [String: Bool]?
    // Active journey snapshot stamped on EVERY event (not just journey_*
    // lifecycle events), matching the web SDK's context.journey, so the
    // backend can annotate any event with the journey it occurred within.
    public var journey: JourneyInfo?
    // Monotonic per-session ordering counter for gap/reorder detection at
    // ingest, matching the web SDK's context.sequence.event wire shape.
    public var sequence: SequenceInfo?
    // Temporal provenance captured at event occurrence (not SDK init) —
    // top-level on the wire context, matching the ingestion contract
    // (packages/shared/events.ts::EventContext).
    public var timezone: String?
    public var utcOffsetMinutes: Int?
    public var timeZoneSource: String?
    public var clockSource: String?

    public struct LibraryInfo: Codable {
        public let name: String
        public let version: String
    }

    public struct DeviceInfo: Codable {
        public let osName: String
        public let osVersion: String
        public let locale: String
        public let timezone: String
    }

    public struct CampaignInfo: Codable {
        public var source: String?
        public var medium: String?
        public var campaign: String?
        public var content: String?
        public var term: String?
        public var clickIds: [String: String] = [:]
        public var referrerDomain: String?
    }

    public struct FingerprintInfo: Codable {
        public let id: String
    }

    public struct JourneyInfo: Codable {
        public let journeyId: String
        public var journeyName: String?
        public var journeyType: String?
        public var journeyStatus: String?
    }

    public struct SequenceInfo: Codable {
        public let event: Int
    }
}

// MARK: - Identity

public struct WalletEntry {
    public var address: String
    public var vm: String       // evm | svm | bitcoin | movevm | near | tvm | cosmos
    public var walletType: String
    public var chainId: String

    public init(address: String, vm: String = "evm", walletType: String = "unknown", chainId: String = "unknown") {
        self.address = address; self.vm = vm
        self.walletType = walletType; self.chainId = chainId
    }
}

public struct IdentityData {
    public var userId: String?
    public var email: String?
    public var walletAddress: String?
    public var walletType: String?
    public var chainId: Int?
    public var traits: [String: AnyCodable]?
    public var wallets: [WalletEntry]

    public init(userId: String? = nil, email: String? = nil, walletAddress: String? = nil,
                traits: [String: AnyCodable]? = nil, wallets: [WalletEntry] = []) {
        self.userId = userId; self.email = email
        self.walletAddress = walletAddress
        self.traits = traits; self.wallets = wallets
    }
}

// MARK: - Device Fingerprint

struct DeviceFingerprint {
    static func generate() -> String {
        #if canImport(UIKit)
        let signals = [
            UIDevice.current.identifierForVendor?.uuidString ?? "",
            UIDevice.current.model,
            UIDevice.current.systemVersion,
            String(describing: UIScreen.main.bounds.width),
            String(describing: UIScreen.main.bounds.height),
            String(describing: UIScreen.main.scale),
            Locale.current.identifier,
            TimeZone.current.identifier,
            String(ProcessInfo.processInfo.processorCount),
            String(ProcessInfo.processInfo.physicalMemory),
        ]
        #else
        let signals = [
            Host.current().localizedName ?? "",
            "macOS",
            ProcessInfo.processInfo.operatingSystemVersionString,
            Locale.current.identifier,
            TimeZone.current.identifier,
            String(ProcessInfo.processInfo.processorCount),
            String(ProcessInfo.processInfo.physicalMemory),
        ]
        #endif
        return sha256(signals.joined(separator: "|"))
    }

    static func sha256(_ input: String) -> String {
        let data = Data(input.utf8)
        let hash = SHA256.hash(data: data)
        return hash.compactMap { String(format: "%02x", $0) }.joined()
    }
}

// MARK: - Batch Health

/// Per-batch ingestion health counters (Truth Kernel §2.8).
///
/// `accepted` / `duplicate` / `rejected` are parsed from the backend
/// BatchResponse (packages/shared/ingestion-contract.ts). `droppedByConsent`
/// and `queueDepth` are SDK-side truths: consent gating removes events before
/// they leave the device, and queueDepth reflects the local backlog after send.
public struct BatchHealth {
    public let accepted: Int
    public let duplicate: Int
    public let rejected: Int
    public let droppedByConsent: Int
    public let queueDepth: Int
}

// MARK: - Main SDK Class

public final class Aether: NSObject {
    public static let shared = Aether()

    /// Invoked after each processed batch with per-batch ingestion health (§2.8).
    public var onBatchResult: ((BatchHealth) -> Void)?

    private var config: AetherConfig?
    private var eventQueue: [AetherEvent] = []
    /// Consent-dropped events accumulated since the last batch send (§2.8).
    private var pendingConsentDrops: Int = 0
    private var sessionId: String = UUID().uuidString
    private var currentJourneyId: String? = nil
    private var currentJourneyName: String? = nil
    private var currentJourneyType: String? = nil
    private var currentJourneyStatus: String? = nil
    private var anonymousId: String = ""
    private var userId: String?
    private var walletAddress: String?
    private var email: String?
    private var traits: [String: AnyCodable] = [:]
    private var flushTimer: Timer?
    private var sessionStart: Date = Date()
    private var appStartDate: Date = Date()
    private var screenCount: Int = 0
    private var eventCount: Int = 0
    /// Monotonic per-session event index stamped into context.sequence.event
    /// (reset on every session rotation) so the backend can detect
    /// gaps/reordering in this client's stream.
    private var eventSequence: Int = 0
    private var isInitialized = false
    private var serverConfig: [String: Any] = [:]
    private var consentState: [String] = []
    private var fingerprintId: String = ""
    private var campaignInfo: EventContext.CampaignInfo?
    /// In-memory mirrors of the persisted first/latest acquisition touches.
    /// Loaded from UserDefaults at initialize(); kept in sync on every write
    /// so buildContext() never has to decode JSON per event.
    private var firstTouchEvidence: [String: AnyCodable]?
    private var latestTouchEvidence: [String: AnyCodable]?
    /// URL+timestamp dedup for incoming deep/universal links: cold-start and
    /// warm-start delivery paths (AppDelegate + SceneDelegate) frequently hand
    /// the SDK the same URL twice within the same launch.
    private var processedIncomingURLs: [String: Date] = [:]
    private var healthAgent: AetherHealthAgent?
    /// Sampling rate in [0,1] derived from the remote manifest's
    /// `rollout_percentage` (Truth Kernel remote config). 1.0 (no gate) until
    /// a manifest has been fetched, verified, and applied via
    /// `onManifestUpdate`. See `enqueueEvent(type:properties:)`.
    var samplingRate: Double = 1.0
    /// Manifest-provided feature-flag overrides (`SDKManifest.features`),
    /// applied on top of `serverConfig["featureFlags"]` in
    /// `isFeatureEnabled(_:default:)`. Empty until a manifest is applied.
    var manifestFeatureOverrides: [String: Bool] = [:]
    private let networkMonitor = NWPathMonitor()
    private var currentNetworkType: String = "unknown"

    private static let clickIdParams: Set<String> = [
        "gclid", "msclkid", "fbclid", "ttclid", "twclid",
        "li_fat_id", "rdt_cid", "scid", "dclid", "epik",
        "irclickid", "aff_id"
    ]

    private static let eventConsentPurpose: [AetherEventType: String] = [
// @generated-start aether-consent-purposes/ios-map
// @generated — DO NOT EDIT. Source: packages/shared/contracts/event-registry.json
// Contract version: 8.12.0 — Run: python scripts/generate_contracts.py
        // core
        .track: "analytics",
        .page: "analytics",
        .screen: "analytics",
        .heartbeat: "analytics",
        .error: "analytics",
        .performance: "analytics",
        .experiment: "marketing",
        // journey
        .journey_started: "analytics",
        .journey_paused: "analytics",
        .journey_resumed: "analytics",
        .journey_continued: "analytics",
        .journey_completed: "analytics",
        .journey_abandoned: "analytics",
        .journey_checkpoint: "analytics",
        .navigation_intent: "analytics",
        .navigation_arrival: "analytics",
        .deep_link_opened: "analytics",
        .app_install_attributed: "analytics",
        .deferred_attribution_resolved: "analytics",
        .qr_code_scanned: "analytics",
        .nfc_tag_read: "analytics",
        .app_clip_invoked: "analytics",
        // identity
        .identify: "analytics",
        // consent
        .consent: "analytics",
        // commerce
        .conversion: "marketing",
        .payment_initiated: "commerce",
        .payment_completed: "commerce",
        .payment_failed: "commerce",
        .approval_requested: "commerce",
        .approval_resolved: "commerce",
        .entitlement_granted: "commerce",
        .entitlement_revoked: "commerce",
        .access_granted: "commerce",
        .access_denied: "commerce",
        // wallet
        .wallet: "web3",
        .transaction: "web3",
        .contract_action: "web3",
        // agent
        .agent_task: "agent",
        .agent_decision: "agent",
        .a2h_interaction: "agent",
        .agent_registered: "agent",
        .agent_updated: "agent",
        .agent_authorized: "agent",
        .agent_deauthorized: "agent",
        .agent_capability_granted: "agent",
        .agent_capability_revoked: "agent",
        .agent_task_created: "agent",
        .agent_task_decomposed: "agent",
        .agent_task_started: "agent",
        .agent_task_completed: "agent",
        .agent_task_failed: "agent",
        .agent_tool_called: "agent",
        .agent_resource_requested: "agent",
        .agent_delegated_task: "agent",
        .agent_subagent_spawned: "agent",
        .agent_policy_evaluated: "agent",
        .agent_handoff: "agent",
        .agent_escalated_to_human: "agent",
        .agent_outcome_recorded: "agent",
        .agentic_account_observed: "agent",
        .agentic_account_connected_observed: "agent",
        .agentic_account_disconnected_observed: "agent",
        .agent_budget_observed: "agent",
        .agent_budget_changed_observed: "agent",
        .agent_permission_observed: "agent",
        .agent_mcp_connection_observed: "agent",
        .agent_tool_observed: "agent",
        .agent_tool_invocation_observed: "agent",
        .agent_activity_observed: "agent",
        .agent_risk_signal_observed: "agent",
        .agent_notification_observed: "agent",
        .agent_strategy_observed: "agent",
        .agent_trade_intent_observed: "agent",
        .agent_trade_order_observed: "financial_activity",
        .agent_trade_fill_observed: "financial_activity",
        .agent_trade_rejection_observed: "agent",
        .agent_position_observed: "financial_activity",
        .agent_portfolio_snapshot_observed: "financial_activity",
        .agent_performance_snapshot_observed: "financial_activity",
        .agent_disconnect_observed: "agent",
        .agent_inbox_observed: "agent",
        .agent_email_address_observed: "agent",
        .agent_thread_observed: "agent",
        .agent_message_received_observed: "agent",
        .agent_message_sent_observed: "agent",
        .agent_reply_observed: "agent",
        .agent_attachment_observed: "agent",
        .agent_attachment_parsed_observed: "agent",
        .agent_otp_detected_observed: "agent",
        .agent_invoice_detected_observed: "agent",
        .agent_receipt_detected_observed: "agent",
        .agent_calendar_intent_observed: "agent",
        .agent_support_route_observed: "agent",
        .agent_semantic_search_observed: "agent",
        .agent_data_extraction_observed: "agent",
        .agent_evaluation_observed: "agent",
        .agent_cost_observed: "agent",
        .ai_invocation_observed: "agent",
        .agent_grounding_observed: "agent",
        .agent_guardrail_observed: "agent",
        .agent_human_override_observed: "agent",
        // reward
        .reward_action_queued: "commerce",
        .reward_proof_generated: "commerce",
        .reward_delivered: "commerce",
        .reward_claim_submitted: "commerce",
        // x402
        .x402_payment: "commerce",
        .x402_resource_requested: "commerce",
        .x402_payment_required: "commerce",
        .x402_quote_received: "commerce",
        .x402_authorization_requested: "commerce",
        .x402_authorization_resolved: "commerce",
        .x402_payment_intent_created: "commerce",
        .x402_payment_submitted: "commerce",
        .x402_payment_settled: "commerce",
        .x402_payment_failed: "commerce",
        .x402_payment_timeout: "commerce",
        .x402_receipt_verified: "commerce",
        .x402_access_granted: "commerce",
        .x402_access_denied: "commerce",
        .x402_refund_or_reversal: "commerce",
        .x402_resource_request_observed: "commerce",
        .x402_challenge_observed: "commerce",
        .x402_payment_requirement_observed: "commerce",
        .x402_signature_observed: "commerce",
        .x402_verification_observed: "commerce",
        .x402_settlement_observed: "commerce",
        .x402_resource_access_observed: "commerce",
        .x402_resource_access_denied_observed: "commerce",
        .x402_failure_observed: "commerce",
        .x402_replay_risk_observed: "commerce",
        .x402_provider_observed: "commerce",
        // exposure
        .content_impression: "analytics",
        .recommendation_exposed: "analytics",
        .offer_exposed: "analytics",
        .feature_exposed: "analytics",
        .search_result_exposed: "analytics",
        .ad_exposed: "marketing",
        .notification_presented: "analytics",
        .decision_observed: "analytics",
        // outcome
        .outcome_observed: "analytics",
        .goal_achieved: "analytics",
        .goal_failed: "analytics",
        .recommendation_accepted: "analytics",
        .recommendation_rejected: "analytics",
        .feedback_submitted: "analytics",
        .retention_observed: "analytics",
        .churn_observed: "analytics",
        .human_override_observed: "analytics",
        // b2b
        .organization_observed: "analytics",
        .workspace_created: "analytics",
        .workspace_updated: "analytics",
        .member_invited: "analytics",
        .member_joined: "analytics",
        .member_removed: "analytics",
        .role_changed: "analytics",
        .seat_assigned: "analytics",
        .seat_released: "analytics",
        .integration_connected: "analytics",
        .integration_disconnected: "analytics",
        .service_account_created: "analytics",
        .service_account_revoked: "analytics",
        .api_key_created: "analytics",
        .api_key_revoked: "analytics",
        .project_created: "analytics",
        .project_archived: "analytics",
        .workflow_started: "analytics",
        .workflow_completed: "analytics",
        .workflow_failed: "analytics",
        // ecommerce
        .product_viewed: "commerce",
        .cart_item_added: "commerce",
        .cart_item_removed: "commerce",
        .cart_updated: "commerce",
        .coupon_applied: "commerce",
        .checkout_started: "commerce",
        .checkout_step_completed: "commerce",
        .order_completed: "commerce",
        .order_cancelled: "commerce",
        .order_refunded: "commerce",
        .chargeback_observed: "commerce",
        .subscription_started: "commerce",
        .trial_started: "commerce",
        .trial_converted: "commerce",
        .subscription_renewed: "commerce",
        .subscription_upgrade_observed: "commerce",
        .subscription_downgrade_observed: "commerce",
        .subscription_cancelled: "commerce",
        .invoice_issued: "commerce",
        .invoice_paid: "commerce",
        .invoice_failed: "commerce",
        .dunning_started: "commerce",
        .dunning_resolved: "commerce",
        // friction
        .dead_click_observed: "analytics",
        .rage_click_observed: "analytics",
        .scroll_depth_observed: "analytics",
        .form_started: "analytics",
        .form_field_interaction: "analytics",
        .form_validation_failed: "analytics",
        .form_submitted: "analytics",
        .form_abandoned: "analytics",
        .search_reformulated: "analytics",
        .retry_observed: "analytics",
        .journey_stalled: "analytics",
        .backtrack_observed: "analytics",
        // interaction
        .surface_entered: "analytics",
        .surface_exited: "analytics",
        .interaction_observed: "analytics",
        .ui_interaction_observed: "analytics",
        .feature_started: "analytics",
        .feature_completed: "analytics",
        .feature_abandoned: "analytics",
        .action_attempted: "analytics",
        .action_succeeded: "analytics",
        .action_failed: "analytics",
        .action_cancelled: "analytics",
        .active_interval_observed: "analytics",
        // server
        .api_request_observed: "analytics",
        .webhook_delivery_observed: "analytics",
        .connector_sync_started: "analytics",
        .connector_sync_completed: "analytics",
        .connector_sync_failed: "analytics",
        .job_started: "analytics",
        .job_completed: "analytics",
        .job_failed: "analytics",
        .rate_limit_observed: "analytics",
        .dependency_failure_observed: "analytics",
        .export_completed: "analytics",
        // identity_lc
        .signup_started: "analytics",
        .signup_completed: "analytics",
        .login_succeeded: "analytics",
        .login_failed: "analytics",
        .logout_observed: "analytics",
        .sso_observed: "analytics",
        .mfa_challenge_observed: "analytics",
        .identity_verified: "analytics",
        .alias_link_requested: "analytics",
        .alias_link_confirmed: "analytics",
        .alias_revoked: "analytics",
        .account_recovery_started: "analytics",
        .account_recovery_completed: "analytics",
        .device_registered: "analytics",
        .device_revoked: "analytics",
        // web3_lc
        .transaction_pending_observed: "web3",
        .transaction_confirmed_observed: "web3",
        .transaction_reverted_observed: "web3",
        .transaction_reorged_observed: "web3",
        .token_approval_observed: "web3",
        .allowance_changed_observed: "web3",
        .bridge_transfer_observed: "web3",
        .settlement_finality_observed: "web3",
        // comms
        .notification_delivered: "analytics",
        .notification_opened: "analytics",
        .notification_clicked: "analytics",
        .email_delivered: "marketing",
        .email_opened: "marketing",
        .email_clicked: "marketing",
        .email_bounced: "marketing",
        .email_queued: "marketing",
        .email_processed: "marketing",
        .email_sent: "marketing",
        .email_deferred: "marketing",
        .email_dropped: "marketing",
        .email_replied: "marketing",
        .email_spam_complaint: "marketing",
        .email_suppressed: "marketing",
        .message_received_observed: "analytics",
        .message_sent_observed: "analytics",
        .message_replied_observed: "analytics",
        .unsubscribe_observed: "marketing",
        .support_case_created: "analytics",
        .support_case_resolved: "analytics",
        .support_case_escalated: "analytics",
        .support_sla_breached: "analytics",
        // credit
        .credit_signal_observed: "credit",
        .credit_account_observed: "credit",
        .credit_decision_observed: "credit",
        // location
        .location_observed: "location",
        .geofence_transition_observed: "location",
        // derivatives
        .trading_account_connected: "financial_activity",
        .trading_account_disconnected: "financial_activity",
        .trading_account_authorized: "financial_activity",
        .trading_account_deauthorized: "financial_activity",
        .trading_agent_enabled: "financial_activity",
        .trading_agent_disabled: "financial_activity",
        .trade_intent_created: "financial_activity",
        .trade_approval_requested: "financial_activity",
        .trade_approval_resolved: "financial_activity",
        .risk_policy_updated: "financial_activity",
        .human_trade_override_recorded: "financial_activity",
        .derivatives_venue_registered: "financial_activity",
        .derivatives_venue_deployment_registered: "financial_activity",
        .derivatives_instrument_registered: "financial_activity",
        .derivatives_market_registered: "financial_activity",
        .derivatives_strategy_registered: "financial_activity",
        .derivatives_strategy_version_registered: "financial_activity",
        .derivatives_risk_policy_registered: "financial_activity",
        .derivatives_account_linked: "financial_activity",
        .derivatives_account_link_revoked: "financial_activity",
        .derivatives_balance_snapshot_observed: "financial_activity",
        .derivatives_collateral_change_observed: "financial_activity",
        .derivatives_margin_snapshot_observed: "financial_activity",
        .derivatives_order_observed: "financial_activity",
        .derivatives_order_updated_observed: "financial_activity",
        .derivatives_order_cancelled_observed: "financial_activity",
        .derivatives_order_rejected_observed: "financial_activity",
        .derivatives_order_expired_observed: "financial_activity",
        .derivatives_fill_observed: "financial_activity",
        .derivatives_fill_corrected: "financial_activity",
        .derivatives_position_opened_observed: "financial_activity",
        .derivatives_position_increased_observed: "financial_activity",
        .derivatives_position_reduced_observed: "financial_activity",
        .derivatives_position_closed_observed: "financial_activity",
        .derivatives_position_liquidated_observed: "financial_activity",
        .derivatives_position_adl_observed: "financial_activity",
        .derivatives_position_settled_observed: "financial_activity",
        .derivatives_position_corrected: "financial_activity",
        .derivatives_funding_payment_observed: "financial_activity",
        .derivatives_fee_observed: "financial_activity",
        .derivatives_pnl_snapshot_materialized: "financial_activity",
        .derivatives_exposure_snapshot_materialized: "financial_activity",
        .derivatives_price_observation_recorded: "financial_activity",
        .derivatives_market_status_changed: "financial_activity",
        .derivatives_stream_gap_detected: "financial_activity",
        .derivatives_stream_gap_recovered: "financial_activity",
        .derivatives_stream_checkpoint_advanced: "financial_activity",
        .derivatives_adapter_conformance_run: "financial_activity",
        .derivatives_reconciliation_run_completed: "financial_activity",
        .derivatives_reconciliation_variance_detected: "financial_activity",
        .derivatives_reconciliation_variance_resolved: "financial_activity",
        .derivatives_risk_threshold_breached: "financial_activity",
        // stablecoin
        .stablecoin_transfer_observed: "economic_observability",
        .stablecoin_payment_observed: "economic_observability",
        .stablecoin_mint_observed: "economic_observability",
        .stablecoin_burn_observed: "economic_observability",
        .stablecoin_bridge_outbound_observed: "economic_observability",
        .stablecoin_bridge_inbound_observed: "economic_observability",
        .stablecoin_swap_observed: "economic_observability",
        .stablecoin_x402_settlement_observed: "economic_observability",
        .stablecoin_treasury_movement_observed: "economic_observability",
        .stablecoin_payout_observed: "economic_observability",
        .stablecoin_venue_deposit_observed: "economic_observability",
        .stablecoin_venue_withdrawal_observed: "economic_observability",
        .stablecoin_balance_snapshot_observed: "economic_observability",
        .stablecoin_supply_snapshot_observed: "economic_observability",
        .stablecoin_holder_concentration_observed: "economic_observability",
        .stablecoin_valuation_observed: "economic_observability",
        .stablecoin_depeg_detected: "economic_observability",
        .stablecoin_depeg_resolved: "economic_observability",
        .stablecoin_finality_confirmed: "economic_observability",
        .stablecoin_reorg_detected: "economic_observability",
        .stablecoin_observation_corrected: "economic_observability",
        .stablecoin_reconciliation_run_completed: "economic_observability",
        .stablecoin_reconciliation_variance_detected: "economic_observability",
        .stablecoin_reconciliation_variance_resolved: "economic_observability",
        .stablecoin_asset_registered: "economic_observability",
        .stablecoin_deployment_registered: "economic_observability",
        .stablecoin_support_asserted: "economic_observability",
        .stablecoin_support_revoked: "economic_observability",
        .stablecoin_flow_aggregate_materialized: "economic_observability",
        .stablecoin_checkpoint_advanced: "economic_observability",
        // interop
        .interop_provider_registered: "cross_chain_observability",
        .interop_gateway_registered: "cross_chain_observability",
        .interop_path_registered: "cross_chain_observability",
        .interop_application_registered: "cross_chain_observability",
        .interop_verification_actor_registered: "cross_chain_observability",
        .interop_message_discovered: "cross_chain_observability",
        .interop_message_sent_observed: "cross_chain_observability",
        .interop_message_source_confirmed: "cross_chain_observability",
        .interop_message_verification_observed: "cross_chain_observability",
        .interop_message_verified: "cross_chain_observability",
        .interop_message_delivery_attempt_observed: "cross_chain_observability",
        .interop_message_delivered: "cross_chain_observability",
        .interop_message_executed_observed: "cross_chain_observability",
        .interop_message_settled: "cross_chain_observability",
        .interop_message_failed: "cross_chain_observability",
        .interop_message_timeout: "cross_chain_observability",
        .interop_message_expired: "cross_chain_observability",
        .interop_message_cancelled: "cross_chain_observability",
        .interop_message_refunded_observed: "cross_chain_observability",
        .interop_message_recovered: "cross_chain_observability",
        .interop_message_reorged: "cross_chain_observability",
        .interop_message_corrected: "cross_chain_observability",
        .interop_message_correlated: "cross_chain_observability",
        .interop_intent_observed: "cross_chain_observability",
        .interop_intent_fulfilled_observed: "cross_chain_observability",
        .interop_asset_leg_locked_observed: "cross_chain_observability",
        .interop_asset_leg_burned_observed: "cross_chain_observability",
        .interop_asset_leg_minted_observed: "cross_chain_observability",
        .interop_asset_leg_released_observed: "cross_chain_observability",
        .interop_fee_observed: "cross_chain_observability",
        .interop_security_policy_snapshot_recorded: "cross_chain_observability",
        .interop_security_policy_changed: "cross_chain_observability",
        .interop_verification_quorum_observed: "cross_chain_observability",
        .interop_provider_checkpoint_advanced: "cross_chain_observability",
        .interop_stream_gap_detected: "cross_chain_observability",
        .interop_stream_gap_recovered: "cross_chain_observability",
        .interop_reconciliation_run_completed: "cross_chain_observability",
        .interop_reconciliation_variance_detected: "cross_chain_observability",
        .interop_reconciliation_variance_resolved: "cross_chain_observability",
        // privacy
        .data_subject_request_received: "analytics",
        .data_subject_request_queued: "analytics",
        .data_subject_request_denied: "analytics",
        .erasure_completed: "analytics",
        .erasure_failed: "analytics"
// @generated-end aether-consent-purposes/ios-map
    ]

    static let sensitiveKeys: Set<String> = [
        "privatekey", "private_key", "seedphrase", "seed_phrase", "mnemonic",
        "secret", "secretkey", "secret_key", "password", "pin",
        "cardnumber", "card_number", "pan", "cvv", "cvc", "cvv2",
        "paymenttoken", "payment_token", "authcode", "auth_code"
    ]

    private let serialQueue = DispatchQueue(label: "com.aether.sdk.serial")
    private let defaults = UserDefaults(suiteName: "com.aether.sdk")!
    private static let maxQueueSize = 500
    private static let sessionTimeoutSeconds: TimeInterval = 30 * 60
    private static let maxScrubDepth = 32
    // Acquisition-evidence persistence (shared AcquisitionEvidence schema v3).
    // Keys are versioned so a future schema bump can migrate or discard
    // deliberately instead of silently misreading old payloads.
    private static let acquisitionEvidenceSchemaVersion = 3
    private static let firstTouchDefaultsKey = "acquisitionEvidence.firstTouch.v1"
    private static let latestTouchDefaultsKey = "acquisitionEvidence.latestTouch.v1"
    /// Default evidence lifetime: 30 days from observation, after which stored
    /// touches stop attaching to outgoing events and first touch may be re-set.
    private static let acquisitionEvidenceTTL: TimeInterval = 30 * 24 * 60 * 60
    /// Window inside which the identical incoming URL is treated as a
    /// duplicate delivery (cold-start + warm-start double dispatch).
    private static let incomingURLDedupWindow: TimeInterval = 10
    /// destinationPathHash length: SHA-256 hex truncated to 24 chars, matching
    /// the one-way path-privacy hash documented on the shared contract.
    private static let destinationPathHashLength = 24
    private var lastActivityDate: Date?

    private override init() {
        super.init()
        startNetworkMonitor()
    }

    // MARK: - Public API

    public func initialize(config: AetherConfig) {
        guard !isInitialized else {
            log("Already initialized")
            return
        }

        self.config = config
        self.anonymousId = loadOrCreateAnonymousId()
        self.walletAddress = defaults.string(forKey: "walletAddress")
        self.consentState = defaults.stringArray(forKey: "consentState") ?? []
        self.userId = defaults.string(forKey: "userId")
        self.firstTouchEvidence = loadPersistedEvidence(forKey: Aether.firstTouchDefaultsKey)
        self.latestTouchEvidence = loadPersistedEvidence(forKey: Aether.latestTouchDefaultsKey)
        self.sessionId = UUID().uuidString
        self.sessionStart = Date()
        self.eventSequence = 0

        // Setup flush timer
        flushTimer = Timer.scheduledTimer(withTimeInterval: config.flushInterval, repeats: true) { [weak self] _ in
            self?.flush()
        }

        // Setup lifecycle observers
        setupLifecycleObservers()

        // Auto screen tracking via swizzling (iOS only)
        #if canImport(UIKit)
        if config.modules.screenTracking {
            UIViewController.swizzleViewDidAppear()
        }
        #endif

        self.fingerprintId = DeviceFingerprint.generate()

        // Request App Tracking Transparency authorization if required (iOS 14.5+)
        #if canImport(AppTrackingTransparency)
        if config.privacy.respectATT {
            requestTrackingAuthorization()
        }
        #endif

        isInitialized = true
        log("Aether iOS SDK initialized (v8.12.0)")

        loadPersistedQueue()

        // Health agent: fleet heartbeat + manifest fetch
        let hAgent = AetherHealthAgent(
            endpoint: config.endpoint,
            apiKey: config.apiKey,
            platform: "ios",
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "",
            manifestVerificationKey: config.manifestVerificationKey
        )
        hAgent.getDynamicState = { [weak self] in
            guard let self = self else { return (0, false, false, false) }
            return (
                queueDepth: self.eventQueue.count,
                authValid: self.config?.apiKey.isEmpty == false,
                consentValid: self.consentState.contains("analytics"),
                walletConnected: self.walletAddress != nil
            )
        }
        healthAgent = hAgent
        // Wire the verified remote manifest into the emitter: rollout_percentage
        // drives the sampling gate in enqueueEvent, features feed
        // isFeatureEnabled. Previously fetched+verified+cached and discarded.
        hAgent.onManifestUpdate { [weak self] manifest in
            guard let self = self else { return }
            let pct = max(0, min(100, manifest.rollout_percentage))
            self.samplingRate = Double(pct) / 100.0
            self.manifestFeatureOverrides = manifest.features
        }
        // In GDPR mode, defer health agent until analytics consent granted
        if config.privacy.gdprMode {
            if consentState.contains("analytics") { hAgent.start() }
        } else {
            hAgent.start()
        }

        fetchConfig()
        emitSessionStart()

        // MetricKit: subscribe for diagnostic/performance payloads (iOS 13+)
        #if canImport(MetricKit)
        MXMetricManager.shared.add(self)
        #endif

        if config.autoResumeJourney {
            resolveIdentity(walletAddress: walletAddress, userId: nil, email: nil)
        }
    }

    public func track(_ event: String, properties: [String: AnyCodable] = [:]) {
        enqueueEvent(type: .track, properties: ["event": AnyCodable(event)].merging(properties) { _, new in new })
    }

    /// Canonical low-level observation API (Truth Kernel §2.6). Emits a
    /// first-class backend event `type` directly. Semantics mirror the web SDK:
    ///
    /// - `type` must be a canonical registry event type; unknown types are a
    ///   production-safe no-op (with a debug log), never a silent mislabel.
    /// - Payloads asserting `execution_by_aether == true` are rejected — Aether
    ///   observes, it never executes.
    /// - Consent gating, sensitive-field scrubbing, batching, and the max
    ///   queue-size bound all run on the shared `enqueueEvent` path.
    public func observe(_ type: String, properties: [String: AnyCodable] = [:]) {
        guard let eventType = AetherEventType(rawValue: type),
              Self.eventConsentPurpose[eventType] != nil else {
            log("observe(): '\(type)' is not a canonical event type — ignored")
            return
        }
        if let flag = properties["execution_by_aether"]?.value as? Bool, flag {
            log("observe(): event '\(type)' dropped — execution_by_aether must never be true")
            return
        }
        enqueueEvent(type: eventType, properties: properties)
    }

    /// Current event-queue depth (Truth Kernel §2.6 queue-depth awareness).
    public func queueDepth() -> Int {
        serialQueue.sync { eventQueue.count }
    }

    public func startJourney(_ nameOrType: String, properties: [String: AnyCodable] = [:]) {
        currentJourneyId = properties["journeyId"]?.value as? String ?? UUID().uuidString
        currentJourneyName = nameOrType
        currentJourneyType = nameOrType
        currentJourneyStatus = "started"
        var props = properties; props["journeyId"] = AnyCodable(currentJourneyId ?? ""); props["journeyName"] = AnyCodable(nameOrType); props["journeyType"] = AnyCodable(nameOrType); props["journeyStatus"] = AnyCodable("started")
        enqueueEvent(type: .journey_started, properties: props)
    }

    public func pauseJourney(_ reason: String? = nil, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        currentJourneyStatus = "paused"
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["pauseReason"] = AnyCodable(reason ?? ""); props["journeyStatus"] = AnyCodable("paused")
        enqueueEvent(type: .journey_paused, properties: props)
    }

    public func resumeJourney(_ reason: String? = nil, properties: [String: AnyCodable] = [:]) {
        if currentJourneyId == nil { currentJourneyId = properties["journeyId"]?.value as? String ?? UUID().uuidString }
        currentJourneyStatus = "resumed"
        var props = properties; props["journeyId"] = AnyCodable(currentJourneyId ?? ""); props["resumeReason"] = AnyCodable(reason ?? ""); props["journeyStatus"] = AnyCodable("resumed")
        enqueueEvent(type: .journey_resumed, properties: props)
    }

    public func continueJourney(_ stepIdOrName: String, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        currentJourneyStatus = "continued"
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["stepId"] = AnyCodable(stepIdOrName); props["stepName"] = AnyCodable(stepIdOrName); props["journeyStatus"] = AnyCodable("continued")
        enqueueEvent(type: .journey_continued, properties: props)
    }

    public func completeJourney(_ reason: String? = nil, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        currentJourneyStatus = "completed"
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["completionReason"] = AnyCodable(reason ?? ""); props["journeyStatus"] = AnyCodable("completed")
        enqueueEvent(type: .journey_completed, properties: props); clearCurrentJourney()
    }

    public func abandonJourney(_ reason: String? = nil, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        currentJourneyStatus = "abandoned"
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["abandonmentReason"] = AnyCodable(reason ?? ""); props["journeyStatus"] = AnyCodable("abandoned")
        enqueueEvent(type: .journey_abandoned, properties: props); clearCurrentJourney()
    }

    public func checkpointJourney(_ stepIdOrName: String, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        currentJourneyStatus = "checkpoint"
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["stepId"] = AnyCodable(stepIdOrName); props["stepName"] = AnyCodable(stepIdOrName); props["journeyStatus"] = AnyCodable("checkpoint")
        enqueueEvent(type: .journey_checkpoint, properties: props)
    }

    private func clearCurrentJourney() {
        currentJourneyId = nil; currentJourneyName = nil
        currentJourneyType = nil; currentJourneyStatus = nil
    }

    public func getCurrentJourney() -> [String: AnyCodable]? {
        guard let journeyId = currentJourneyId else { return nil }
        return ["journeyId": AnyCodable(journeyId), "journeyName": AnyCodable(currentJourneyName as Any)]
    }

    public func screenView(_ screenName: String, properties: [String: AnyCodable] = [:]) {
        screenCount += 1
        enqueueEvent(type: .screen, properties: ["screen": AnyCodable(screenName)].merging(properties) { _, new in new })
    }

    public func conversion(_ event: String, value: Double? = nil, properties: [String: AnyCodable] = [:]) {
        var props = properties
        props["event"] = AnyCodable(event)
        if let value = value { props["value"] = AnyCodable(value) }
        enqueueEvent(type: .conversion, properties: props)
    }

    public func hydrateIdentity(_ data: IdentityData) {
        let priorUserId = self.userId
        let priorEmail = self.email
        if let userId = data.userId { self.userId = userId }
        if let em = data.email { self.email = em }
        if let traits = data.traits { self.traits.merge(traits) { _, new in new } }
        if let addr = data.walletAddress {
            walletAddress = addr
            defaults.set(addr, forKey: "walletAddress")
        }
        // Multi-wallet: connect each as a proper wallet event
        for w in data.wallets {
            walletConnected(address: w.address, walletType: w.walletType, chainId: w.chainId)
        }

        enqueueEvent(type: .identify, properties: [
            "userId":       AnyCodable(userId ?? ""),
            "traits":       AnyCodable(traits),
            "walletAddress": AnyCodable(data.walletAddress ?? ""),
            "walletsCount": AnyCodable(data.wallets.count),
            "wallets": AnyCodable(data.wallets.map { ["address": $0.address, "vm": $0.vm, "walletType": $0.walletType] }),
        ])

        defaults.set(userId, forKey: "userId")

        // Cross-device: fire resolve when userId or email just became known
        if config?.autoResumeJourney == true {
            let uidChanged = self.userId != nil && self.userId != priorUserId
            let emailChanged = self.email != nil && self.email != priorEmail
            if uidChanged || emailChanged {
                resolveIdentity(walletAddress: walletAddress, userId: self.userId, email: self.email)
            }
        }
    }

    public func getAnonymousId() -> String { anonymousId }
    public func getUserId() -> String? { userId }
    public func getFingerprintId() -> String { fingerprintId }

    public func reset() {
        flush()
        userId = nil
        walletAddress = nil
        email = nil
        traits = [:]
        consentState = []
        anonymousId = UUID().uuidString
        sessionId = UUID().uuidString
        eventSequence = 0
        // Acquisition attribution is identity-scoped state: logout/reset
        // clears campaign context and both persisted acquisition touches.
        campaignInfo = nil
        firstTouchEvidence = nil
        latestTouchEvidence = nil
        defaults.removeObject(forKey: "userId")
        defaults.removeObject(forKey: "walletAddress")
        defaults.removeObject(forKey: "consentState")
        defaults.removeObject(forKey: Aether.firstTouchDefaultsKey)
        defaults.removeObject(forKey: Aether.latestTouchDefaultsKey)
        defaults.set(anonymousId, forKey: "anonymousId")
        log("SDK reset")
    }

    public func flush() {
        serialQueue.async { [weak self] in
            self?.sendBatch()
        }
    }

    // MARK: - Durable Queue Persistence

    private var persistedQueueURL: URL? {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first?
            .appendingPathComponent("com.aether.sdk", isDirectory: true)
            .appendingPathComponent("event_queue.json")
    }

    private func persistQueue() {
        serialQueue.async { [weak self] in self?.persistQueueLocked() }
    }

    private func persistQueueLocked() {
        guard let url = persistedQueueURL else { return }
        if eventQueue.isEmpty {
            try? FileManager.default.removeItem(at: url)
            return
        }
        do {
            let directory = url.deletingLastPathComponent()
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
            let envelope = PersistedQueueEnvelope(
                version: 1,
                savedAt: ISO8601DateFormatter().string(from: Date()),
                events: Array(eventQueue.suffix(Aether.maxQueueSize))
            )
            let data = try JSONEncoder().encode(envelope)
            try data.write(to: url, options: .atomic)
        } catch {
            log("Failed to persist durable queue: \(type(of: error))")
        }
    }

    private func loadPersistedQueue() {
        guard let url = persistedQueueURL,
              FileManager.default.fileExists(atPath: url.path) else { return }
        do {
            let data = try Data(contentsOf: url)
            let decoder = JSONDecoder()
            let events: [AetherEvent]
            if let envelope = try? decoder.decode(PersistedQueueEnvelope.self, from: data) {
                guard envelope.version == 1 else {
                    throw CocoaError(.fileReadCorruptFile)
                }
                events = envelope.events
            } else {
                events = try decoder.decode([AetherEvent].self, from: data)
            }
            serialQueue.async { [weak self] in
                guard let self = self else { return }
                let capacity = max(0, Aether.maxQueueSize - self.eventQueue.count)
                let restored = Array(events.prefix(capacity))
                self.eventQueue.insert(contentsOf: restored, at: 0)
                self.persistQueueLocked()
                self.log("Restored \(restored.count) events from durable queue")
            }
        } catch {
            let quarantine = url.deletingPathExtension()
                .appendingPathExtension("corrupt.\(Int(Date().timeIntervalSince1970))")
            try? FileManager.default.moveItem(at: url, to: quarantine)
            log("Quarantined corrupt durable queue: \(type(of: error))")
        }
    }

    private func requeueBatch(_ batch: [AetherEvent]) {
        serialQueue.async { [weak self] in
            guard let self = self else { return }
            self.eventQueue = Array(
                (batch + self.eventQueue).prefix(Aether.maxQueueSize)
            )
            self.persistQueueLocked()
        }
    }

    private func clearPersistedQueue() {
        if let url = persistedQueueURL { try? FileManager.default.removeItem(at: url) }
    }

    // MARK: - Deep Link / Universal Link Attribution
    //
    // Integration (UIKit AppDelegate):
    //
    //     func application(_ app: UIApplication, open url: URL,
    //                      options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
    //         Aether.shared.handleDeepLink(url)          // custom scheme (myapp://…)
    //         return true
    //     }
    //     func application(_ application: UIApplication,
    //                      continue userActivity: NSUserActivity,
    //                      restorationHandler: @escaping ([UIUserActivityRestoring]?) -> Void) -> Bool {
    //         return Aether.shared.handleUniversalLink(userActivity)
    //     }
    //
    // Integration (SceneDelegate — covers BOTH cold start and warm start):
    //
    //     func scene(_ scene: UIScene, willConnectTo session: UISceneSession,
    //                options connectionOptions: UIScene.ConnectionOptions) {
    //         // Cold start
    //         connectionOptions.userActivities.forEach { Aether.shared.handleUniversalLink($0) }
    //         connectionOptions.urlContexts.forEach { Aether.shared.handleDeepLink($0.url) }
    //     }
    //     func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
    //         Aether.shared.handleUniversalLink(userActivity)   // warm start
    //     }
    //     func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
    //         URLContexts.forEach { Aether.shared.handleDeepLink($0.url) }
    //     }
    //
    // Both cold- and warm-start paths funnel into processIncomingURL, which
    // dedupes identical URL deliveries inside a short window, so wiring every
    // delegate callback is safe (no double deep_link_opened events).

    /// Handle a custom-scheme deep link (`myapp://…`). Entry method is
    /// recorded as the canonical `ios_custom_url`.
    public func handleDeepLink(_ url: URL) {
        processIncomingURL(url, entryMethod: "ios_custom_url")
    }

    /// Handle a Universal Link handoff (`NSUserActivityTypeBrowsingWeb`).
    /// Returns `true` when the activity carried a web URL the SDK consumed as
    /// acquisition evidence (entry method `ios_universal_link`); `false` lets
    /// the caller fall through to its own activity handling.
    @discardableResult
    public func handleUniversalLink(_ userActivity: NSUserActivity) -> Bool {
        guard userActivity.activityType == NSUserActivityTypeBrowsingWeb,
              let url = userActivity.webpageURL else {
            return false
        }
        processIncomingURL(url, entryMethod: "ios_universal_link")
        return true
    }

    /// Route an arbitrary incoming URL string context (React Native bridge and
    /// other host-managed link routers). http(s) URLs are Universal Links;
    /// everything else is a custom URL scheme.
    public func handleURL(_ url: URL) {
        let scheme = url.scheme?.lowercased()
        let entryMethod = (scheme == "http" || scheme == "https")
            ? "ios_universal_link"
            : "ios_custom_url"
        processIncomingURL(url, entryMethod: entryMethod)
    }

    /// Attribute a QR code the host app has ALREADY decoded. The SDK does not
    /// access the camera or decode images — the host app owns the scan and
    /// hands the SDK the decoded URL. Routed through the SAME canonical
    /// evidence parser as deep links (entry method `qr_code`): the URL is
    /// sanitized, `aether_ref`/UTM/click IDs are parsed, destinationDomain is
    /// set, and first/latest-touch evidence is persisted. Emits
    /// `qr_code_scanned`.
    public func handleQrScanResult(_ url: URL) {
        processIncomingURL(url, entryMethod: "qr_code", eventType: .qr_code_scanned)
    }

    /// Attribute an NFC tag URI the host app has ALREADY read (e.g. via
    /// CoreNFC). The SDK does not drive the NFC radio. Routed through the
    /// canonical evidence parser (entry method `nfc`) with the same
    /// sanitization and first/latest-touch persistence as deep links. Emits
    /// `nfc_tag_read`.
    public func handleNfcUri(_ url: URL) {
        processIncomingURL(url, entryMethod: "nfc", eventType: .nfc_tag_read)
    }

    /// Handle an App Clip invocation delivered as an `NSUserActivity`
    /// (`NSUserActivityTypeBrowsingWeb`, entry method `ios_universal_link`).
    /// First-touch evidence is persisted so a subsequent full-app install
    /// inherits the acquisition source via the existing deferred-handoff /
    /// first-touch path. Emits `app_clip_invoked`. Returns `true` when a web
    /// URL was consumed.
    @discardableResult
    public func handleAppClipInvocation(_ userActivity: NSUserActivity) -> Bool {
        guard userActivity.activityType == NSUserActivityTypeBrowsingWeb,
              let url = userActivity.webpageURL else {
            return false
        }
        processIncomingURL(url, entryMethod: "ios_universal_link", eventType: .app_clip_invoked)
        return true
    }

    /// Handle an App Clip invocation URL directly (when the host obtained the
    /// invocation URL outside an `NSUserActivity`). Recorded with entry method
    /// `manual_sdk_evidence`; first-touch is persisted for full-app handoff.
    /// Emits `app_clip_invoked`.
    public func handleAppClipInvocation(url: URL) {
        processIncomingURL(url, entryMethod: "manual_sdk_evidence", eventType: .app_clip_invoked)
    }

    /// Single processing funnel for every incoming deep/universal link:
    /// URL+timestamp dedup → canonical evidence parse → campaign context →
    /// first/latest-touch persistence → `deep_link_opened` emission.
    private func processIncomingURL(
        _ url: URL,
        entryMethod: String,
        eventType: AetherEventType = .deep_link_opened,
        at date: Date = Date()
    ) {
        guard isInitialized, config?.modules.deepLinkAttribution != false else { return }

        // Dedup: cold-start and warm-start delegate paths often deliver the
        // same URL twice within the same launch.
        let dedupKey = url.absoluteString
        var isDuplicate = false
        serialQueue.sync {
            processedIncomingURLs = processedIncomingURLs.filter {
                date.timeIntervalSince($0.value) < Aether.incomingURLDedupWindow
            }
            if let last = processedIncomingURLs[dedupKey],
               date.timeIntervalSince(last) < Aether.incomingURLDedupWindow {
                isDuplicate = true
            } else {
                processedIncomingURLs[dedupKey] = date
            }
        }
        if isDuplicate {
            log("Ignoring duplicate incoming URL delivery")
            return
        }

        let parsed = parseAcquisitionEvidence(from: url, entryMethod: entryMethod, at: date)

        // CampaignInfo keeps the declared UTM fields and click IDs, but a deep
        // link's host is where the user LANDED (destinationDomain), never who
        // referred them — referrerDomain must stay nil here.
        self.campaignInfo = EventContext.CampaignInfo(
            source: parsed.evidence["utmSource"]?.value as? String,
            medium: parsed.evidence["utmMedium"]?.value as? String,
            campaign: parsed.evidence["utmCampaign"]?.value as? String,
            content: parsed.evidence["utmContent"]?.value as? String,
            term: parsed.evidence["utmTerm"]?.value as? String,
            clickIds: parsed.clickIds,
            referrerDomain: nil
        )

        recordAcquisitionTouch(parsed.evidence, at: date)

        var properties: [String: AnyCodable] = [
            "url": AnyCodable(parsed.sanitizedURL),
            "entryMethod": AnyCodable(entryMethod),
        ]
        for key in ["utmSource", "utmMedium", "utmCampaign", "utmContent", "utmTerm", "utmId"] {
            if let value = parsed.evidence[key]?.value as? String {
                properties[key] = AnyCodable(value)
            }
        }
        if let host = parsed.evidence["destinationDomain"]?.value as? String {
            properties["destinationDomain"] = AnyCodable(host)
        }
        if !parsed.clickIds.isEmpty {
            properties["clickIds"] = AnyCodable(parsed.clickIds.mapValues { AnyCodable($0) })
        }
        enqueueEvent(type: eventType, properties: properties)
    }

    /// Parsed representation of one incoming link observation.
    struct ParsedIncomingURL {
        /// Shared AcquisitionEvidence (schema v3) as a wire-shaped dictionary.
        let evidence: [String: AnyCodable]
        /// Click IDs preserved for CampaignInfo/audit.
        let clickIds: [String: String]
        /// URL with the opaque `aether_ref` token stripped — the token only
        /// travels inside evidence.referralToken, never in raw URL strings.
        let sanitizedURL: String
    }

    /// Canonical evidence parser: one URL in, one AcquisitionEvidence
    /// (schema v3) dictionary out. The SDK observes; it never classifies.
    func parseAcquisitionEvidence(
        from url: URL,
        entryMethod: String,
        at date: Date = Date()
    ) -> ParsedIncomingURL {
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        var evidence: [String: AnyCodable] = [
            "schemaVersion": AnyCodable(Aether.acquisitionEvidenceSchemaVersion),
            "entryMethod": AnyCodable(entryMethod),
        ]
        var clickIds: [String: String] = [:]

        let utmKeyMap: [String: String] = [
            "utm_source": "utmSource",
            "utm_medium": "utmMedium",
            "utm_campaign": "utmCampaign",
            "utm_content": "utmContent",
            "utm_term": "utmTerm",
            "utm_id": "utmId",
        ]

        for item in components?.queryItems ?? [] {
            let name = item.name.lowercased()
            if let mapped = utmKeyMap[name], let value = item.value, !value.isEmpty {
                evidence[mapped] = AnyCodable(value)
            } else if Self.clickIdParams.contains(name), let value = item.value, !value.isEmpty {
                clickIds[name] = value
            } else if name == "aether_ref", let value = item.value, !value.isEmpty {
                // Opaque referral token: captured as-is, verified server-side.
                evidence["referralToken"] = AnyCodable(value)
            } else if name == "aether_cid", let value = item.value, !value.isEmpty {
                // Explicit Aether campaign UUID — always validated server-side.
                evidence["canonicalCampaignId"] = AnyCodable(value)
            }
        }
        if !clickIds.isEmpty {
            evidence["clickIds"] = AnyCodable(clickIds.mapValues { AnyCodable($0) })
        }

        // destinationDomain is the host the user LANDED on. It is not a
        // referrer and is never surfaced as referrerDomain.
        if let host = components?.host, !host.isEmpty {
            evidence["destinationDomain"] = AnyCodable(host)
        }
        let path = url.path
        if !path.isEmpty && path != "/" {
            let digest = DeviceFingerprint.sha256(path)
            evidence["destinationPathHash"] = AnyCodable(
                String(digest.prefix(Aether.destinationPathHashLength))
            )
        }

        // Strip the opaque referral token from the transmitted URL string.
        var sanitizedComponents = components
        if let items = components?.queryItems {
            let kept = items.filter { $0.name.lowercased() != "aether_ref" }
            sanitizedComponents?.queryItems = kept.isEmpty ? nil : kept
        }
        let sanitizedURL = sanitizedComponents?.url?.absoluteString ?? url.absoluteString
        evidence["landingPage"] = AnyCodable(sanitizedURL)

        let observedAt = ISO8601DateFormatter().string(from: date)
        evidence["firstCapturedAt"] = AnyCodable(observedAt)
        evidence["lastObservedAt"] = AnyCodable(observedAt)
        evidence["evidenceExpiresAt"] = AnyCodable(
            ISO8601DateFormatter().string(from: date.addingTimeInterval(Aether.acquisitionEvidenceTTL))
        )

        return ParsedIncomingURL(
            evidence: evidence,
            clickIds: clickIds,
            sanitizedURL: sanitizedURL
        )
    }

    // MARK: - First / Latest Touch Persistence

    /// Persist a fresh observation: latest touch always advances; first touch
    /// is written only when none exists (or the stored one has expired), so a
    /// later, weaker observation can never overwrite the original first touch.
    private func recordAcquisitionTouch(_ evidence: [String: AnyCodable], at date: Date = Date()) {
        var latest = evidence
        latest["firstTouch"] = AnyCodable(false)
        latestTouchEvidence = latest
        persistEvidence(latest, forKey: Aether.latestTouchDefaultsKey)

        let existingFirst = firstTouchEvidence
        if existingFirst == nil || isEvidenceExpired(existingFirst!, at: date) {
            var first = evidence
            first["firstTouch"] = AnyCodable(true)
            firstTouchEvidence = first
            persistEvidence(first, forKey: Aether.firstTouchDefaultsKey)
        }
    }

    private func persistEvidence(_ evidence: [String: AnyCodable], forKey key: String) {
        if let data = try? JSONEncoder().encode(evidence) {
            defaults.set(data, forKey: key)
        }
    }

    private func loadPersistedEvidence(forKey key: String) -> [String: AnyCodable]? {
        guard let data = defaults.data(forKey: key),
              let decoded = try? JSONDecoder().decode([String: AnyCodable].self, from: data),
              (decoded["schemaVersion"]?.value as? Int) == Aether.acquisitionEvidenceSchemaVersion
        else { return nil }
        return decoded
    }

    func isEvidenceExpired(_ evidence: [String: AnyCodable], at date: Date = Date()) -> Bool {
        guard let raw = evidence["evidenceExpiresAt"]?.value as? String,
              let expires = ISO8601DateFormatter().date(from: raw) else {
            // Evidence persisted without an expiry is treated as expired
            // rather than attaching forever.
            return true
        }
        return expires <= date
    }

    /// The evidence stamped on outgoing event contexts: the latest unexpired
    /// touch, falling back to an unexpired first touch. Nil once expired.
    private func activeAcquisitionEvidence(at date: Date) -> [String: AnyCodable]? {
        if let latest = latestTouchEvidence, !isEvidenceExpired(latest, at: date) {
            return latest
        }
        if let first = firstTouchEvidence, !isEvidenceExpired(first, at: date) {
            return first
        }
        return nil
    }

    /// First-touch acquisition evidence as a JSON string (nil when absent or
    /// expired). Used by the React Native bridge.
    public func getFirstTouchAttributionJSON() -> String? {
        guard let first = firstTouchEvidence, !isEvidenceExpired(first) else { return nil }
        guard let data = try? JSONEncoder().encode(first) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    /// Latest-touch acquisition evidence as a JSON string (nil when absent or
    /// expired). Used by the React Native bridge.
    public func getLatestTouchAttributionJSON() -> String? {
        guard let latest = latestTouchEvidence, !isEvidenceExpired(latest) else { return nil }
        guard let data = try? JSONEncoder().encode(latest) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    // MARK: - Deferred Attribution (deterministic server handoff)

    /// Resolve a deterministic deferred-attribution handoff.
    ///
    /// iOS has no Android-style install referrer: deferred attribution is only
    /// possible when the pre-install surface registered a handoff server-side
    /// and the app can present the SAME explicit identifier (e.g. a code the
    /// user typed, or an identifier carried through a deterministic channel).
    /// The SDK never fingerprints its way to a match — an unmatched install
    /// simply stays Direct / Unknown server-side, and no event is emitted.
    ///
    /// On a resolved response the returned evidence is stored as the first
    /// touch (only if none exists yet) and `deferred_attribution_resolved`
    /// is emitted.
    public func resolveDeferredHandoff(identifier: String, completion: @escaping (Bool) -> Void) {
        let trimmed = identifier.trimmingCharacters(in: .whitespacesAndNewlines)
        guard isInitialized, let config = config, !trimmed.isEmpty,
              let url = URL(string: "\(config.endpoint)/v1/attribution/deferred/resolve") else {
            completion(false)
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("ios", forHTTPHeaderField: "X-Aether-SDK")
        request.timeoutInterval = 10.0
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["identifier": trimmed])

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self = self else { return }
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard error == nil, (200...299).contains(statusCode),
                  let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let resolved = json["resolved"] as? Bool, resolved,
                  let serverEvidence = json["evidence"] as? [String: Any] else {
                // Unmatched, expired, or failed: uniformly no event and no
                // stored evidence — the install stays Direct / Unknown.
                completion(false)
                return
            }

            let now = Date()
            let evidence = self.evidenceFromDeferredResolution(serverEvidence, at: now)
            self.serialQueue.sync {
                // Deferred evidence becomes the first touch ONLY when no
                // unexpired first touch exists — never an overwrite.
                if self.firstTouchEvidence == nil
                    || self.isEvidenceExpired(self.firstTouchEvidence!, at: now) {
                    var first = evidence
                    first["firstTouch"] = AnyCodable(true)
                    self.firstTouchEvidence = first
                    self.persistEvidence(first, forKey: Aether.firstTouchDefaultsKey)
                }
            }

            var properties: [String: AnyCodable] = [
                "entryMethod": AnyCodable("verified_source_link"),
                "proofLevel": AnyCodable("server_observed"),
            ]
            if let source = serverEvidence["source"] as? String { properties["source"] = AnyCodable(source) }
            if let medium = serverEvidence["medium"] as? String { properties["medium"] = AnyCodable(medium) }
            if let sourceClass = serverEvidence["source_class"] as? String { properties["sourceClass"] = AnyCodable(sourceClass) }
            if let placement = serverEvidence["placement"] as? String { properties["placement"] = AnyCodable(placement) }
            self.enqueueEvent(type: .deferred_attribution_resolved, properties: properties)
            completion(true)
        }.resume()
    }

    /// Map the server's snake_case deferred-resolution evidence into the
    /// shared AcquisitionEvidence (schema v3) wire shape.
    private func evidenceFromDeferredResolution(
        _ server: [String: Any],
        at date: Date
    ) -> [String: AnyCodable] {
        let observedAt = ISO8601DateFormatter().string(from: date)
        var evidence: [String: AnyCodable] = [
            "schemaVersion": AnyCodable(Aether.acquisitionEvidenceSchemaVersion),
            "entryMethod": AnyCodable("verified_source_link"),
            "firstCapturedAt": AnyCodable(observedAt),
            "lastObservedAt": AnyCodable(observedAt),
            "evidenceExpiresAt": AnyCodable(
                ISO8601DateFormatter().string(from: date.addingTimeInterval(Aether.acquisitionEvidenceTTL))
            ),
        ]
        let passthrough: [(server: String, wire: String)] = [
            ("source", "utmSource"),
            ("medium", "utmMedium"),
            ("utm_source", "utmSource"),
            ("utm_medium", "utmMedium"),
            ("utm_campaign", "utmCampaign"),
            ("utm_content", "utmContent"),
            ("utm_term", "utmTerm"),
            ("campaign_id", "campaignId"),
            ("link_id", "verifiedReferralLinkId"),
            ("placement", "placement"),
            ("source_class", "sourceClass"),
            ("proof_level", "proofLevel"),
        ]
        for (serverKey, wireKey) in passthrough {
            if let value = server[serverKey] as? String, !value.isEmpty {
                evidence[wireKey] = AnyCodable(value)
            }
        }
        return evidence
    }

    // MARK: - Push Notification

    public func trackPushOpened(userInfo: [AnyHashable: Any]) {
        var props: [String: AnyCodable] = [:]
        if let campaignId = userInfo["campaign_id"] as? String {
            props["campaignId"] = AnyCodable(campaignId)
        }
        track("push_notification_opened", properties: props)
    }

    // MARK: - Wallet Tracking

    public func walletConnected(address: String, walletType: String? = nil, chainId: String? = nil) {
        let normalized = normalizeWalletAddress(address)
        walletAddress = normalized
        defaults.set(normalized, forKey: "walletAddress")
        enqueueEvent(type: .wallet, properties: [
            "action": AnyCodable("connect"),
            "address": AnyCodable(normalized),
            "walletType": AnyCodable(walletType ?? "unknown"),
            "chainId": AnyCodable(chainId ?? "unknown")
        ])
        if config?.autoResumeJourney == true {
            resolveIdentity(walletAddress: normalized, userId: userId, email: email)
        }
    }

    public func walletDisconnected(address: String) {
        enqueueEvent(type: .wallet, properties: [
            "action": AnyCodable("disconnect"),
            "address": AnyCodable(address)
        ])
    }

    public func walletTransaction(txHash: String, chainId: String, value: String? = nil, properties: [String: AnyCodable]? = nil) {
        var props: [String: AnyCodable] = [
            "action": AnyCodable("transaction"),
            "txHash": AnyCodable(txHash),
            "chainId": AnyCodable(chainId)
        ]
        if let value = value { props["value"] = AnyCodable(value) }
        if let extra = properties { props.merge(extra) { _, new in new } }
        enqueueEvent(type: .transaction, properties: props)
    }

    public func contractAction(contract: String, action: String, vm: String = "evm", properties: [String: AnyCodable] = [:]) {
        var props = properties
        props["contract"] = AnyCodable(contract); props["action"] = AnyCodable(action); props["vm"] = AnyCodable(vm)
        enqueueEvent(type: .contract_action, properties: props)
    }

    // MARK: - Apple Pay Tracking
    // Call from PKPaymentAuthorizationControllerDelegate callbacks.

    public func trackApplePayPayment(
        status: String,
        amount: Double? = nil,
        currency: String? = nil,
        properties: [String: AnyCodable]? = nil
    ) {
        var props: [String: AnyCodable] = [
            "action":   AnyCodable(status),
            "provider": AnyCodable("apple_pay")
        ]
        if let amount = amount   { props["amount"]   = AnyCodable(amount) }
        if let currency = currency { props["currency"] = AnyCodable(currency) }
        if let extra = properties  { props.merge(extra) { _, new in new } }
        let eventType: AetherEventType
        switch status {
        case "completed": eventType = .payment_completed
        case "failed":    eventType = .payment_failed
        default:          eventType = .payment_initiated
        }
        enqueueEvent(type: eventType, properties: props)
    }

    // MARK: - WalletConnect Tracking
    // Call after a WalletConnect v2 session is established or resumed.

    public func trackWalletConnectSession(
        topic: String,
        address: String? = nil,
        chainId: String? = nil,
        properties: [String: AnyCodable]? = nil
    ) {
        var props: [String: AnyCodable] = [
            "action":   AnyCodable("walletconnect_session"),
            "topic":    AnyCodable(topic),
            "provider": AnyCodable("walletconnect")
        ]
        if let address = address   { props["address"]  = AnyCodable(normalizeWalletAddress(address)) }
        if let chainId = chainId   { props["chainId"]  = AnyCodable(chainId) }
        if let extra = properties  { props.merge(extra) { _, new in new } }
        if let address = address {
            walletConnected(address: address, walletType: "walletconnect", chainId: chainId)
        } else {
            enqueueEvent(type: .wallet, properties: props)
        }
    }

    // MARK: - Wallet Capability API

    public func getWalletCapabilities() -> [String: Any] {
        return [
            "connected":    walletAddress != nil,
            "addresses":    walletAddress.map { [["address": $0, "vm": "evm", "walletType": "unknown"]] } ?? [],
            "supportedVMs": ["evm", "svm", "bitcoin", "movevm", "near", "tvm", "cosmos"],
            "applePay":     isApplePayAvailable(),
            "googlePay":    false
        ]
    }

    // MARK: - Consent Management
    //
    // Native SDK purposes supported from the canonical consent registry.
    // Callers SHOULD only pass these strings. Backend validator ignores others.

    public static let canonicalConsentPurposes: [String] =
        ["analytics", "marketing", "personalization", "web3", "agent", "commerce", "credit", "location"]

    /// Purposes that always require explicit opt-in and are never granted by grantAll().
    public static let explicitOptInPurposes: [String] = ["credit", "location"]

    public func grantConsent(categories: [String]) {
        consentState = Array(Set(consentState + categories))
        defaults.set(consentState, forKey: "consentState")
        enqueueEvent(type: .consent, properties: [
            "action": AnyCodable("grant"),
            "categories": AnyCodable(categories)
        ])
        // Start health agent when analytics consent is granted in GDPR mode (post-init opt-in flow)
        if config?.privacy.gdprMode == true && categories.contains("analytics") {
            healthAgent?.start()
        }
    }

    /// Grant all non-explicit-opt-in purposes (excludes credit and location).
    /// Call grantConsent(["credit"]) or grantConsent(["location"]) explicitly after
    /// displaying the required separate opt-in UI for those purposes.
    public func grantAll() {
        let grantable = Self.canonicalConsentPurposes.filter {
            !Self.explicitOptInPurposes.contains($0)
        }
        grantConsent(categories: grantable)
    }

    public func revokeConsent(categories: [String]) {
        consentState = consentState.filter { !categories.contains($0) }
        defaults.set(consentState, forKey: "consentState")
        enqueueEvent(type: .consent, properties: [
            "action": AnyCodable("revoke"),
            "categories": AnyCodable(categories)
        ])
    }

    public func getConsentState() -> [String] { return consentState }

    public func buildCanonicalConsentReceipt(
        _ input: CanonicalConsentReceiptInput
    ) throws -> CanonicalConsentReceipt {
        guard !input.tenantId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ConsentReceiptError.invalidInput("tenantId is required")
        }
        guard !(input.subjectId ?? "").isEmpty || !(input.anonymousId ?? "").isEmpty else {
            throw ConsentReceiptError.invalidInput("subjectId or anonymousId is required")
        }
        guard !input.purposes.isEmpty else {
            throw ConsentReceiptError.invalidInput("at least one purpose is required")
        }
        var normalized = input
        normalized.purposes = Array(Set(input.purposes)).sorted()
        let preimage = canonicalConsentReceiptPreimage(normalized)
        let digest = SHA256.hash(data: Data(preimage.utf8))
            .map { String(format: "%02x", $0) }.joined()
        return CanonicalConsentReceipt(
            receiptId: "ccr_\(digest.prefix(32))",
            integrityHash: "sha256:\(digest)",
            idempotencyKey: "consent-receipt:\(digest)",
            input: normalized
        )
    }

    public func recordConsentReceipt(
        _ input: CanonicalConsentReceiptInput,
        completion: @escaping (Result<CanonicalConsentReceipt, Error>) -> Void
    ) {
        guard let config = config else {
            completion(.failure(ConsentReceiptError.notInitialized)); return
        }
        do {
            let receipt = try buildCanonicalConsentReceipt(input)
            guard let url = URL(string: "\(config.endpoint.trimmingCharacters(in: CharacterSet(charactersIn: "/")))/v1/consent/records") else {
                completion(.failure(ConsentReceiptError.invalidEndpoint)); return
            }
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: consentReceiptRequest(receipt))
            URLSession.shared.dataTask(with: request) { _, response, error in
                if let error = error { completion(.failure(error)); return }
                let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                guard (200...299).contains(status) else {
                    completion(.failure(ConsentReceiptError.requestFailed(status))); return
                }
                completion(.success(receipt))
            }.resume()
        } catch {
            completion(.failure(error))
        }
    }

    // MARK: - Ecommerce

    public func trackProductView(_ product: [String: AnyCodable]) {
        enqueueEvent(type: .track, properties: [
            "event": AnyCodable("product_viewed"),
            "product": AnyCodable(product)
        ])
    }

    public func trackAddToCart(_ item: [String: AnyCodable]) {
        enqueueEvent(type: .track, properties: [
            "event": AnyCodable("cart_item_added"),
            "item": AnyCodable(item)
        ])
    }

    public func trackPurchase(orderId: String, total: Double, currency: String = "USD", items: [[String: AnyCodable]]? = nil) {
        var props: [String: AnyCodable] = [
            "event": AnyCodable("order_completed"),
            "orderId": AnyCodable(orderId),
            "total": AnyCodable(total),
            "currency": AnyCodable(currency)
        ]
        if let items = items { props["items"] = AnyCodable(items) }
        enqueueEvent(type: .conversion, properties: props)
    }

    public func paymentInitiated(paymentId: String, amount: Double, currency: String, properties: [String: AnyCodable] = [:]) {
        var props = properties; props["paymentId"] = AnyCodable(paymentId); props["amount"] = AnyCodable(amount); props["currency"] = AnyCodable(currency)
        enqueueEvent(type: .payment_initiated, properties: props)
    }

    public func paymentCompleted(paymentId: String, amount: Double, currency: String, properties: [String: AnyCodable] = [:]) {
        var props = properties; props["paymentId"] = AnyCodable(paymentId); props["amount"] = AnyCodable(amount); props["currency"] = AnyCodable(currency)
        enqueueEvent(type: .payment_completed, properties: props)
    }

    public func paymentFailed(paymentId: String, reason: String, properties: [String: AnyCodable] = [:]) {
        var props = properties; props["paymentId"] = AnyCodable(paymentId); props["reason"] = AnyCodable(reason)
        enqueueEvent(type: .payment_failed, properties: props)
    }

    public func approvalRequested(approvalId: String, scope: String, properties: [String: AnyCodable] = [:]) {
        var props = properties; props["approvalId"] = AnyCodable(approvalId); props["scope"] = AnyCodable(scope)
        enqueueEvent(type: .approval_requested, properties: props)
    }

    public func approvalResolved(approvalId: String, approved: Bool, properties: [String: AnyCodable] = [:]) {
        var props = properties; props["approvalId"] = AnyCodable(approvalId); props["approved"] = AnyCodable(approved)
        enqueueEvent(type: .approval_resolved, properties: props)
    }

    public func entitlementGranted(entitlementId: String, properties: [String: AnyCodable] = [:]) { var props = properties; props["entitlementId"] = AnyCodable(entitlementId); enqueueEvent(type: .entitlement_granted, properties: props) }
    public func entitlementRevoked(entitlementId: String, properties: [String: AnyCodable] = [:]) { var props = properties; props["entitlementId"] = AnyCodable(entitlementId); enqueueEvent(type: .entitlement_revoked, properties: props) }
    public func accessGranted(resource: String, properties: [String: AnyCodable] = [:]) { var props = properties; props["resource"] = AnyCodable(resource); enqueueEvent(type: .access_granted, properties: props) }
    public func accessDenied(resource: String, reason: String, properties: [String: AnyCodable] = [:]) { var props = properties; props["resource"] = AnyCodable(resource); props["reason"] = AnyCodable(reason); enqueueEvent(type: .access_denied, properties: props) }
    public func agentTask(taskId: String, actorId: String, actorKind: String = "agent", properties: [String: AnyCodable] = [:]) { var props = properties; props["taskId"] = AnyCodable(taskId); props["actorId"] = AnyCodable(actorId); props["actorKind"] = AnyCodable(actorKind); enqueueEvent(type: .agent_task, properties: props) }
    public func agentDecision(decisionId: String, actorId: String, properties: [String: AnyCodable] = [:]) { var props = properties; props["decisionId"] = AnyCodable(decisionId); props["actorId"] = AnyCodable(actorId); enqueueEvent(type: .agent_decision, properties: props) }
    public func a2hInteraction(interactionId: String, actorId: String, properties: [String: AnyCodable] = [:]) { var props = properties; props["interactionId"] = AnyCodable(interactionId); props["actorId"] = AnyCodable(actorId); enqueueEvent(type: .a2h_interaction, properties: props) }
    public func x402Payment(paymentId: String, amount: String, currency: String, network: String, properties: [String: AnyCodable] = [:]) { var props = properties; props["paymentId"] = AnyCodable(paymentId); props["amount"] = AnyCodable(amount); props["currency"] = AnyCodable(currency); props["network"] = AnyCodable(network); enqueueEvent(type: .x402_payment, properties: props) }

    // MARK: - Agent Lifecycle (Granular)

    public func agentRegistered(agentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["agentId"] = AnyCodable(agentId); enqueueEvent(type: .agent_registered, properties: p) }
    public func agentUpdated(agentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["agentId"] = AnyCodable(agentId); enqueueEvent(type: .agent_updated, properties: p) }
    public func agentAuthorized(agentId: String, delegationId: String? = nil, properties: [String: AnyCodable] = [:]) { var p = properties; p["agentId"] = AnyCodable(agentId); if let d = delegationId { p["delegationId"] = AnyCodable(d) }; enqueueEvent(type: .agent_authorized, properties: p) }
    public func agentDeauthorized(agentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["agentId"] = AnyCodable(agentId); enqueueEvent(type: .agent_deauthorized, properties: p) }
    public func agentCapabilityGranted(agentId: String, capability: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["agentId"] = AnyCodable(agentId); p["capability"] = AnyCodable(capability); enqueueEvent(type: .agent_capability_granted, properties: p) }
    public func agentCapabilityRevoked(agentId: String, capability: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["agentId"] = AnyCodable(agentId); p["capability"] = AnyCodable(capability); enqueueEvent(type: .agent_capability_revoked, properties: p) }
    public func agentTaskCreated(taskId: String, actorId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["taskId"] = AnyCodable(taskId); p["actorId"] = AnyCodable(actorId); enqueueEvent(type: .agent_task_created, properties: p) }
    public func agentTaskDecomposed(taskId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["taskId"] = AnyCodable(taskId); enqueueEvent(type: .agent_task_decomposed, properties: p) }
    public func agentTaskStarted(taskId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["taskId"] = AnyCodable(taskId); enqueueEvent(type: .agent_task_started, properties: p) }
    public func agentTaskCompleted(taskId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["taskId"] = AnyCodable(taskId); enqueueEvent(type: .agent_task_completed, properties: p) }
    public func agentTaskFailed(taskId: String, reason: String? = nil, properties: [String: AnyCodable] = [:]) { var p = properties; p["taskId"] = AnyCodable(taskId); if let r = reason { p["reason"] = AnyCodable(r) }; enqueueEvent(type: .agent_task_failed, properties: p) }
    public func agentToolCalled(taskId: String, tool: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["taskId"] = AnyCodable(taskId); p["tool"] = AnyCodable(tool); enqueueEvent(type: .agent_tool_called, properties: p) }
    public func agentResourceRequested(resourceId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["resourceId"] = AnyCodable(resourceId); enqueueEvent(type: .agent_resource_requested, properties: p) }
    public func agentDelegatedTask(taskId: String, toAgentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["taskId"] = AnyCodable(taskId); p["toAgentId"] = AnyCodable(toAgentId); enqueueEvent(type: .agent_delegated_task, properties: p) }
    public func agentSubagentSpawned(parentId: String, childId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["parentId"] = AnyCodable(parentId); p["childId"] = AnyCodable(childId); enqueueEvent(type: .agent_subagent_spawned, properties: p) }
    public func agentPolicyEvaluated(policyId: String, outcome: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["policyId"] = AnyCodable(policyId); p["outcome"] = AnyCodable(outcome); enqueueEvent(type: .agent_policy_evaluated, properties: p) }
    public func agentHandoff(fromId: String, toId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["fromId"] = AnyCodable(fromId); p["toId"] = AnyCodable(toId); enqueueEvent(type: .agent_handoff, properties: p) }
    public func agentEscalatedToHuman(taskId: String, reason: String? = nil, properties: [String: AnyCodable] = [:]) { var p = properties; p["taskId"] = AnyCodable(taskId); if let r = reason { p["reason"] = AnyCodable(r) }; enqueueEvent(type: .agent_escalated_to_human, properties: p) }
    public func agentOutcomeRecorded(taskId: String, outcome: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["taskId"] = AnyCodable(taskId); p["outcome"] = AnyCodable(outcome); enqueueEvent(type: .agent_outcome_recorded, properties: p) }

    // MARK: - x402 Lifecycle (Granular)

    public func x402ResourceRequested(resourceId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["resourceId"] = AnyCodable(resourceId); enqueueEvent(type: .x402_resource_requested, properties: p) }
    public func x402PaymentRequired(resourceId: String, amount: Double, currency: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["resourceId"] = AnyCodable(resourceId); p["amount"] = AnyCodable(amount); p["currency"] = AnyCodable(currency); enqueueEvent(type: .x402_payment_required, properties: p) }
    public func x402QuoteReceived(quoteId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["quoteId"] = AnyCodable(quoteId); enqueueEvent(type: .x402_quote_received, properties: p) }
    public func x402AuthorizationRequested(paymentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["paymentId"] = AnyCodable(paymentId); enqueueEvent(type: .x402_authorization_requested, properties: p) }
    public func x402AuthorizationResolved(paymentId: String, authorized: Bool, properties: [String: AnyCodable] = [:]) { var p = properties; p["paymentId"] = AnyCodable(paymentId); p["authorized"] = AnyCodable(authorized); enqueueEvent(type: .x402_authorization_resolved, properties: p) }
    public func x402PaymentIntentCreated(intentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["intentId"] = AnyCodable(intentId); enqueueEvent(type: .x402_payment_intent_created, properties: p) }
    public func x402PaymentSubmitted(paymentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["paymentId"] = AnyCodable(paymentId); enqueueEvent(type: .x402_payment_submitted, properties: p) }
    public func x402PaymentSettled(paymentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["paymentId"] = AnyCodable(paymentId); enqueueEvent(type: .x402_payment_settled, properties: p) }
    public func x402PaymentFailed(paymentId: String, reason: String? = nil, properties: [String: AnyCodable] = [:]) { var p = properties; p["paymentId"] = AnyCodable(paymentId); if let r = reason { p["reason"] = AnyCodable(r) }; enqueueEvent(type: .x402_payment_failed, properties: p) }
    public func x402PaymentTimeout(paymentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["paymentId"] = AnyCodable(paymentId); enqueueEvent(type: .x402_payment_timeout, properties: p) }
    public func x402ReceiptVerified(receiptId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["receiptId"] = AnyCodable(receiptId); enqueueEvent(type: .x402_receipt_verified, properties: p) }
    public func x402AccessGranted(resourceId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["resourceId"] = AnyCodable(resourceId); enqueueEvent(type: .x402_access_granted, properties: p) }
    public func x402AccessDenied(resourceId: String, reason: String? = nil, properties: [String: AnyCodable] = [:]) { var p = properties; p["resourceId"] = AnyCodable(resourceId); if let r = reason { p["reason"] = AnyCodable(r) }; enqueueEvent(type: .x402_access_denied, properties: p) }
    public func x402RefundOrReversal(paymentId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["paymentId"] = AnyCodable(paymentId); enqueueEvent(type: .x402_refund_or_reversal, properties: p) }

    // MARK: - Rewards (Thin Observation Emitters)

    public func rewardActionQueued(campaignId: String, ruleId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["campaignId"] = AnyCodable(campaignId); p["ruleId"] = AnyCodable(ruleId); enqueueEvent(type: .reward_action_queued, properties: p) }
    public func rewardProofGenerated(campaignId: String, proofId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["campaignId"] = AnyCodable(campaignId); p["proofId"] = AnyCodable(proofId); enqueueEvent(type: .reward_proof_generated, properties: p) }
    public func rewardDelivered(campaignId: String, rewardId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["campaignId"] = AnyCodable(campaignId); p["rewardId"] = AnyCodable(rewardId); enqueueEvent(type: .reward_delivered, properties: p) }
    public func rewardClaimSubmitted(campaignId: String, claimId: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["campaignId"] = AnyCodable(campaignId); p["claimId"] = AnyCodable(claimId); enqueueEvent(type: .reward_claim_submitted, properties: p) }

    // MARK: - Ecommerce Additions

    public func trackRemoveFromCart(_ item: [String: AnyCodable]) { enqueueEvent(type: .track, properties: ["event": AnyCodable("cart_item_removed"), "item": AnyCodable(item)]) }
    public func trackApplyCoupon(_ couponCode: String, properties: [String: AnyCodable] = [:]) { var p = properties; p["event"] = AnyCodable("coupon_applied"); p["couponCode"] = AnyCodable(couponCode); enqueueEvent(type: .track, properties: p) }
    public func trackBeginCheckout(cartValue: Double, currency: String = "USD", properties: [String: AnyCodable] = [:]) { var p = properties; p["event"] = AnyCodable("checkout_started"); p["cartValue"] = AnyCodable(cartValue); p["currency"] = AnyCodable(currency); enqueueEvent(type: .conversion, properties: p) }

    // MARK: - Feature Flags (from server config)

    public func isFeatureEnabled(_ key: String, default defaultValue: Bool = false) -> Bool {
        // Manifest overrides win over server config flags — this mirrors the
        // JS RemoteManifest module (packages/react-native/src/modules/RemoteManifest.ts),
        // which pushes manifest flags/features into RNFeatureFlags via
        // setOverride(): an override that supersedes the underlying value.
        if let manifestValue = manifestFeatureOverrides[key] { return manifestValue }
        guard let flags = serverConfig["featureFlags"] as? [String: Any],
              let value = flags[key] as? Bool else { return defaultValue }
        return value
    }

    /// Sampling decision for the manifest-driven rollout gate (Truth Kernel
    /// remote config). Pure/stateless so it can be tested deterministically —
    /// `roll` is injectable and defaults to the platform RNG in production
    /// call sites. Mirrors the JS RemoteManifest sampling convention
    /// (packages/react-native/src/modules/RemoteManifest.ts): keep the event
    /// when `roll < rate`.
    static func shouldSample(rate: Double, roll: Double = Double.random(in: 0..<1)) -> Bool {
        roll < rate
    }

    public func getFeatureValue(_ key: String, default defaultValue: Any? = nil) -> Any? {
        guard let flags = serverConfig["featureFlags"] as? [String: Any] else { return defaultValue }
        return flags[key] ?? defaultValue
    }

    // MARK: - Private

    private func enqueueEvent(type: AetherEventType, properties: [String: AnyCodable]) {
        guard isInitialized else { return }
        guard let purpose = Self.eventConsentPurpose[type] else {
            log("Dropping non-canonical event type: \(type.rawValue). Use track(_:properties:) for custom events.")
            return
        }
        let gdprMode = config?.privacy.gdprMode ?? false
        if type != .consent && gdprMode && !consentState.contains(purpose) {
            log("Dropping \(type.rawValue) before enqueue because \(purpose) consent is not granted")
            // Consent gating is intentional, not a delivery failure — it is
            // surfaced as the BatchHealth.droppedByConsent counter (§2.8).
            serialQueue.async { [weak self] in self?.pendingConsentDrops += 1 }
            healthAgent?.recordDroppedEvents(1)
            return
        }

        // Manifest-driven rollout sampling gate (Truth Kernel remote config).
        // Consent gating above is unchanged; this only applies once a
        // manifest with rollout_percentage < 100 has been fetched, verified,
        // and applied via onManifestUpdate.
        let rate = samplingRate
        if rate < 1.0 && !Aether.shouldSample(rate: rate) {
            log("Dropping \(type.rawValue) — sampled out by remote rollout gate (rate=\(rate))")
            return
        }

        let scrubbedProps = scrubSensitiveFields(properties)
        // Single occurrence instant shared by the timestamp and the temporal
        // provenance so zone/offset evidence matches the stamped clock reading.
        let eventDate = Date()
        let event = AetherEvent(
            id: UUID().uuidString,
            type: type,
            timestamp: ISO8601DateFormatter().string(from: eventDate),
            sessionId: sessionId,
            anonymousId: anonymousId,
            userId: userId,
            properties: scrubbedProps,
            context: buildContext(at: eventDate)
        )

        serialQueue.async { [weak self] in
            guard let self = self else { return }
            // Enforce max queue size
            while self.eventQueue.count >= Aether.maxQueueSize { self.eventQueue.removeFirst() }
            self.eventQueue.append(event)
            self.eventCount += 1
            self.persistQueueLocked()
            if let batchSize = self.config?.batchSize, self.eventQueue.count >= batchSize {
                self.sendBatch()
            }
        }
    }

    private func sendBatch() {
        guard !eventQueue.isEmpty, let config = config else { return }

        let batch = Array(eventQueue.prefix(config.batchSize))
        eventQueue.removeFirst(min(batch.count, eventQueue.count))
        persistQueueLocked()

        sendBatchWithRetry(batch: batch, config: config, retryCount: 0)
    }

    private func sendBatchWithRetry(batch: [AetherEvent], config: AetherConfig, retryCount: Int) {
        let maxRetries = 3
        guard let url = URL(string: "\(config.endpoint)/v1/batch") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(config.apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("ios", forHTTPHeaderField: "X-Aether-SDK")
        request.timeoutInterval = 10.0

        let encodedBatch = batch.map { try? JSONEncoder().encode($0) }
            .compactMap { $0 }
            .map { try? JSONSerialization.jsonObject(with: $0) }
            .compactMap { $0 }
        let payload: [String: Any] = ["batch": encodedBatch, "sentAt": ISO8601DateFormatter().string(from: Date())]
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self = self else { return }
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0

            if let error = error {
                self.log("Batch send failed: \(error.localizedDescription)")
                if retryCount < maxRetries {
                    let delay = min(pow(2.0, Double(retryCount)), 30.0)
                    DispatchQueue.global().asyncAfter(deadline: .now() + delay) {
                        self.sendBatchWithRetry(batch: batch, config: config, retryCount: retryCount + 1)
                    }
                } else {
                    self.requeueBatch(batch)
                }
            } else if statusCode == 429 {
                let retryAfter = (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Retry-After")
                    .flatMap { Double($0) } ?? 5.0
                if retryCount < maxRetries {
                    DispatchQueue.global().asyncAfter(deadline: .now() + retryAfter) {
                        self.sendBatchWithRetry(batch: batch, config: config, retryCount: retryCount + 1)
                    }
                } else {
                    self.requeueBatch(batch)
                    self.log("Batch retained after \(maxRetries) retries (rate limited)")
                }
            } else if statusCode >= 500 || statusCode == 408 || statusCode == 425 {
                // 408 (Request Timeout) and 425 (Too Early) are transient like
                // 5xx, so they share the same exponential backoff instead of
                // being dropped as terminal client errors.
                if retryCount < maxRetries {
                    let delay = min(pow(2.0, Double(retryCount)), 30.0)
                    DispatchQueue.global().asyncAfter(deadline: .now() + delay) {
                        self.sendBatchWithRetry(batch: batch, config: config, retryCount: retryCount + 1)
                    }
                } else {
                    self.requeueBatch(batch)
                    self.log("Batch retained after \(maxRetries) retries (retryable error \(statusCode))")
                }
            } else if statusCode >= 400 {
                self.persistQueue()
                self.healthAgent?.recordDroppedEvents(batch.count)
                self.log("Batch rejected (client error \(statusCode)) — not retrying")
            } else {
                self.persistQueue()
                self.emitBatchHealth(sentCount: batch.count, responseBody: data)
            }
        }.resume()
    }

    /// Parse per-batch acceptance counters from the /v1/batch response body and
    /// surface a BatchHealth via `onBatchResult` (Truth Kernel §2.8). The backend
    /// BatchResponse uses `accepted` / `duplicates` / `rejected`; the singular
    /// `duplicate` is also accepted. Falls back to treating the whole batch as
    /// accepted when the body is absent or unparseable.
    private func emitBatchHealth(sentCount: Int, responseBody: Data?) {
        guard onBatchResult != nil else { return }
        var accepted = sentCount
        var duplicate = 0
        var rejected = 0
        if let data = responseBody,
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let a = (json["accepted"] as? NSNumber)?.intValue { accepted = a }
            if let d = (json["duplicate"] as? NSNumber)?.intValue ?? (json["duplicates"] as? NSNumber)?.intValue { duplicate = d }
            if let r = (json["rejected"] as? NSNumber)?.intValue { rejected = r }
        }
        serialQueue.async { [weak self] in
            guard let self = self else { return }
            let drops = self.pendingConsentDrops
            self.pendingConsentDrops = 0
            let depth = self.eventQueue.count
            let health = BatchHealth(
                accepted: accepted,
                duplicate: duplicate,
                rejected: rejected,
                droppedByConsent: drops,
                queueDepth: depth
            )
            DispatchQueue.main.async { self.onBatchResult?(health) }
        }
    }

    private func fetchConfig() {
        guard let url = URL(string: "\(config?.endpoint ?? "")/v1/config/sdk/manifest") else { return }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(config?.apiKey ?? "")", forHTTPHeaderField: "Authorization")
        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            self?.serialQueue.async {
                self?.serverConfig = json
                if self?.config?.debug == true { self?.log("Config loaded") }
            }
        }.resume()
    }

    private func buildContext(at eventDate: Date) -> EventContext {
        let granted = Set(consentState)

        #if canImport(UIKit)
        let osName = "iOS"
        let osVersion = UIDevice.current.systemVersion
        #else
        let osName = "macOS"
        let osVersion = ProcessInfo.processInfo.operatingSystemVersionString
        #endif

        // Monotonic per-session ordering counter (reset on session rotation)
        // for gap/reorder detection at ingest.
        let sequenceNumber = eventSequence
        eventSequence += 1

        return EventContext(
            library: .init(name: "aether-ios", version: "8.12.0"),
            device: .init(
                osName: osName,
                osVersion: osVersion,
                locale: Locale.current.identifier,
                timezone: TimeZone.current.identifier
            ),
            campaign: self.campaignInfo,
            // Active acquisition evidence rides on every event while
            // unexpired (mirrors campaign attachment); nil once expired.
            acquisitionEvidence: activeAcquisitionEvidence(at: eventDate),
            fingerprint: gatedFingerprint(),
            network: currentNetworkType,
            thermalState: thermalStateString(),
            consent: [
                "analytics": granted.contains("analytics"),
                "marketing": granted.contains("marketing"),
                "personalization": granted.contains("personalization"),
                "web3": granted.contains("web3"),
                "agent": granted.contains("agent"),
                "commerce": granted.contains("commerce"),
                "financial_activity": granted.contains("financial_activity"),
                "credit": granted.contains("credit"),
                "location": granted.contains("location"),
                "economic_observability": granted.contains("economic_observability"),
                "cross_chain_observability": granted.contains("cross_chain_observability"),
            ],
            journey: journeySnapshot(),
            sequence: .init(event: sequenceNumber),
            // Temporal provenance at the event's occurrence instant (offset is
            // zone-at-instant, so DST transitions are captured correctly).
            timezone: TimeZone.current.identifier,
            utcOffsetMinutes: TimeZone.current.secondsFromGMT(for: eventDate) / 60,
            timeZoneSource: "device",
            clockSource: "device"
        )
    }

    /// Snapshot of the active journey stamped on every event's context.
    /// Carries only the canonical journey identity fields (id/name/type/status)
    /// — the backend owns step reconstruction. Nil when no journey is active.
    private func journeySnapshot() -> EventContext.JourneyInfo? {
        guard let journeyId = currentJourneyId else { return nil }
        return .init(
            journeyId: journeyId,
            journeyName: currentJourneyName,
            journeyType: currentJourneyType,
            journeyStatus: currentJourneyStatus
        )
    }

    /// Fingerprint stamping gate: the device-fingerprint hash is only stamped
    /// on the wire context when (a) analytics consent is granted in GDPR mode
    /// (mirroring the fingerprint_signals gating in resolveIdentity) and
    /// (b) the user authorized tracking via App Tracking Transparency when
    /// respectATT is enabled. On platforms without the ATT framework the ATT
    /// gate does not apply.
    private func gatedFingerprint() -> EventContext.FingerprintInfo? {
        let gdprActive = config?.privacy.gdprMode ?? false
        if gdprActive && !consentState.contains("analytics") { return nil }
        #if canImport(AppTrackingTransparency)
        if config?.privacy.respectATT == true {
            if #available(iOS 14.5, macOS 12.0, *) {
                guard ATTrackingManager.trackingAuthorizationStatus == .authorized else { return nil }
            }
        }
        #endif
        return .init(id: fingerprintId)
    }

    private func emitSessionStart() {
        let startupMs = Int(Date().timeIntervalSince(appStartDate) * 1000)
        let memoryUsedMB = memoryUsageMB()

        #if canImport(UIKit)
        let osVersion = UIDevice.current.systemVersion
        let deviceModel = UIDevice.current.model
        #else
        let osVersion = ProcessInfo.processInfo.operatingSystemVersionString
        let deviceModel = "Mac"
        #endif

        enqueueEvent(type: .track, properties: [
            "event":          AnyCodable("session_start"),
            "startupTimeMs":  AnyCodable(startupMs),
            "memoryUsedMB":   AnyCodable(memoryUsedMB),
            "thermalState":   AnyCodable(thermalStateString()),
            "networkType":    AnyCodable(currentNetworkType),
            "osVersion":      AnyCodable(osVersion),
            "device":         AnyCodable(deviceModel),
        ])
    }

    private func memoryUsageMB() -> Int {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size) / 4
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
            }
        }
        guard result == KERN_SUCCESS else { return 0 }
        return Int(info.resident_size / 1048576)
    }

    private func thermalStateString() -> String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal:  return "nominal"
        case .fair:     return "fair"
        case .serious:  return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }

    #if canImport(AppTrackingTransparency)
    private func requestTrackingAuthorization() {
        if #available(iOS 14.5, macOS 12.0, *) {
            // Must be called after the first UIApplicationDidBecomeActive
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                ATTrackingManager.requestTrackingAuthorization { [weak self] status in
                    let statusStr: String
                    switch status {
                    case .authorized:          statusStr = "authorized"
                    case .denied:              statusStr = "denied"
                    case .restricted:          statusStr = "restricted"
                    case .notDetermined:       statusStr = "not_determined"
                    @unknown default:          statusStr = "unknown"
                    }
                    var props: [String: AnyCodable] = [
                        "event": AnyCodable("att_authorization"),
                        "status": AnyCodable(statusStr),
                    ]
                    #if canImport(AdSupport)
                    props["idfa"] = AnyCodable(status == .authorized ? ASIdentifierManager.shared().advertisingIdentifier.uuidString : "")
                    #else
                    props["idfa"] = AnyCodable("")
                    #endif
                    self?.enqueueEvent(type: .track, properties: props)
                }
            }
        }
    }
    #endif

    private func startNetworkMonitor() {
        networkMonitor.pathUpdateHandler = { [weak self] path in
            if path.usesInterfaceType(.wifi) { self?.currentNetworkType = "wifi" }
            else if path.usesInterfaceType(.cellular) { self?.currentNetworkType = "cellular" }
            else if path.usesInterfaceType(.wiredEthernet) { self?.currentNetworkType = "ethernet" }
            else if path.status == .satisfied { self?.currentNetworkType = "other" }
            else { self?.currentNetworkType = "none" }
        }
        networkMonitor.start(queue: DispatchQueue(label: "com.aether.sdk.network"))
    }

    private func loadOrCreateAnonymousId() -> String {
        if let stored = defaults.string(forKey: "anonymousId") {
            return stored
        }
        let id = UUID().uuidString
        defaults.set(id, forKey: "anonymousId")
        return id
    }

    private func setupLifecycleObservers() {
        #if canImport(UIKit)
        NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            self?.persistQueue()
            self?.flush()
        }
        NotificationCenter.default.addObserver(forName: UIApplication.willTerminateNotification, object: nil, queue: .main) { [weak self] _ in
            self?.persistQueue()
            self?.flush()
        }
        NotificationCenter.default.addObserver(forName: UIApplication.willEnterForegroundNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self = self else { return }
            let now = Date()
            let elapsed = self.lastActivityDate.map { now.timeIntervalSince($0) } ?? (Aether.sessionTimeoutSeconds + 1)
            if elapsed > Aether.sessionTimeoutSeconds {
                self.sessionId = UUID().uuidString
                self.sessionStart = now
                self.eventSequence = 0
            }
            self.lastActivityDate = now
            self.track("app_foreground")
            self.continueJourney("app_foreground", properties: ["resumeReason": AnyCodable("application_active")])
        }
        NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            self?.lastActivityDate = Date()
        }
        #else
        // macOS lifecycle: observe NSApplication termination
        NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object: nil, queue: .main) { [weak self] _ in
            self?.flush()
        }
        #endif
    }

    private func sha256(_ string: String) -> String {
        let data = Data(string.lowercased().utf8)
        let hash = SHA256.hash(data: data)
        return hash.compactMap { String(format: "%02x", $0) }.joined()
    }

    private func resolveIdentity(walletAddress addr: String?, userId uid: String?, email: String?) {
        guard let cfg = config,
              let url = URL(string: "\(cfg.endpoint)/sdk/identity/resolve") else { return }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(cfg.apiKey, forHTTPHeaderField: "x-api-key")
        request.timeoutInterval = 5.0

        var wallets: [[String: String]] = []
        if let address = addr, !address.isEmpty {
            wallets = [["address": address, "vm": "evm"]]
        }
        var body: [String: Any] = [
            "wallets": wallets,
            "anonymous_id": anonymousId,
            "device_fingerprint": fingerprintId,
            "platform": "ios",
        ]
        if let uid = uid { body["user_id"] = uid }
        if let em = email, !em.isEmpty { body["email_hash"] = sha256(em.trimmingCharacters(in: .whitespaces)) }
        // fingerprint_signals: individual components for backend confidence scoring.
        // Omitted in GDPR mode until analytics consent is granted to avoid pre-consent disclosure.
        let gdprActive = config?.privacy.gdprMode ?? false
        if !gdprActive || consentState.contains("analytics") {
            #if canImport(UIKit)
            body["fingerprint_signals"] = [
                "idfv": UIDevice.current.identifierForVendor?.uuidString ?? "",
                "model": UIDevice.current.model,
                "os_version": UIDevice.current.systemVersion,
                "locale": Locale.current.identifier,
                "timezone": TimeZone.current.identifier,
                "processor_count": ProcessInfo.processInfo.processorCount,
            ] as [String: Any]
            #endif
        }
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            guard let self = self,
                  let data = data,
                  let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let resolved = json["resolved"] as? Bool, resolved,
                  let identity = json["identity"] as? [String: Any] else { return }

            let resolvedAnonymousId = identity["anonymous_id"] as? String ?? ""
            let resolvedUserId = identity["user_id"] as? String

            guard !resolvedAnonymousId.isEmpty, resolvedAnonymousId != self.anonymousId else { return }

            self.serialQueue.async {
                if let uid = resolvedUserId {
                    self.userId = uid
                    self.defaults.set(uid, forKey: "userId")
                }
                self.enqueueEvent(type: .track, properties: [
                    "event": AnyCodable("journey_resumed"),
                    "resolvedAnonymousId": AnyCodable(resolvedAnonymousId),
                    "resolvedUserId": AnyCodable(resolvedUserId ?? "")
                ])
                self.log("Journey resumed from prior device")
                cfg.onJourneyResumed?(resolvedAnonymousId, resolvedUserId)
            }
        }.resume()
    }

    private func log(_ message: String) {
        guard config?.debug == true else { return }
        print("[Aether SDK] \(message)")
    }

    func scrubSensitiveFields(_ props: [String: AnyCodable]) -> [String: AnyCodable] {
        Dictionary(uniqueKeysWithValues: props.map { key, value in
            (key, Self.sensitiveKeys.contains(key.lowercased())
                ? AnyCodable("[REDACTED]")
                : AnyCodable(scrubNestedValue(value.value, depth: 1)))
        })
    }

    /// Depth-capped recursive scrub so sensitive keys are redacted inside
    /// nested dictionaries and arrays at every depth, not only at the top
    /// level. Non-mutating: always returns a new collection.
    private func scrubNestedValue(_ value: Any, depth: Int) -> Any {
        guard depth < Aether.maxScrubDepth else { return value }
        switch value {
        case let nested as [String: AnyCodable]:
            return Dictionary(uniqueKeysWithValues: nested.map { key, inner in
                (key, Self.sensitiveKeys.contains(key.lowercased())
                    ? AnyCodable("[REDACTED]")
                    : AnyCodable(scrubNestedValue(inner.value, depth: depth + 1)))
            })
        case let nested as [String: Any]:
            return Dictionary(uniqueKeysWithValues: nested.map { key, inner in
                (key, Self.sensitiveKeys.contains(key.lowercased())
                    ? "[REDACTED]" as Any
                    : scrubNestedValue(inner, depth: depth + 1))
            })
        case let nested as [AnyCodable]:
            return nested.map { AnyCodable(scrubNestedValue($0.value, depth: depth + 1)) }
        case let nested as [Any]:
            return nested.map { scrubNestedValue($0, depth: depth + 1) }
        default:
            return value
        }
    }

    func normalizeWalletAddress(_ address: String, vm: String = "evm") -> String {
        switch vm.lowercased() {
        case "evm": return address.lowercased()
        default:    return address.trimmingCharacters(in: .whitespaces)
        }
    }

    private func isApplePayAvailable() -> Bool {
        #if canImport(PassKit)
        return true
        #else
        return false
        #endif
    }

    private var canonicalConsentReceiptHashFields: [String] {
        [
            "tenant_id", "subject_id", "anonymous_id", "purposes", "state", "source",
            "provider", "policy_version", "jurisdiction_context", "mode", "lawful_basis",
            "granted_at", "denied_at", "revoked_at", "expires_at", "gpc_observed",
            "dnt_observed", "provider_consent_id", "metadata",
        ]
    }

    private func canonicalConsentReceiptValues(
        _ input: CanonicalConsentReceiptInput
    ) -> [String: Any?] {
        [
            "tenant_id": input.tenantId, "subject_id": input.subjectId,
            "anonymous_id": input.anonymousId, "purposes": input.purposes,
            "state": input.state, "source": input.source, "provider": input.provider,
            "policy_version": input.policyVersion,
            "jurisdiction_context": input.jurisdictionContext, "mode": input.mode,
            "lawful_basis": input.lawfulBasis, "granted_at": input.grantedAt,
            "denied_at": input.deniedAt, "revoked_at": input.revokedAt,
            "expires_at": input.expiresAt, "gpc_observed": input.gpcObserved,
            "dnt_observed": input.dntObserved, "provider_consent_id": input.providerConsentId,
            "metadata": input.metadata.mapValues(\.value),
        ]
    }

    private func canonicalConsentReceiptPreimage(
        _ input: CanonicalConsentReceiptInput
    ) -> String {
        let values = canonicalConsentReceiptValues(input)
        return canonicalConsentReceiptHashFields.reduce(into: "aether-consent-receipt/v1\n") {
            result, field in
            let value = canonicalConsentHashValue(values[field] ?? nil)
            result += "\(field)=\(value.lengthOfBytes(using: .utf8)):\(value)\n"
        }
    }

    private func canonicalConsentHashValue(_ value: Any?) -> String {
        guard let value = value else { return "" }
        if let bool = value as? Bool { return bool ? "true" : "false" }
        if let array = value as? [String] {
            return Array(Set(array)).sorted().joined(separator: "\u{001f}")
        }
        if let dictionary = value as? [String: Any] {
            return dictionary.isEmpty ? "" : canonicalJSON(dictionary)
        }
        return String(describing: value)
    }

    private func canonicalJSON(_ value: Any) -> String {
        if value is NSNull { return "null" }
        if let string = value as? String {
            let data = try! JSONSerialization.data(withJSONObject: [string])
            return String(data: data, encoding: .utf8)!.dropFirst().dropLast().description
        }
        if let bool = value as? Bool { return bool ? "true" : "false" }
        if let number = value as? NSNumber { return number.stringValue }
        if let array = value as? [Any] {
            return "[\(array.map(canonicalJSON).joined(separator: ","))]"
        }
        if let dictionary = value as? [String: Any] {
            let members = dictionary.keys.sorted().map {
                "\(canonicalJSON($0)):\(canonicalJSON(dictionary[$0]!))"
            }
            return "{\(members.joined(separator: ","))}"
        }
        return canonicalJSON(String(describing: value))
    }

    private func canonicalConsentReceiptDictionary(
        _ receipt: CanonicalConsentReceipt
    ) -> [String: Any] {
        var values = canonicalConsentReceiptValues(receipt.input).mapValues { $0 ?? NSNull() }
        values["receipt_id"] = receipt.receiptId
        values["integrity_hash"] = receipt.integrityHash
        values["idempotency_key"] = receipt.idempotencyKey
        return values
    }

    private func consentReceiptRequest(_ receipt: CanonicalConsentReceipt) -> [String: Any] {
        let input = receipt.input
        return [
            "user_id": input.subjectId ?? NSNull(),
            "subject_id": input.subjectId ?? NSNull(),
            "anonymous_id": input.anonymousId ?? NSNull(),
            "purposes": input.purposes,
            "granted": input.state == "granted",
            "source": input.source,
            "mode": input.mode ?? NSNull(),
            "jurisdiction": input.jurisdictionContext ?? NSNull(),
            "gpc_observed": input.gpcObserved ?? NSNull(),
            "dnt_observed": input.dntObserved ?? NSNull(),
            "idempotency_key": receipt.idempotencyKey,
            "canonical_receipt": canonicalConsentReceiptDictionary(receipt),
        ]
    }
}

// MARK: - MetricKit Delegate

#if canImport(MetricKit)
extension Aether: MXMetricManagerSubscriber {
    public func didReceive(_ payloads: [MXMetricPayload]) {
        for payload in payloads {
            var props: [String: AnyCodable] = [
                "event":        AnyCodable("metrickit_payload"),
                "appVersion":   AnyCodable(payload.latestApplicationVersion),
                "periodStart":  AnyCodable(ISO8601DateFormatter().string(from: payload.timeStampBegin)),
                "periodEnd":    AnyCodable(ISO8601DateFormatter().string(from: payload.timeStampEnd)),
            ]

            if let launch = payload.applicationLaunchMetrics {
                props["resumeBucketCount"]     = AnyCodable(launch.histogrammedApplicationResumeTime.totalBucketCount)
                props["coldLaunchBucketCount"] = AnyCodable(launch.histogrammedTimeToFirstDraw.totalBucketCount)
            }
            if let hang = payload.applicationResponsivenessMetrics {
                props["hangBucketCount"] = AnyCodable(hang.histogrammedApplicationHangTime.totalBucketCount)
            }
            if let cpu = payload.cpuMetrics {
                props["cpuTimePerSecond"] = AnyCodable(cpu.cumulativeCPUTime.converted(to: .seconds).value)
            }
            if let mem = payload.memoryMetrics {
                props["peakMemoryMB"] = AnyCodable(mem.peakMemoryUsage.converted(to: .megabytes).value)
            }
            if let network = payload.networkTransferMetrics {
                props["wifiUploadMB"]   = AnyCodable(network.cumulativeWifiUpload.converted(to: .megabytes).value)
                props["wifiDownloadMB"] = AnyCodable(network.cumulativeWifiDownload.converted(to: .megabytes).value)
                props["cellUploadMB"]   = AnyCodable(network.cumulativeCellularUpload.converted(to: .megabytes).value)
                props["cellDownloadMB"] = AnyCodable(network.cumulativeCellularDownload.converted(to: .megabytes).value)
            }
            if let disk = payload.diskIOMetrics {
                props["diskWritesMB"] = AnyCodable(disk.cumulativeLogicalWrites.converted(to: .megabytes).value)
            }

            enqueueEvent(type: .performance, properties: props)
        }
    }

    public func didReceive(_ payloads: [MXDiagnosticPayload]) {
        for payload in payloads {
            var props: [String: AnyCodable] = [
                "event":      AnyCodable("metrickit_diagnostic"),
            ]
            if let crashes = payload.crashDiagnostics, !crashes.isEmpty {
                props["crashCount"] = AnyCodable(crashes.count)
                props["crashType"]  = AnyCodable(crashes.first?.exceptionType ?? "unknown")
            }
            if let hangs = payload.hangDiagnostics, !hangs.isEmpty {
                props["hangCount"]          = AnyCodable(hangs.count)
                props["hangDurationMs"]     = AnyCodable(hangs.first?.hangDuration.converted(to: .milliseconds).value ?? 0)
            }
            enqueueEvent(type: .performance, properties: props)
        }
    }
}
#endif

// MARK: - UIViewController Swizzling for Auto Screen Tracking

#if canImport(UIKit)
extension UIViewController {
    static var hasSwizzled = false

    static func swizzleViewDidAppear() {
        guard !hasSwizzled else { return }
        hasSwizzled = true

        let originalSelector = #selector(UIViewController.viewDidAppear(_:))
        let swizzledSelector = #selector(UIViewController.aether_viewDidAppear(_:))

        guard let originalMethod = class_getInstanceMethod(UIViewController.self, originalSelector),
              let swizzledMethod = class_getInstanceMethod(UIViewController.self, swizzledSelector) else { return }

        method_exchangeImplementations(originalMethod, swizzledMethod)
    }

    @objc func aether_viewDidAppear(_ animated: Bool) {
        aether_viewDidAppear(animated) // Calls original

        let screenName = String(describing: type(of: self))
        let ignoredPrefixes = ["UI", "_", "NS"]
        if !ignoredPrefixes.contains(where: { screenName.hasPrefix($0) }) {
            Aether.shared.screenView(screenName)
        }
    }
}
#endif

// MARK: - AnyCodable Helper

public struct AnyCodable: Codable {
    public let value: Any

    public init(_ value: Any) { self.value = value }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let v = try? container.decode(String.self) { value = v }
        else if let v = try? container.decode(Int.self) { value = v }
        else if let v = try? container.decode(Double.self) { value = v }
        else if let v = try? container.decode(Bool.self) { value = v }
        else if let v = try? container.decode([String: AnyCodable].self) { value = v }
        else if let v = try? container.decode([AnyCodable].self) { value = v }
        else { value = "" }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case let v as String: try container.encode(v)
        case let v as Int: try container.encode(v)
        case let v as Double: try container.encode(v)
        case let v as Bool: try container.encode(v)
        case let v as [String: AnyCodable]: try container.encode(v)
        case let v as [AnyCodable]: try container.encode(v)
        default: try container.encode(String(describing: value))
        }
    }
}
