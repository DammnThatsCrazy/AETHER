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

// MARK: - Event Types

public enum AetherEventType: String, Codable, CaseIterable {
    case track, page, screen, heartbeat, error, performance, experiment
    case journey_started, journey_paused, journey_resumed, journey_continued, journey_completed, journey_abandoned, journey_checkpoint
    case identify, consent
    case conversion, payment_initiated, payment_completed, payment_failed, approval_requested, approval_resolved, entitlement_granted, entitlement_revoked, access_granted, access_denied
    case wallet, transaction, contract_action
    // Agent — legacy
    case agent_task, agent_decision, a2h_interaction
    // Agent — lifecycle (granular)
    case agent_registered, agent_updated, agent_authorized, agent_deauthorized
    case agent_capability_granted, agent_capability_revoked
    case agent_task_created, agent_task_decomposed, agent_task_started, agent_task_completed, agent_task_failed
    case agent_tool_called, agent_resource_requested, agent_delegated_task, agent_subagent_spawned
    case agent_policy_evaluated, agent_handoff, agent_escalated_to_human, agent_outcome_recorded
    // x402 — legacy
    case x402_payment
    // x402 — lifecycle (granular)
    case x402_resource_requested, x402_payment_required, x402_quote_received
    case x402_authorization_requested, x402_authorization_resolved
    case x402_payment_intent_created, x402_payment_submitted, x402_payment_settled
    case x402_payment_failed, x402_payment_timeout, x402_receipt_verified
    case x402_access_granted, x402_access_denied, x402_refund_or_reversal
    // reward enablement (A6)
    case reward_action_queued, reward_proof_generated, reward_delivered, reward_claim_submitted
    // Agentic observability — account / MCP / tool
    case agentic_account_observed, agentic_account_connected_observed, agentic_account_disconnected_observed
    case agent_budget_observed, agent_budget_changed_observed, agent_permission_observed
    case agent_mcp_connection_observed, agent_tool_observed, agent_tool_invocation_observed
    case agent_activity_observed, agent_risk_signal_observed, agent_notification_observed
    // Agentic observability — Robinhood-style trading observation
    case agent_strategy_observed, agent_trade_intent_observed, agent_trade_order_observed
    case agent_trade_fill_observed, agent_trade_rejection_observed, agent_position_observed
    case agent_portfolio_snapshot_observed, agent_performance_snapshot_observed, agent_disconnect_observed
    // Agentic observability — AgentMail-style communication observation
    case agent_inbox_observed, agent_email_address_observed, agent_thread_observed
    case agent_message_received_observed, agent_message_sent_observed, agent_reply_observed
    case agent_attachment_observed, agent_attachment_parsed_observed
    case agent_otp_detected_observed, agent_invoice_detected_observed, agent_receipt_detected_observed
    case agent_calendar_intent_observed, agent_support_route_observed
    case agent_semantic_search_observed, agent_data_extraction_observed
    // x402 protocol observation family (from external observer perspective)
    case x402_resource_request_observed, x402_challenge_observed, x402_payment_requirement_observed
    case x402_signature_observed, x402_verification_observed, x402_settlement_observed
    case x402_resource_access_observed, x402_resource_access_denied_observed
    case x402_failure_observed, x402_replay_risk_observed, x402_provider_observed
    // Exposure family
    case content_impression, recommendation_exposed, offer_exposed, feature_exposed
    case search_result_exposed, ad_exposed, notification_presented, decision_observed
    // Outcome family
    case outcome_observed, goal_achieved, goal_failed
    case recommendation_accepted, recommendation_rejected, feedback_submitted
    case retention_observed, churn_observed, human_override_observed
    // B2B family
    case organization_observed, workspace_created, workspace_updated
    case member_invited, member_joined, member_removed, role_changed
    case seat_assigned, seat_released, integration_connected, integration_disconnected
    case service_account_created, service_account_revoked
    case api_key_created, api_key_revoked
    case project_created, project_archived
    case workflow_started, workflow_completed, workflow_failed
    // Ecommerce extended family
    case product_viewed, cart_item_added, cart_item_removed, cart_updated, coupon_applied
    case checkout_started, checkout_step_completed, order_completed, order_cancelled, order_refunded
    case chargeback_observed
    case subscription_started, trial_started, trial_converted, subscription_renewed
    case subscription_upgrade_observed, subscription_downgrade_observed, subscription_cancelled
    case invoice_issued, invoice_paid, invoice_failed, dunning_started, dunning_resolved
    // Friction family
    case dead_click_observed, rage_click_observed, scroll_depth_observed
    case form_started, form_field_interaction, form_validation_failed, form_submitted, form_abandoned
    case search_reformulated, retry_observed, journey_stalled, backtrack_observed
    // Server observation family
    case api_request_observed, webhook_delivery_observed
    case connector_sync_started, connector_sync_completed, connector_sync_failed
    case job_started, job_completed, job_failed
    case rate_limit_observed, dependency_failure_observed, export_completed
    // Identity lifecycle family
    case signup_started, signup_completed, login_succeeded, login_failed, logout_observed
    case sso_observed, mfa_challenge_observed, identity_verified
    case alias_link_requested, alias_link_confirmed, alias_revoked
    case account_recovery_started, account_recovery_completed
    case device_registered, device_revoked
    // Agent evaluation family
    case agent_evaluation_observed, agent_cost_observed
    case agent_grounding_observed, agent_guardrail_observed, agent_human_override_observed
    case ai_invocation_observed
    // Web3 lifecycle extensions
    case transaction_pending_observed, transaction_confirmed_observed
    case transaction_reverted_observed, transaction_reorged_observed
    case token_approval_observed, allowance_changed_observed
    case bridge_transfer_observed, settlement_finality_observed
    // Comms family
    case notification_delivered, notification_opened, notification_clicked
    case email_delivered, email_opened, email_clicked, email_bounced
    case email_queued, email_processed, email_sent, email_deferred
    case email_dropped, email_replied, email_spam_complaint, email_suppressed
    case message_replied_observed, unsubscribe_observed
    case support_case_created, support_case_resolved, support_case_escalated, support_sla_breached
    // Credit family (explicit opt-in)
    case credit_signal_observed, credit_account_observed, credit_decision_observed
    // Location family (explicit opt-in)
    case location_observed, geofence_transition_observed
    // Derivatives family (explicit financial_activity opt-in)
    case trading_account_connected, trading_account_disconnected
    case trading_account_authorized, trading_account_deauthorized
    case trading_agent_enabled, trading_agent_disabled
    case trade_intent_created, trade_approval_requested, trade_approval_resolved
    case risk_policy_updated, human_trade_override_recorded
    // Stablecoin intelligence family (explicit opt-in)
    case stablecoin_transfer_observed, stablecoin_payment_observed, stablecoin_mint_observed
    case stablecoin_burn_observed, stablecoin_bridge_outbound_observed, stablecoin_bridge_inbound_observed
    case stablecoin_swap_observed, stablecoin_x402_settlement_observed, stablecoin_treasury_movement_observed
    case stablecoin_payout_observed, stablecoin_venue_deposit_observed, stablecoin_venue_withdrawal_observed
    case stablecoin_balance_snapshot_observed, stablecoin_supply_snapshot_observed, stablecoin_holder_concentration_observed
    case stablecoin_valuation_observed, stablecoin_depeg_detected, stablecoin_depeg_resolved
    case stablecoin_finality_confirmed, stablecoin_reorg_detected, stablecoin_observation_corrected
    case stablecoin_reconciliation_run_completed, stablecoin_reconciliation_variance_detected, stablecoin_reconciliation_variance_resolved
    case stablecoin_asset_registered, stablecoin_deployment_registered, stablecoin_support_asserted
    case stablecoin_support_revoked, stablecoin_flow_aggregate_materialized, stablecoin_checkpoint_advanced
    // Derivatives intelligence family (explicit opt-in)
    case derivatives_venue_registered, derivatives_venue_deployment_registered, derivatives_instrument_registered
    case derivatives_market_registered, derivatives_strategy_registered, derivatives_strategy_version_registered
    case derivatives_risk_policy_registered, derivatives_account_linked, derivatives_account_link_revoked
    case derivatives_balance_snapshot_observed, derivatives_collateral_change_observed, derivatives_margin_snapshot_observed
    case derivatives_order_observed, derivatives_order_updated_observed, derivatives_order_cancelled_observed
    case derivatives_order_rejected_observed, derivatives_order_expired_observed, derivatives_fill_observed
    case derivatives_fill_corrected, derivatives_position_opened_observed, derivatives_position_increased_observed
    case derivatives_position_reduced_observed, derivatives_position_closed_observed, derivatives_position_liquidated_observed
    case derivatives_position_adl_observed, derivatives_position_settled_observed, derivatives_position_corrected
    case derivatives_funding_payment_observed, derivatives_fee_observed, derivatives_pnl_snapshot_materialized
    case derivatives_exposure_snapshot_materialized, derivatives_price_observation_recorded, derivatives_market_status_changed
    case derivatives_stream_gap_detected, derivatives_stream_gap_recovered, derivatives_stream_checkpoint_advanced
    case derivatives_adapter_conformance_run, derivatives_reconciliation_run_completed, derivatives_reconciliation_variance_detected
    case derivatives_reconciliation_variance_resolved, derivatives_risk_threshold_breached
    // Interoperability intelligence family (explicit opt-in)
    case interop_provider_registered, interop_gateway_registered, interop_path_registered
    case interop_application_registered, interop_verification_actor_registered, interop_message_discovered
    case interop_message_sent_observed, interop_message_source_confirmed, interop_message_verification_observed
    case interop_message_verified, interop_message_delivery_attempt_observed, interop_message_delivered
    case interop_message_executed_observed, interop_message_settled, interop_message_failed
    case interop_message_timeout, interop_message_expired, interop_message_cancelled
    case interop_message_refunded_observed, interop_message_recovered, interop_message_reorged
    case interop_message_corrected, interop_message_correlated, interop_intent_observed
    case interop_intent_fulfilled_observed, interop_asset_leg_locked_observed, interop_asset_leg_burned_observed
    case interop_asset_leg_minted_observed, interop_asset_leg_released_observed, interop_fee_observed
    case interop_security_policy_snapshot_recorded, interop_security_policy_changed, interop_verification_quorum_observed
    case interop_provider_checkpoint_advanced, interop_stream_gap_detected, interop_stream_gap_recovered
    case interop_reconciliation_run_completed, interop_reconciliation_variance_detected, interop_reconciliation_variance_resolved
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

public struct EventContext: Codable {
    public let library: LibraryInfo
    public var device: DeviceInfo?
    public var campaign: CampaignInfo?
    public var fingerprint: FingerprintInfo?
    public var network: String?
    public var thermalState: String?
    public var consent: [String: Bool]?

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

// MARK: - Main SDK Class

public final class Aether: NSObject {
    public static let shared = Aether()

    private var config: AetherConfig?
    private var eventQueue: [AetherEvent] = []
    private var sessionId: String = UUID().uuidString
    private var currentJourneyId: String? = nil
    private var currentJourneyName: String? = nil
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
    private var isInitialized = false
    private var serverConfig: [String: Any] = [:]
    private var consentState: [String] = []
    private var fingerprintId: String = ""
    private var campaignInfo: EventContext.CampaignInfo?
    private var healthAgent: AetherHealthAgent?
    private let networkMonitor = NWPathMonitor()
    private var currentNetworkType: String = "unknown"

    private static let clickIdParams: Set<String> = [
        "gclid", "msclkid", "fbclid", "ttclid", "twclid",
        "li_fat_id", "rdt_cid", "scid", "dclid", "epik",
        "irclickid", "aff_id"
    ]

    private static let eventConsentPurpose: [AetherEventType: String] = [
        .track: "analytics", .page: "analytics", .screen: "analytics", .heartbeat: "analytics", .error: "analytics", .performance: "analytics",
        .journey_started: "analytics", .journey_paused: "analytics", .journey_resumed: "analytics", .journey_continued: "analytics", .journey_completed: "analytics", .journey_abandoned: "analytics", .journey_checkpoint: "analytics", .identify: "analytics",
        .experiment: "marketing", .conversion: "marketing", .consent: "analytics",
        .payment_initiated: "commerce", .payment_completed: "commerce", .payment_failed: "commerce", .approval_requested: "commerce", .approval_resolved: "commerce", .entitlement_granted: "commerce", .entitlement_revoked: "commerce", .access_granted: "commerce", .access_denied: "commerce",
        // x402 — legacy + lifecycle
        .x402_payment: "commerce",
        .x402_resource_requested: "commerce", .x402_payment_required: "commerce",
        .x402_quote_received: "commerce", .x402_authorization_requested: "commerce",
        .x402_authorization_resolved: "commerce", .x402_payment_intent_created: "commerce",
        .x402_payment_submitted: "commerce", .x402_payment_settled: "commerce",
        .x402_payment_failed: "commerce", .x402_payment_timeout: "commerce",
        .x402_receipt_verified: "commerce", .x402_access_granted: "commerce",
        .x402_access_denied: "commerce", .x402_refund_or_reversal: "commerce",
        // reward enablement (A6)
        .reward_action_queued: "commerce", .reward_proof_generated: "commerce",
        .reward_delivered: "commerce", .reward_claim_submitted: "commerce",
        .wallet: "web3", .transaction: "web3", .contract_action: "web3",
        // Agent — legacy + lifecycle
        .agent_task: "agent", .agent_decision: "agent", .a2h_interaction: "agent",
        .agent_registered: "agent", .agent_updated: "agent",
        .agent_authorized: "agent", .agent_deauthorized: "agent",
        .agent_capability_granted: "agent", .agent_capability_revoked: "agent",
        .agent_task_created: "agent", .agent_task_decomposed: "agent",
        .agent_task_started: "agent", .agent_task_completed: "agent",
        .agent_task_failed: "agent", .agent_tool_called: "agent",
        .agent_resource_requested: "agent", .agent_delegated_task: "agent",
        .agent_subagent_spawned: "agent", .agent_policy_evaluated: "agent",
        .agent_handoff: "agent", .agent_escalated_to_human: "agent",
        .agent_outcome_recorded: "agent",
        // Agentic observability — account / MCP / tool
        .agentic_account_observed: "agent", .agentic_account_connected_observed: "agent", .agentic_account_disconnected_observed: "agent",
        .agent_budget_observed: "agent", .agent_budget_changed_observed: "agent", .agent_permission_observed: "agent",
        .agent_mcp_connection_observed: "agent", .agent_tool_observed: "agent", .agent_tool_invocation_observed: "agent",
        .agent_activity_observed: "agent", .agent_risk_signal_observed: "agent", .agent_notification_observed: "agent",
        // Agentic observability — Robinhood-style trading observation
        .agent_strategy_observed: "agent", .agent_trade_intent_observed: "agent", .agent_trade_order_observed: "agent",
        .agent_trade_fill_observed: "agent", .agent_trade_rejection_observed: "agent", .agent_position_observed: "agent",
        .agent_portfolio_snapshot_observed: "agent", .agent_performance_snapshot_observed: "agent", .agent_disconnect_observed: "agent",
        // Agentic observability — AgentMail-style communication observation
        .agent_inbox_observed: "agent", .agent_email_address_observed: "agent", .agent_thread_observed: "agent",
        .agent_message_received_observed: "agent", .agent_message_sent_observed: "agent", .agent_reply_observed: "agent",
        .agent_attachment_observed: "agent", .agent_attachment_parsed_observed: "agent",
        .agent_otp_detected_observed: "agent", .agent_invoice_detected_observed: "agent", .agent_receipt_detected_observed: "agent",
        .agent_calendar_intent_observed: "agent", .agent_support_route_observed: "agent",
        .agent_semantic_search_observed: "agent", .agent_data_extraction_observed: "agent",
        // x402 protocol observation family
        .x402_resource_request_observed: "commerce", .x402_challenge_observed: "commerce", .x402_payment_requirement_observed: "commerce",
        .x402_signature_observed: "commerce", .x402_verification_observed: "commerce", .x402_settlement_observed: "commerce",
        .x402_resource_access_observed: "commerce", .x402_resource_access_denied_observed: "commerce",
        .x402_failure_observed: "commerce", .x402_replay_risk_observed: "commerce", .x402_provider_observed: "commerce",
        // Exposure family
        .content_impression: "analytics", .recommendation_exposed: "analytics",
        .offer_exposed: "analytics", .feature_exposed: "analytics",
        .search_result_exposed: "analytics", .ad_exposed: "marketing",
        .notification_presented: "analytics", .decision_observed: "analytics",
        // Outcome family
        .outcome_observed: "analytics", .goal_achieved: "analytics", .goal_failed: "analytics",
        .recommendation_accepted: "analytics", .recommendation_rejected: "analytics",
        .feedback_submitted: "analytics", .retention_observed: "analytics",
        .churn_observed: "analytics", .human_override_observed: "analytics",
        // B2B family
        .organization_observed: "analytics", .workspace_created: "analytics", .workspace_updated: "analytics",
        .member_invited: "analytics", .member_joined: "analytics", .member_removed: "analytics",
        .role_changed: "analytics", .seat_assigned: "analytics", .seat_released: "analytics",
        .integration_connected: "analytics", .integration_disconnected: "analytics",
        .service_account_created: "analytics", .service_account_revoked: "analytics",
        .api_key_created: "analytics", .api_key_revoked: "analytics",
        .project_created: "analytics", .project_archived: "analytics",
        .workflow_started: "analytics", .workflow_completed: "analytics", .workflow_failed: "analytics",
        // Ecommerce extended family
        .product_viewed: "commerce", .cart_item_added: "commerce", .cart_item_removed: "commerce",
        .cart_updated: "commerce", .coupon_applied: "commerce",
        .checkout_started: "commerce", .checkout_step_completed: "commerce",
        .order_completed: "commerce", .order_cancelled: "commerce", .order_refunded: "commerce",
        .chargeback_observed: "commerce",
        .subscription_started: "commerce", .trial_started: "commerce", .trial_converted: "commerce",
        .subscription_renewed: "commerce", .subscription_upgrade_observed: "commerce",
        .subscription_downgrade_observed: "commerce", .subscription_cancelled: "commerce",
        .invoice_issued: "commerce", .invoice_paid: "commerce", .invoice_failed: "commerce",
        .dunning_started: "commerce", .dunning_resolved: "commerce",
        // Friction family
        .dead_click_observed: "analytics", .rage_click_observed: "analytics",
        .scroll_depth_observed: "analytics", .form_started: "analytics",
        .form_field_interaction: "analytics", .form_validation_failed: "analytics",
        .form_submitted: "analytics", .form_abandoned: "analytics",
        .search_reformulated: "analytics", .retry_observed: "analytics",
        .journey_stalled: "analytics", .backtrack_observed: "analytics",
        // Server observation family
        .api_request_observed: "analytics", .webhook_delivery_observed: "analytics",
        .connector_sync_started: "analytics", .connector_sync_completed: "analytics",
        .connector_sync_failed: "analytics", .job_started: "analytics",
        .job_completed: "analytics", .job_failed: "analytics",
        .rate_limit_observed: "analytics", .dependency_failure_observed: "analytics",
        .export_completed: "analytics",
        // Identity lifecycle family
        .signup_started: "analytics", .signup_completed: "analytics",
        .login_succeeded: "analytics", .login_failed: "analytics",
        .logout_observed: "analytics", .sso_observed: "analytics",
        .mfa_challenge_observed: "analytics", .identity_verified: "analytics",
        .alias_link_requested: "analytics", .alias_link_confirmed: "analytics",
        .alias_revoked: "analytics", .account_recovery_started: "analytics",
        .account_recovery_completed: "analytics", .device_registered: "analytics",
        .device_revoked: "analytics",
        // Agent evaluation family
        .agent_evaluation_observed: "agent", .agent_cost_observed: "agent",
        .agent_grounding_observed: "agent", .agent_guardrail_observed: "agent",
        .agent_human_override_observed: "agent", .ai_invocation_observed: "agent",
        // Web3 lifecycle extensions
        .transaction_pending_observed: "web3", .transaction_confirmed_observed: "web3",
        .transaction_reverted_observed: "web3", .transaction_reorged_observed: "web3",
        .token_approval_observed: "web3", .allowance_changed_observed: "web3",
        .bridge_transfer_observed: "web3", .settlement_finality_observed: "web3",
        // Comms family
        .notification_delivered: "analytics", .notification_opened: "analytics",
        .notification_clicked: "analytics",
        .email_delivered: "marketing", .email_opened: "marketing",
        .email_clicked: "marketing", .email_bounced: "marketing",
        .email_queued: "marketing", .email_processed: "marketing",
        .email_sent: "marketing", .email_deferred: "marketing",
        .email_dropped: "marketing", .email_replied: "marketing",
        .email_spam_complaint: "marketing", .email_suppressed: "marketing",
        .message_replied_observed: "analytics", .unsubscribe_observed: "marketing",
        .support_case_created: "analytics", .support_case_resolved: "analytics",
        .support_case_escalated: "analytics", .support_sla_breached: "analytics",
        // Credit family (explicit opt-in)
        .credit_signal_observed: "credit", .credit_account_observed: "credit",
        .credit_decision_observed: "credit",
        // Location family (explicit opt-in)
        .location_observed: "location", .geofence_transition_observed: "location",
        // Derivatives family (explicit financial_activity opt-in)
        .trading_account_connected: "financial_activity", .trading_account_disconnected: "financial_activity",
        .trading_account_authorized: "financial_activity", .trading_account_deauthorized: "financial_activity",
        .trading_agent_enabled: "financial_activity", .trading_agent_disabled: "financial_activity",
        .trade_intent_created: "financial_activity", .trade_approval_requested: "financial_activity",
        .trade_approval_resolved: "financial_activity", .risk_policy_updated: "financial_activity",
        .human_trade_override_recorded: "financial_activity"
        // Stablecoin intelligence family (explicit opt-in)
        .stablecoin_transfer_observed: "economic_observability", .stablecoin_payment_observed: "economic_observability",
        .stablecoin_mint_observed: "economic_observability", .stablecoin_burn_observed: "economic_observability",
        .stablecoin_bridge_outbound_observed: "economic_observability", .stablecoin_bridge_inbound_observed: "economic_observability",
        .stablecoin_swap_observed: "economic_observability", .stablecoin_x402_settlement_observed: "economic_observability",
        .stablecoin_treasury_movement_observed: "economic_observability", .stablecoin_payout_observed: "economic_observability",
        .stablecoin_venue_deposit_observed: "economic_observability", .stablecoin_venue_withdrawal_observed: "economic_observability",
        .stablecoin_balance_snapshot_observed: "economic_observability", .stablecoin_supply_snapshot_observed: "economic_observability",
        .stablecoin_holder_concentration_observed: "economic_observability", .stablecoin_valuation_observed: "economic_observability",
        .stablecoin_depeg_detected: "economic_observability", .stablecoin_depeg_resolved: "economic_observability",
        .stablecoin_finality_confirmed: "economic_observability", .stablecoin_reorg_detected: "economic_observability",
        .stablecoin_observation_corrected: "economic_observability", .stablecoin_reconciliation_run_completed: "economic_observability",
        .stablecoin_reconciliation_variance_detected: "economic_observability", .stablecoin_reconciliation_variance_resolved: "economic_observability",
        .stablecoin_asset_registered: "economic_observability", .stablecoin_deployment_registered: "economic_observability",
        .stablecoin_support_asserted: "economic_observability", .stablecoin_support_revoked: "economic_observability",
        .stablecoin_flow_aggregate_materialized: "economic_observability", .stablecoin_checkpoint_advanced: "economic_observability",
        // Derivatives intelligence family (explicit opt-in)
        .derivatives_venue_registered: "financial_activity", .derivatives_venue_deployment_registered: "financial_activity",
        .derivatives_instrument_registered: "financial_activity", .derivatives_market_registered: "financial_activity",
        .derivatives_strategy_registered: "financial_activity", .derivatives_strategy_version_registered: "financial_activity",
        .derivatives_risk_policy_registered: "financial_activity", .derivatives_account_linked: "financial_activity",
        .derivatives_account_link_revoked: "financial_activity", .derivatives_balance_snapshot_observed: "financial_activity",
        .derivatives_collateral_change_observed: "financial_activity", .derivatives_margin_snapshot_observed: "financial_activity",
        .derivatives_order_observed: "financial_activity", .derivatives_order_updated_observed: "financial_activity",
        .derivatives_order_cancelled_observed: "financial_activity", .derivatives_order_rejected_observed: "financial_activity",
        .derivatives_order_expired_observed: "financial_activity", .derivatives_fill_observed: "financial_activity",
        .derivatives_fill_corrected: "financial_activity", .derivatives_position_opened_observed: "financial_activity",
        .derivatives_position_increased_observed: "financial_activity", .derivatives_position_reduced_observed: "financial_activity",
        .derivatives_position_closed_observed: "financial_activity", .derivatives_position_liquidated_observed: "financial_activity",
        .derivatives_position_adl_observed: "financial_activity", .derivatives_position_settled_observed: "financial_activity",
        .derivatives_position_corrected: "financial_activity", .derivatives_funding_payment_observed: "financial_activity",
        .derivatives_fee_observed: "financial_activity", .derivatives_pnl_snapshot_materialized: "financial_activity",
        .derivatives_exposure_snapshot_materialized: "financial_activity", .derivatives_price_observation_recorded: "financial_activity",
        .derivatives_market_status_changed: "financial_activity", .derivatives_stream_gap_detected: "financial_activity",
        .derivatives_stream_gap_recovered: "financial_activity", .derivatives_stream_checkpoint_advanced: "financial_activity",
        .derivatives_adapter_conformance_run: "financial_activity", .derivatives_reconciliation_run_completed: "financial_activity",
        .derivatives_reconciliation_variance_detected: "financial_activity", .derivatives_reconciliation_variance_resolved: "financial_activity",
        .derivatives_risk_threshold_breached: "financial_activity",
        // Interoperability intelligence family (explicit opt-in)
        .interop_provider_registered: "cross_chain_observability", .interop_gateway_registered: "cross_chain_observability",
        .interop_path_registered: "cross_chain_observability", .interop_application_registered: "cross_chain_observability",
        .interop_verification_actor_registered: "cross_chain_observability", .interop_message_discovered: "cross_chain_observability",
        .interop_message_sent_observed: "cross_chain_observability", .interop_message_source_confirmed: "cross_chain_observability",
        .interop_message_verification_observed: "cross_chain_observability", .interop_message_verified: "cross_chain_observability",
        .interop_message_delivery_attempt_observed: "cross_chain_observability", .interop_message_delivered: "cross_chain_observability",
        .interop_message_executed_observed: "cross_chain_observability", .interop_message_settled: "cross_chain_observability",
        .interop_message_failed: "cross_chain_observability", .interop_message_timeout: "cross_chain_observability",
        .interop_message_expired: "cross_chain_observability", .interop_message_cancelled: "cross_chain_observability",
        .interop_message_refunded_observed: "cross_chain_observability", .interop_message_recovered: "cross_chain_observability",
        .interop_message_reorged: "cross_chain_observability", .interop_message_corrected: "cross_chain_observability",
        .interop_message_correlated: "cross_chain_observability", .interop_intent_observed: "cross_chain_observability",
        .interop_intent_fulfilled_observed: "cross_chain_observability", .interop_asset_leg_locked_observed: "cross_chain_observability",
        .interop_asset_leg_burned_observed: "cross_chain_observability", .interop_asset_leg_minted_observed: "cross_chain_observability",
        .interop_asset_leg_released_observed: "cross_chain_observability", .interop_fee_observed: "cross_chain_observability",
        .interop_security_policy_snapshot_recorded: "cross_chain_observability", .interop_security_policy_changed: "cross_chain_observability",
        .interop_verification_quorum_observed: "cross_chain_observability", .interop_provider_checkpoint_advanced: "cross_chain_observability",
        .interop_stream_gap_detected: "cross_chain_observability", .interop_stream_gap_recovered: "cross_chain_observability",
        .interop_reconciliation_run_completed: "cross_chain_observability", .interop_reconciliation_variance_detected: "cross_chain_observability",
        .interop_reconciliation_variance_resolved: "cross_chain_observability"
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
        self.sessionId = UUID().uuidString
        self.sessionStart = Date()

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
            appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
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


    public func startJourney(_ nameOrType: String, properties: [String: AnyCodable] = [:]) {
        currentJourneyId = properties["journeyId"]?.value as? String ?? UUID().uuidString
        currentJourneyName = nameOrType
        var props = properties; props["journeyId"] = AnyCodable(currentJourneyId ?? ""); props["journeyName"] = AnyCodable(nameOrType); props["journeyType"] = AnyCodable(nameOrType); props["journeyStatus"] = AnyCodable("started")
        enqueueEvent(type: .journey_started, properties: props)
    }

    public func pauseJourney(_ reason: String? = nil, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["pauseReason"] = AnyCodable(reason ?? ""); props["journeyStatus"] = AnyCodable("paused")
        enqueueEvent(type: .journey_paused, properties: props)
    }

    public func resumeJourney(_ reason: String? = nil, properties: [String: AnyCodable] = [:]) {
        if currentJourneyId == nil { currentJourneyId = properties["journeyId"]?.value as? String ?? UUID().uuidString }
        var props = properties; props["journeyId"] = AnyCodable(currentJourneyId ?? ""); props["resumeReason"] = AnyCodable(reason ?? ""); props["journeyStatus"] = AnyCodable("resumed")
        enqueueEvent(type: .journey_resumed, properties: props)
    }

    public func continueJourney(_ stepIdOrName: String, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["stepId"] = AnyCodable(stepIdOrName); props["stepName"] = AnyCodable(stepIdOrName); props["journeyStatus"] = AnyCodable("continued")
        enqueueEvent(type: .journey_continued, properties: props)
    }

    public func completeJourney(_ reason: String? = nil, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["completionReason"] = AnyCodable(reason ?? ""); props["journeyStatus"] = AnyCodable("completed")
        enqueueEvent(type: .journey_completed, properties: props); currentJourneyId = nil
    }

    public func abandonJourney(_ reason: String? = nil, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["abandonmentReason"] = AnyCodable(reason ?? ""); props["journeyStatus"] = AnyCodable("abandoned")
        enqueueEvent(type: .journey_abandoned, properties: props); currentJourneyId = nil
    }

    public func checkpointJourney(_ stepIdOrName: String, properties: [String: AnyCodable] = [:]) {
        guard let journeyId = currentJourneyId else { return }
        var props = properties; props["journeyId"] = AnyCodable(journeyId); props["stepId"] = AnyCodable(stepIdOrName); props["stepName"] = AnyCodable(stepIdOrName); props["journeyStatus"] = AnyCodable("checkpoint")
        enqueueEvent(type: .journey_checkpoint, properties: props)
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
        defaults.removeObject(forKey: "userId")
        defaults.removeObject(forKey: "walletAddress")
        defaults.removeObject(forKey: "consentState")
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
        serialQueue.async { [weak self] in
            guard let self = self, !self.eventQueue.isEmpty else { return }
            let maxPersist = 1000
            let toSave = Array(self.eventQueue.suffix(maxPersist))
            guard let url = self.persistedQueueURL else { return }
            do {
                let dir = url.deletingLastPathComponent()
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let data = try JSONEncoder().encode(toSave)
                try data.write(to: url, options: .atomic)
            } catch {
                self.log("Failed to persist queue: \(error)")
            }
        }
    }

    private func loadPersistedQueue() {
        guard let url = persistedQueueURL,
              FileManager.default.fileExists(atPath: url.path),
              let data = try? Data(contentsOf: url),
              let events = try? JSONDecoder().decode([AetherEvent].self, from: data) else { return }
        serialQueue.async { [weak self] in
            guard let self = self else { return }
            let capacity = max(0, Aether.maxQueueSize - self.eventQueue.count)
            let toRestore = Array(events.prefix(capacity))
            self.eventQueue.insert(contentsOf: toRestore, at: 0)
            self.log("Restored \(toRestore.count) events from persistent queue")
        }
        try? FileManager.default.removeItem(at: url)
    }

    private func clearPersistedQueue() {
        if let url = persistedQueueURL { try? FileManager.default.removeItem(at: url) }
    }

    // MARK: - Deep Link Attribution

    public func handleDeepLink(_ url: URL) {
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        var attribution: [String: AnyCodable] = ["url": AnyCodable(url.absoluteString)]
        var clickIds: [String: String] = [:]

        for item in components?.queryItems ?? [] {
            if item.name.hasPrefix("utm_") {
                attribution[item.name] = AnyCodable(item.value ?? "")
            }
            if Self.clickIdParams.contains(item.name), let val = item.value {
                clickIds[item.name] = val
                attribution[item.name] = AnyCodable(val)
            }
        }

        // Store campaign info for inclusion in event context
        self.campaignInfo = EventContext.CampaignInfo(
            source: attribution["utm_source"]?.value as? String,
            medium: attribution["utm_medium"]?.value as? String,
            campaign: attribution["utm_campaign"]?.value as? String,
            content: attribution["utm_content"]?.value as? String,
            term: attribution["utm_term"]?.value as? String,
            clickIds: clickIds,
            referrerDomain: components?.host
        )

        track("deep_link_opened", properties: attribution)
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
    // Canonical purposes (see packages/shared/consent.ts):
    //   "analytics", "marketing", "web3", "agent", "commerce"
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
        let grantable = AetherSDK.canonicalConsentPurposes.filter {
            !AetherSDK.explicitOptInPurposes.contains($0)
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
        guard let flags = serverConfig["featureFlags"] as? [String: Any],
              let value = flags[key] as? Bool else { return defaultValue }
        return value
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
            return
        }

        let scrubbedProps = scrubSensitiveFields(properties)
        let event = AetherEvent(
            id: UUID().uuidString,
            type: type,
            timestamp: ISO8601DateFormatter().string(from: Date()),
            sessionId: sessionId,
            anonymousId: anonymousId,
            userId: userId,
            properties: scrubbedProps,
            context: buildContext()
        )

        serialQueue.async { [weak self] in
            guard let self = self else { return }
            // Enforce max queue size
            while self.eventQueue.count >= Aether.maxQueueSize { self.eventQueue.removeFirst() }
            self.eventQueue.append(event)
            self.eventCount += 1
            if let batchSize = self.config?.batchSize, self.eventQueue.count >= batchSize {
                self.sendBatch()
            }
        }
    }

    private func sendBatch() {
        guard !eventQueue.isEmpty, let config = config else { return }

        let batch = Array(eventQueue.prefix(config.batchSize))
        eventQueue.removeFirst(min(batch.count, eventQueue.count))

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

        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
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
                    self.serialQueue.async { self.eventQueue.insert(contentsOf: batch, at: 0) }
                }
            } else if statusCode == 429 {
                let retryAfter = (response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Retry-After")
                    .flatMap { Double($0) } ?? 5.0
                if retryCount < maxRetries {
                    DispatchQueue.global().asyncAfter(deadline: .now() + retryAfter) {
                        self.sendBatchWithRetry(batch: batch, config: config, retryCount: retryCount + 1)
                    }
                }
            } else if statusCode >= 500 {
                if retryCount < maxRetries {
                    let delay = min(pow(2.0, Double(retryCount)), 30.0)
                    DispatchQueue.global().asyncAfter(deadline: .now() + delay) {
                        self.sendBatchWithRetry(batch: batch, config: config, retryCount: retryCount + 1)
                    }
                } else {
                    self.log("Batch dropped after \(maxRetries) retries (server error \(statusCode))")
                }
            } else if statusCode >= 400 {
                self.log("Batch rejected (client error \(statusCode)) — not retrying")
            } else {
                // 2xx success — remove persisted snapshot so next launch does not re-deliver
                self.clearPersistedQueue()
            }
        }.resume()
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

    private func buildContext() -> EventContext {
        let granted = Set(consentState)

        #if canImport(UIKit)
        let osName = "iOS"
        let osVersion = UIDevice.current.systemVersion
        #else
        let osName = "macOS"
        let osVersion = ProcessInfo.processInfo.operatingSystemVersionString
        #endif

        return EventContext(
            library: .init(name: "aether-ios", version: "8.12.0"),
            device: .init(
                osName: osName,
                osVersion: osVersion,
                locale: Locale.current.identifier,
                timezone: TimeZone.current.identifier
            ),
            campaign: self.campaignInfo,
            fingerprint: .init(id: self.fingerprintId),
            network: currentNetworkType,
            thermalState: thermalStateString(),
            consent: [
                "analytics": granted.contains("analytics"),
                "marketing": granted.contains("marketing"),
                "web3": granted.contains("web3"),
                "agent": granted.contains("agent"),
                "commerce": granted.contains("commerce"),
            ]
        )
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
            (key, Self.sensitiveKeys.contains(key.lowercased()) ? AnyCodable("[REDACTED]") : value)
        })
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
