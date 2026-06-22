// =============================================================================
// Aether SDK — CORE TYPE DEFINITIONS (web package)
//
// These types MIRROR the canonical contracts in packages/shared/*.ts.
// Keep in sync with: packages/shared/{events,consent,wallet,identity,
// entities,commerce,agent,provenance,capabilities,schema-version}.ts
//
// Any change to an EventType, ConsentPurpose, VMType, or envelope field MUST
// also be made in packages/shared and bump CONTRACT_SCHEMA_VERSION.
// =============================================================================

/**
 * Identity resolved from a prior device/session via wallet address lookup.
 * Returned by POST /sdk/identity/resolve when a known wallet is recognized.
 */
export interface ResolvedIdentity {
  userId?: string;
  anonymousId: string;
  traits?: Record<string, unknown>;
  wallets?: ConnectedWallet[];
  resolvedAt: string;
}

/** SDK configuration passed to Aether.init() */
export interface AetherConfig {
  /** API key from the Aether dashboard (required) */
  apiKey: string;
  /** Deployment environment */
  environment?: 'production' | 'staging' | 'development';
  /** Host application version, reported in SDK fleet heartbeats */
  appVersion?: string;
  /** Enable debug logging */
  debug?: boolean;
  /** Data collection endpoint override */
  endpoint?: string;
  /** WebSocket endpoint override */
  wsEndpoint?: string;
  /** Feature modules to enable */
  modules?: ModuleConfig;
  /** Privacy and compliance settings */
  privacy?: PrivacyConfig;
  /** Advanced performance settings */
  advanced?: AdvancedConfig;
  /**
   * Automatically attempt to resolve a prior user journey when a wallet
   * connects. Calls POST /sdk/identity/resolve with the wallet address.
   * Defaults to true.
   */
  autoResumeJourney?: boolean;
  /**
   * Called when a prior journey is detected and resumed on this device.
   * Receives the merged identity from the backend.
   */
  onJourneyResumed?: (identity: ResolvedIdentity) => void;
  /** Client-side inactivity window before an incomplete journey is considered abandoned. */
  journeyTimeoutMs?: number;
}


/**
 * Module toggles read by AetherSDK.init().
 *
 * Flags are declared here ONLY if the SDK runtime actually gates behavior on
 * them. DeFi/NFT/portfolio/whale classification is performed backend-side
 * from `wallet` + `transaction` events — no client-side flags exist for it.
 */
export interface ModuleConfig {
  // Core analytics
  autoDiscovery?: boolean;
  ecommerce?: boolean;
  formAnalytics?: boolean;
  featureFlags?: boolean;
  heatmaps?: boolean;
  funnels?: boolean;
  // Performance
  performance?: boolean | { sampleRate?: number };
  // Wallet / multi-VM capture
  walletTracking?: boolean;   // evm
  svmTracking?: boolean;
  bitcoinTracking?: boolean;
  moveTracking?: boolean;
  nearTracking?: boolean;
  tronTracking?: boolean;
  cosmosTracking?: boolean;
  aptosTracking?: boolean;
  tonTracking?: boolean;
  starknetTracking?: boolean;
  cardanoTracking?: boolean;
  substrateTracking?: boolean;
  algorandTracking?: boolean;
  hederaTracking?: boolean;
  stellarTracking?: boolean;
  icpTracking?: boolean;
  // Cosmos multi-chain — list of chain IDs to enable (defaults to sei-pacific-1 only)
  cosmosChains?: string[];
  // Connect-time data enrichment (optional, adds latency)
  approvalScan?: boolean;
  domainResolution?: boolean;
  networkContext?: boolean;
}

export interface PrivacyConfig {
  /** Anonymize IP addresses before transmission */
  anonymizeIP?: boolean;
  /** Enable full GDPR compliance mode */
  gdprMode?: boolean;
  /** Enable CCPA compliance mode */
  ccpaMode?: boolean;
  /** Respect Do Not Track browser header */
  respectDNT?: boolean;
  /** Mask sensitive form fields (passwords, credit cards) */
  maskSensitiveFields?: boolean;
  /** Cookie consent requirement level */
  cookieConsent?: 'none' | 'notice' | 'opt-in' | 'opt-out';
  /** Custom PII field patterns to mask */
  piiPatterns?: RegExp[];
}

export interface AdvancedConfig {
  /** Session heartbeat interval in ms (default: 30000) */
  heartbeatInterval?: number;
  /** Event batch size before flush (default: 10) */
  batchSize?: number;
  /** Batch flush interval in ms (default: 5000) */
  flushInterval?: number;
  /** Max events in queue before forced flush (default: 100) */
  maxQueueSize?: number;
  /** Retry configuration */
  retry?: RetryConfig;
  /** Custom HTTP headers for API requests */
  customHeaders?: Record<string, string>;
}

export interface RetryConfig {
  maxRetries?: number;
  baseDelay?: number;
  maxDelay?: number;
  backoffMultiplier?: number;
}

// =============================================================================
// FINGERPRINT TYPES
// =============================================================================

export interface FingerprintComponents {
  canvasHash: string;
  webglRenderer: string;
  webglVendor: string;
  audioHash: string;
  screenResolution: string;
  colorDepth: number;
  timezone: string;
  language: string;
  languages: string[];
  platform: string;
  hardwareConcurrency: number;
  deviceMemory: number;
  touchSupport: boolean;
  fontHash: string;
  cookieEnabled: boolean;
  doNotTrack: string | null;
  pixelRatio: number;
}

// =============================================================================
// MULTI-VM TYPES
// =============================================================================

/** Virtual machine family */
export type VMType = 'evm' | 'svm' | 'bitcoin' | 'movevm' | 'near' | 'tvm' | 'cosmos' | 'aptos' | 'ton' | 'starknet' | 'cardano' | 'substrate' | 'algorand' | 'hedera' | 'stellar' | 'icp';

/** Wallet classification by security model */
export type WalletClassification = 'hot' | 'cold' | 'smart' | 'exchange' | 'protocol' | 'multisig';

/** DeFi protocol categories */
export type DeFiCategory =
  | 'dex'
  | 'router'
  | 'lending'
  | 'staking'
  | 'restaking'
  | 'perpetuals'
  | 'options'
  | 'bridge'
  | 'cex'
  | 'yield'
  | 'nft_marketplace'
  | 'governance'
  | 'payments'
  | 'insurance'
  | 'launchpad';

/** Chain information across all VMs */
export interface ChainInfo {
  vm: VMType;
  chainId: number | string;
  name: string;
  shortName: string;
  nativeCurrency: { name: string; symbol: string; decimals: number };
  rpcUrl?: string;
  explorerUrl?: string;
  isTestnet: boolean;
  isL2?: boolean;
  logoUrl?: string;
}

/** Connected wallet across any VM */
export interface ConnectedWallet {
  address: string;
  vm: VMType;
  chainId: number | string;
  walletType: string;
  displayName: string;
  classification: WalletClassification;
  ens?: string;
  sns?: string;
  suiNS?: string;
  nearAccountId?: string;
  connectedAt: string;
  isConnected: boolean;
  isPrimary: boolean;
}

/** Token balance for any chain */
export interface TokenBalance {
  symbol: string;
  name: string;
  contractAddress: string;
  balance: string;
  decimals: number;
  usdValue?: number;
  vm: VMType;
  chainId: number | string;
  standard: 'native' | 'erc20' | 'spl' | 'brc20' | 'trc20' | 'nep141' | 'ibc' | 'sui_coin';
  logoUrl?: string;
}

/** NFT asset for any chain */
export interface NFTAsset {
  contractAddress: string;
  tokenId: string;
  name?: string;
  collection?: string;
  imageUrl?: string;
  standard: 'erc721' | 'erc1155' | 'metaplex' | 'trc721' | 'nep171' | 'sui_object' | 'ordinal';
  vm: VMType;
  chainId: number | string;
  floorPrice?: number;
  lastSalePrice?: number;
}

/** DeFi position across any protocol */
export interface DeFiPosition {
  protocol: string;
  category: DeFiCategory;
  positionType: string;
  assets: { symbol: string; amount: string; side?: 'supply' | 'borrow' | 'long' | 'short' }[];
  valueUSD?: number;
  apy?: number;
  healthFactor?: number;
  pnl?: number;
  pnlPercent?: number;
  leverage?: number;
  liquidationPrice?: number;
  vm: VMType;
  chainId: number | string;
  entryTimestamp?: string;
}

/** Whale alert event data */
export interface WhaleAlert {
  txHash: string;
  value: string;
  valueUSD?: number;
  from: string;
  to: string;
  chainId: number | string;
  vm: VMType;
  threshold: string;
  token?: string;
  protocol?: string;
  fromLabel?: string;
  toLabel?: string;
}

/** Gas/fee analytics across VMs */
export interface GasAnalytics {
  gasPrice?: string;
  gasUsed?: string;
  gasCostNative: string;
  gasCostUSD?: number;
  chainId: number | string;
  vm: VMType;
  computeUnits?: number;
  priorityFee?: string;
  energyUsed?: number;
  bandwidthUsed?: number;
}

/** Cross-chain portfolio snapshot */
export interface PortfolioSnapshot {
  wallets: ConnectedWallet[];
  totalValueUSD?: number;
  chains: { vm: VMType; chainId: number | string; name: string; valueUSD?: number }[];
  tokens: TokenBalance[];
  nfts: NFTAsset[];
  defiPositions: DeFiPosition[];
  timestamp: string;
}

/** Bridge transfer data */
export interface BridgeTransfer {
  sourceChain: { vm: VMType; chainId: number | string; name: string };
  destChain: { vm: VMType; chainId: number | string; name: string };
  token: string;
  amount: string;
  fee?: string;
  bridge: string;
  status: 'initiated' | 'in_flight' | 'completed' | 'failed' | 'refunded';
  sourceTxHash?: string;
  destTxHash?: string;
  estimatedTime?: number;
}

/** Known address label */
export interface AddressLabel {
  address: string;
  name: string;
  category: 'cex' | 'dex' | 'bridge' | 'dao' | 'whale' | 'protocol' | 'deployer' | 'validator';
  subcategory?: string;
  confidence: number;
  chainId: number | string;
  vm: VMType;
}

/** Perpetual/derivatives position data */
export interface PerpetualPosition {
  protocol: string;
  market: string;
  side: 'long' | 'short';
  size: string;
  collateral: string;
  leverage: number;
  entryPrice: string;
  markPrice?: string;
  liquidationPrice?: string;
  unrealizedPnl?: string;
  realizedPnl?: string;
  fundingRate?: string;
  vm: VMType;
  chainId: number | string;
}

/** Options position data */
export interface OptionsPosition {
  protocol: string;
  underlying: string;
  optionType: 'call' | 'put';
  strikePrice: string;
  expiryDate: string;
  premium: string;
  size: string;
  side: 'buy' | 'sell';
  iv?: number;
  delta?: number;
  vm: VMType;
  chainId: number | string;
}

/** Protocol identification info */
export interface ProtocolInfo {
  name: string;
  category: DeFiCategory;
  chains: Record<string, string[]>;
  website?: string;
  logoUrl?: string;
}

// =============================================================================
// EVENT TYPES
// =============================================================================

/**
 * Canonical EventType — mirrors packages/shared/events.ts.
 *
 * Do NOT add web3 sub-type events (defi_interaction, whale_alert, etc.) —
 * those are computed backend-side from `wallet`/`transaction` events.
 */
export type EventType =
  // Core analytics
  | 'track'
  | 'page'
  | 'screen'
  | 'heartbeat'
  | 'error'
  | 'performance'
  | 'experiment'
  // Journey lifecycle
  | 'journey_started'
  | 'journey_paused'
  | 'journey_resumed'
  | 'journey_continued'
  | 'journey_completed'
  | 'journey_abandoned'
  | 'journey_checkpoint'
  // Identity
  | 'identify'
  | 'consent'
  // Commerce / access (Web2 + Web3 unified)
  | 'conversion'
  | 'payment_initiated'
  | 'payment_completed'
  | 'payment_failed'
  | 'approval_requested'
  | 'approval_resolved'
  | 'entitlement_granted'
  | 'entitlement_revoked'
  | 'access_granted'
  | 'access_denied'
  // Wallet / on-chain (optional)
  | 'wallet'
  | 'transaction'
  | 'contract_action'
  // Agent lifecycle — legacy (kept for backward compatibility)
  | 'agent_task'
  | 'agent_decision'
  | 'a2h_interaction'
  // Agent lifecycle — granular events
  | 'agent_registered'
  | 'agent_updated'
  | 'agent_authorized'
  | 'agent_deauthorized'
  | 'agent_capability_granted'
  | 'agent_capability_revoked'
  | 'agent_task_created'
  | 'agent_task_decomposed'
  | 'agent_task_started'
  | 'agent_task_completed'
  | 'agent_task_failed'
  | 'agent_tool_called'
  | 'agent_resource_requested'
  | 'agent_delegated_task'
  | 'agent_subagent_spawned'
  | 'agent_policy_evaluated'
  | 'agent_handoff'
  | 'agent_escalated_to_human'
  | 'agent_outcome_recorded'
  // x402 — legacy (kept for backward compatibility)
  | 'x402_payment'
  // x402 lifecycle — granular events
  | 'x402_resource_requested'
  | 'x402_payment_required'
  | 'x402_quote_received'
  | 'x402_authorization_requested'
  | 'x402_authorization_resolved'
  | 'x402_payment_intent_created'
  | 'x402_payment_submitted'
  | 'x402_payment_settled'
  | 'x402_payment_failed'
  | 'x402_payment_timeout'
  | 'x402_receipt_verified'
  | 'x402_access_granted'
  | 'x402_access_denied'
  | 'x402_refund_or_reversal';


export type JourneyLifecycleEventType =
  | 'journey_started'
  | 'journey_paused'
  | 'journey_resumed'
  | 'journey_continued'
  | 'journey_completed'
  | 'journey_abandoned'
  | 'journey_checkpoint';

export type JourneyStatus = 'started' | 'paused' | 'resumed' | 'continued' | 'completed' | 'abandoned' | 'checkpoint';

export interface JourneyPayload {
  journeyId?: string;
  journeyName?: string;
  journeyType?: string;
  stepId?: string;
  stepName?: string;
  previousStepId?: string;
  nextExpectedStepId?: string;
  journeyStatus?: JourneyStatus;
  pauseReason?: string;
  resumeReason?: string;
  completionReason?: string;
  abandonmentReason?: string;
  handoffFromSessionId?: string;
  handoffFromDeviceId?: string;
  handoffToDeviceId?: string;
  handoffLatencyMs?: number;
  confidence?: number;
  confidenceSignals?: string[];
  sourceSessionId?: string;
  sourceAnonymousId?: string;
  sourceUserId?: string;
  targetSessionId?: string;
  targetAnonymousId?: string;
  targetUserId?: string;
  campaignAttribution?: Record<string, unknown>;
  referrerAttribution?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface CurrentJourney extends JourneyPayload {
  journeyId: string;
  journeyStatus: JourneyStatus;
  startedAt: string;
  updatedAt: string;
}

export interface BaseEvent {

  id: string;
  type: EventType;
  timestamp: string;
  sessionId: string;
  anonymousId: string;
  userId?: string;
  properties?: Record<string, unknown>;
  context: EventContext;
}

export interface EventContext {
  library: { name: string; version: string };
  page?: PageContext;
  device?: DeviceContext;
  campaign?: CampaignContext;
  fingerprint?: { id: string };
  ip?: string;
  locale?: string;
  timezone?: string;
  userAgent?: string;
  consent?: ConsentState;
  semantic?: Record<string, unknown>;
  trafficSource?: Record<string, unknown>;
  network?: NetworkContext;
  journey?: Pick<CurrentJourney, 'journeyId' | 'journeyName' | 'journeyType' | 'journeyStatus'>;
}

export interface NetworkContext {
  effectiveType?: string;
  downlink?: number;
  rtt?: number;
  saveData?: boolean;
}

export interface PageContext {
  url: string;
  path: string;
  title: string;
  referrer: string;
  search: string;
  hash: string;
}

export interface DeviceContext {
  type: 'desktop' | 'mobile' | 'tablet';
  browser: string;
  browserVersion: string;
  os: string;
  osVersion: string;
  screenWidth: number;
  screenHeight: number;
  viewportWidth: number;
  viewportHeight: number;
  pixelRatio: number;
  language: string;
  cookieEnabled: boolean;
  online: boolean;
}

export interface CampaignContext {
  source?: string;
  medium?: string;
  campaign?: string;
  content?: string;
  term?: string;
  clickId?: string;
  referrerDomain?: string;
  referrerType?: 'direct' | 'organic' | 'paid' | 'social' | 'email' | 'referral' | 'unknown';
}

// =============================================================================
// SPECIFIC EVENT INTERFACES
// =============================================================================

export interface TrackEvent extends BaseEvent {
  type: 'track';
  event: string;
}

export interface PageEvent extends BaseEvent {
  type: 'page';
  properties: {
    url: string;
    path: string;
    title: string;
    referrer: string;
    [key: string]: unknown;
  };
}

export interface IdentifyEvent extends BaseEvent {
  type: 'identify';
  userId: string;
  traits?: UserTraits;
}

export interface ConversionEvent extends BaseEvent {
  type: 'conversion';
  event: string;
  properties: {
    value?: number;
    currency?: string;
    orderId?: string;
    products?: ProductItem[];
    [key: string]: unknown;
  };
}

export interface WalletEvent extends BaseEvent {
  type: 'wallet';
  properties: {
    action: 'connect' | 'disconnect' | 'switch_chain' | 'sign' | 'approve'
      | 'sign_message' | 'sign_transaction' | 'approve_token' | 'revoke_token';
    address: string;
    chainId: number | string;
    walletType: string;
    vm?: VMType;
    classification?: WalletClassification;
    ens?: string;
    sns?: string;
    [key: string]: unknown;
  };
}

export interface TransactionEvent extends BaseEvent {
  type: 'transaction';
  properties: {
    txHash: string;
    chainId: number | string;
    from: string;
    to: string;
    value?: string;
    gasUsed?: string;
    gasPrice?: string;
    status: 'pending' | 'confirmed' | 'failed';
    type?: 'transfer' | 'swap' | 'stake' | 'mint' | 'approve' | 'custom'
      | 'bridge' | 'wrap' | 'unwrap' | 'governance' | 'nft_mint' | 'nft_transfer'
      | 'borrow' | 'repay' | 'liquidation' | 'flash_loan'
      | 'open_position' | 'close_position' | 'add_liquidity' | 'remove_liquidity';
    vm?: VMType;
    protocol?: string;
    defiCategory?: DeFiCategory;
    [key: string]: unknown;
  };
}

export interface ErrorEvent extends BaseEvent {
  type: 'error';
  properties: {
    message: string;
    stack?: string;
    filename?: string;
    lineno?: number;
    colno?: number;
    type: string;
    [key: string]: unknown;
  };
}

// ---------------------------------------------------------------------------
// Agent events (L2 — IG_AGENT_LAYER)
// ---------------------------------------------------------------------------

export interface AgentTaskEvent extends BaseEvent {
  type: 'agent_task';
  properties: {
    taskId: string;
    agent: { kind: 'agent'; id: string; label?: string };
    status: 'started' | 'running' | 'completed' | 'failed' | 'cancelled';
    workerType?: string;
    stateRef?: string;
    confidenceDelta?: number;
    durationMs?: number;
    [key: string]: unknown;
  };
}

export interface AgentDecisionEvent extends BaseEvent {
  type: 'agent_decision';
  properties: {
    decisionId: string;
    agent: { kind: 'agent'; id: string; label?: string };
    taskId?: string;
    chosen: string;
    alternatives?: string[];
    confidence?: number;
    [key: string]: unknown;
  };
}

export interface A2HInteractionEvent extends BaseEvent {
  type: 'a2h_interaction';
  properties: {
    interactionId: string;
    agent: { kind: 'agent'; id: string; label?: string };
    user: { kind: 'user'; id: string };
    interaction: 'notify' | 'recommend' | 'deliver' | 'escalate';
    channel?: 'push' | 'email' | 'sms' | 'inapp' | 'webhook';
    [key: string]: unknown;
  };
}

// ---------------------------------------------------------------------------
// Agent lifecycle events — granular events (L2 — IG_AGENT_LAYER)
// Legacy events above are kept for backward compatibility.
// ---------------------------------------------------------------------------

export interface AgentRegisteredEvent extends BaseEvent {
  type: 'agent_registered';
  properties: { tenantId: string; agentId: string; ownerUserId?: string; ownerOrgId?: string; agentName?: string; capabilities?: string[]; [key: string]: unknown };
}
export interface AgentUpdatedEvent extends BaseEvent {
  type: 'agent_updated';
  properties: { tenantId: string; agentId: string; changes?: Record<string, unknown>; [key: string]: unknown };
}
export interface AgentAuthorizedEvent extends BaseEvent {
  type: 'agent_authorized';
  properties: { tenantId: string; agentId: string; authorizationId: string; authorizedBy?: string; scope?: string[]; expiresAt?: string; [key: string]: unknown };
}
export interface AgentDeauthorizedEvent extends BaseEvent {
  type: 'agent_deauthorized';
  properties: { tenantId: string; agentId: string; authorizationId: string; revokedBy?: string; reason?: string; [key: string]: unknown };
}
export interface AgentCapabilityGrantedEvent extends BaseEvent {
  type: 'agent_capability_granted';
  properties: { tenantId: string; agentId: string; capability: string; grantedBy?: string; authorizationId?: string; [key: string]: unknown };
}
export interface AgentCapabilityRevokedEvent extends BaseEvent {
  type: 'agent_capability_revoked';
  properties: { tenantId: string; agentId: string; capability: string; revokedBy?: string; reason?: string; [key: string]: unknown };
}
export interface AgentTaskCreatedEvent extends BaseEvent {
  type: 'agent_task_created';
  properties: { tenantId: string; agentId: string; taskId: string; parentTaskId?: string; taskType?: string; description?: string; [key: string]: unknown };
}
export interface AgentTaskDecomposedEvent extends BaseEvent {
  type: 'agent_task_decomposed';
  properties: { tenantId: string; agentId: string; taskId: string; parentTaskId: string; subtaskIds: string[]; [key: string]: unknown };
}
export interface AgentTaskStartedEvent extends BaseEvent {
  type: 'agent_task_started';
  properties: { tenantId: string; agentId: string; taskId: string; [key: string]: unknown };
}
export interface AgentTaskCompletedEvent extends BaseEvent {
  type: 'agent_task_completed';
  properties: { tenantId: string; agentId: string; taskId: string; outcomeId?: string; durationMs?: number; [key: string]: unknown };
}
export interface AgentTaskFailedEvent extends BaseEvent {
  type: 'agent_task_failed';
  properties: { tenantId: string; agentId: string; taskId: string; failureReason?: string; durationMs?: number; [key: string]: unknown };
}
export interface AgentToolCalledEvent extends BaseEvent {
  type: 'agent_tool_called';
  properties: { tenantId: string; agentId: string; toolId: string; taskId?: string; success?: boolean; durationMs?: number; [key: string]: unknown };
}
export interface AgentResourceRequestedEvent extends BaseEvent {
  type: 'agent_resource_requested';
  properties: { tenantId: string; agentId: string; resourceId: string; taskId?: string; resourceType?: string; provider?: string; [key: string]: unknown };
}
export interface AgentDelegatedTaskEvent extends BaseEvent {
  type: 'agent_delegated_task';
  properties: { tenantId: string; agentId: string; delegationId: string; taskId: string; delegateeAgentId: string; [key: string]: unknown };
}
export interface AgentSubagentSpawnedEvent extends BaseEvent {
  type: 'agent_subagent_spawned';
  properties: { tenantId: string; agentId: string; childAgentId: string; parentAgentId: string; rootAgentId?: string; delegationId?: string; [key: string]: unknown };
}
export interface AgentPolicyEvaluatedEvent extends BaseEvent {
  type: 'agent_policy_evaluated';
  properties: { tenantId: string; agentId: string; policyId: string; decision: string; taskId?: string; confidence?: number; [key: string]: unknown };
}
export interface AgentHandoffEvent extends BaseEvent {
  type: 'agent_handoff';
  properties: { tenantId: string; agentId: string; targetAgentId?: string; targetUserId?: string; taskId?: string; reason?: string; [key: string]: unknown };
}
export interface AgentEscalatedToHumanEvent extends BaseEvent {
  type: 'agent_escalated_to_human';
  properties: { tenantId: string; agentId: string; targetUserId: string; taskId?: string; escalationReason?: string; [key: string]: unknown };
}
export interface AgentOutcomeRecordedEvent extends BaseEvent {
  type: 'agent_outcome_recorded';
  properties: { tenantId: string; agentId: string; outcomeId: string; taskId?: string; success?: boolean; [key: string]: unknown };
}

// ---------------------------------------------------------------------------
// Commerce / access events (unified Web2 + Web3)
// ---------------------------------------------------------------------------

export type PaymentRail = 'fiat' | 'stripe' | 'invoice' | 'onchain' | 'x402' | 'internal_credit';

interface CommercePaymentProps {
  paymentId: string;
  amount: number;
  currency: string;
  rail: PaymentRail;
  payer?: { kind: string; id: string };
  payee?: { kind: string; id: string };
  subject?: { kind: string; id: string };
  external_ref?: string;
  [key: string]: unknown;
}

export interface PaymentInitiatedEvent extends BaseEvent {
  type: 'payment_initiated';
  properties: CommercePaymentProps;
}
export interface PaymentCompletedEvent extends BaseEvent {
  type: 'payment_completed';
  properties: CommercePaymentProps;
}
export interface PaymentFailedEvent extends BaseEvent {
  type: 'payment_failed';
  properties: CommercePaymentProps & { reason?: string };
}

export interface ApprovalRequestedEvent extends BaseEvent {
  type: 'approval_requested';
  properties: {
    approvalId: string;
    requester?: { kind: string; id: string };
    subject?: { kind: string; id: string };
    reason?: string;
    [key: string]: unknown;
  };
}
export interface ApprovalResolvedEvent extends BaseEvent {
  type: 'approval_resolved';
  properties: {
    approvalId: string;
    status: 'approved' | 'rejected' | 'escalated' | 'expired';
    decidedBy?: string;
    reason?: string;
    [key: string]: unknown;
  };
}

export interface EntitlementGrantedEvent extends BaseEvent {
  type: 'entitlement_granted';
  properties: {
    entitlementId: string;
    holder?: { kind: string; id: string };
    resource?: { kind: string; id: string };
    expiresAt?: string;
    [key: string]: unknown;
  };
}
export interface EntitlementRevokedEvent extends BaseEvent {
  type: 'entitlement_revoked';
  properties: {
    entitlementId: string;
    reason?: string;
    [key: string]: unknown;
  };
}

export interface AccessGrantedEvent extends BaseEvent {
  type: 'access_granted';
  properties: {
    resource: { kind: string; id: string };
    actor?: { kind: string; id: string };
    [key: string]: unknown;
  };
}
export interface AccessDeniedEvent extends BaseEvent {
  type: 'access_denied';
  properties: {
    resource: { kind: string; id: string };
    actor?: { kind: string; id: string };
    reason?: string;
    [key: string]: unknown;
  };
}

// ---------------------------------------------------------------------------
// x402 (L3b — IG_X402_LAYER)
// ---------------------------------------------------------------------------

export interface X402PaymentEvent extends BaseEvent {
  type: 'x402_payment';
  properties: {
    captureId: string;
    payerAgentId: string;
    payeeServiceId: string;
    amount: number;
    currency: string;
    chain?: string;
    txHash?: string;
    [key: string]: unknown;
  };
}

// ---------------------------------------------------------------------------
// x402 lifecycle events — granular events (L3b — IG_X402_LAYER)
// Legacy x402_payment above is kept for backward compatibility.
// ---------------------------------------------------------------------------

export interface X402ResourceRequestedEvent extends BaseEvent {
  type: 'x402_resource_requested';
  properties: { tenantId: string; agentId: string; resourceId?: string; serviceId?: string; provider?: string; protocol?: string; [key: string]: unknown };
}
export interface X402PaymentRequiredEvent extends BaseEvent {
  type: 'x402_payment_required';
  properties: { tenantId: string; agentId: string; resourceId?: string; amount?: string; currency?: string; paymentTerms?: Record<string, unknown>; [key: string]: unknown };
}
export interface X402QuoteReceivedEvent extends BaseEvent {
  type: 'x402_quote_received';
  properties: { tenantId: string; agentId: string; quoteId?: string; quotedAmount?: string; quotedCurrency?: string; facilitatorId?: string; [key: string]: unknown };
}
export interface X402AuthorizationRequestedEvent extends BaseEvent {
  type: 'x402_authorization_requested';
  properties: { tenantId: string; agentId: string; authorizationId: string; paymentIntentId?: string; [key: string]: unknown };
}
export interface X402AuthorizationResolvedEvent extends BaseEvent {
  type: 'x402_authorization_resolved';
  properties: { tenantId: string; agentId: string; authorizationId: string; resolution: string; paymentIntentId?: string; [key: string]: unknown };
}
export interface X402PaymentIntentCreatedEvent extends BaseEvent {
  type: 'x402_payment_intent_created';
  properties: { tenantId: string; agentId: string; paymentIntentId: string; amount?: string; currency?: string; provider?: string; protocol?: string; [key: string]: unknown };
}
export interface X402PaymentSubmittedEvent extends BaseEvent {
  type: 'x402_payment_submitted';
  properties: { tenantId: string; agentId: string; paymentIntentId: string; settlementEventId?: string; txHash?: string; [key: string]: unknown };
}
export interface X402PaymentSettledEvent extends BaseEvent {
  type: 'x402_payment_settled';
  properties: { tenantId: string; agentId: string; paymentIntentId: string; settlementEventId: string; txHash?: string; executionId?: string; [key: string]: unknown };
}
export interface X402PaymentFailedEvent extends BaseEvent {
  type: 'x402_payment_failed';
  properties: { tenantId: string; agentId: string; paymentIntentId: string; failureReason?: string; settlementEventId?: string; [key: string]: unknown };
}
export interface X402PaymentTimeoutEvent extends BaseEvent {
  type: 'x402_payment_timeout';
  properties: { tenantId: string; agentId: string; paymentIntentId: string; timeoutReason?: string; [key: string]: unknown };
}
export interface X402ReceiptVerifiedEvent extends BaseEvent {
  type: 'x402_receipt_verified';
  properties: { tenantId: string; agentId: string; receiptId: string; paymentIntentId?: string; settlementEventId?: string; [key: string]: unknown };
}
export interface X402AccessGrantedEvent extends BaseEvent {
  type: 'x402_access_granted';
  properties: { tenantId: string; agentId: string; paymentIntentId?: string; settlementEventId?: string; executionId?: string; [key: string]: unknown };
}
export interface X402AccessDeniedEvent extends BaseEvent {
  type: 'x402_access_denied';
  properties: { tenantId: string; agentId: string; paymentIntentId?: string; denialReason?: string; [key: string]: unknown };
}
export interface X402RefundOrReversalEvent extends BaseEvent {
  type: 'x402_refund_or_reversal';
  properties: { tenantId: string; agentId: string; settlementEventId: string; reversalType: string; paymentIntentId?: string; refundAmount?: string; [key: string]: unknown };
}

// ---------------------------------------------------------------------------
// On-chain action (L0 — IG_ONCHAIN_LAYER)
// ---------------------------------------------------------------------------

export interface ContractActionEvent extends BaseEvent {
  type: 'contract_action';
  properties: {
    actionType: string;
    chainId: string;
    contractAddress?: string;
    txHash?: string;
    method?: string;
    [key: string]: unknown;
  };
}

export interface JourneyLifecycleEvent extends BaseEvent {
  type: JourneyLifecycleEventType;
  properties: JourneyPayload;
}

export type AetherEvent =
  | JourneyLifecycleEvent
  | TrackEvent
  | PageEvent
  | IdentifyEvent
  | ConversionEvent
  | WalletEvent
  | TransactionEvent
  | ErrorEvent
  // agent legacy
  | AgentTaskEvent
  | AgentDecisionEvent
  | A2HInteractionEvent
  // agent lifecycle
  | AgentRegisteredEvent
  | AgentUpdatedEvent
  | AgentAuthorizedEvent
  | AgentDeauthorizedEvent
  | AgentCapabilityGrantedEvent
  | AgentCapabilityRevokedEvent
  | AgentTaskCreatedEvent
  | AgentTaskDecomposedEvent
  | AgentTaskStartedEvent
  | AgentTaskCompletedEvent
  | AgentTaskFailedEvent
  | AgentToolCalledEvent
  | AgentResourceRequestedEvent
  | AgentDelegatedTaskEvent
  | AgentSubagentSpawnedEvent
  | AgentPolicyEvaluatedEvent
  | AgentHandoffEvent
  | AgentEscalatedToHumanEvent
  | AgentOutcomeRecordedEvent
  // commerce
  | PaymentInitiatedEvent
  | PaymentCompletedEvent
  | PaymentFailedEvent
  | ApprovalRequestedEvent
  | ApprovalResolvedEvent
  | EntitlementGrantedEvent
  | EntitlementRevokedEvent
  | AccessGrantedEvent
  | AccessDeniedEvent
  // x402 legacy
  | X402PaymentEvent
  // x402 lifecycle
  | X402ResourceRequestedEvent
  | X402PaymentRequiredEvent
  | X402QuoteReceivedEvent
  | X402AuthorizationRequestedEvent
  | X402AuthorizationResolvedEvent
  | X402PaymentIntentCreatedEvent
  | X402PaymentSubmittedEvent
  | X402PaymentSettledEvent
  | X402PaymentFailedEvent
  | X402PaymentTimeoutEvent
  | X402ReceiptVerifiedEvent
  | X402AccessGrantedEvent
  | X402AccessDeniedEvent
  | X402RefundOrReversalEvent
  | ContractActionEvent;

// =============================================================================
// IDENTITY TYPES
// =============================================================================

export interface UserTraits {
  email?: string;
  name?: string;
  firstName?: string;
  lastName?: string;
  phone?: string;
  avatar?: string;
  company?: string;
  plan?: string;
  createdAt?: string;
  [key: string]: unknown;
}

export interface IdentityData {
  userId?: string;
  walletAddress?: string;
  walletType?: string;
  chainId?: number;
  ens?: string;
  traits?: UserTraits;
  /** Multi-wallet linking (EVM + SVM + BTC + ...) */
  wallets?: ConnectedWallet[];
  /** Email address for identity resolution */
  email?: string;
  /** Phone number for identity resolution */
  phone?: string;
  /** OAuth provider name (e.g. 'google', 'github') */
  oauthProvider?: string;
  /** OAuth subject identifier */
  oauthSubject?: string;
}

export interface Identity {
  anonymousId: string;
  userId?: string;
  /** @deprecated Use wallets[] array. Kept for backwards compatibility. */
  walletAddress?: string;
  /** @deprecated Use wallets[] array. Kept for backwards compatibility. */
  walletType?: string;
  /** @deprecated Use wallets[] array. Kept for backwards compatibility. */
  chainId?: number;
  /** @deprecated Use wallets[] array. Kept for backwards compatibility. */
  ens?: string;
  /** All connected wallets across VMs */
  wallets: ConnectedWallet[];
  traits: UserTraits;
  firstSeen: string;
  lastSeen: string;
  sessionCount: number;
}

// =============================================================================
// SESSION TYPES
// =============================================================================

export interface Session {
  id: string;
  startedAt: string;
  lastActivityAt: string;
  pageCount: number;
  eventCount: number;
  landingPage: string;
  currentPage: string;
  referrer: string;
  campaign?: CampaignContext;
  device: DeviceContext;
  isActive: boolean;
}

// =============================================================================
// WEB3 TYPES
// =============================================================================

/** Multi-protocol domain names resolved at connect time. */
export interface DomainNames {
  ens?: string;
  uns?: string;
  lens?: string;
  sns?: string;
  avvy?: string;
  fns?: string;
}

/** Bitcoin-specific metadata captured at connect time. */
export interface BitcoinExtended {
  addressType: 'taproot' | 'native_segwit' | 'segwit' | 'legacy' | 'unknown';
  hasOrdinals?: boolean;
  hasInscriptions?: boolean;
  utxoCount?: number;
}

/** EVM blockchain network state captured at wallet connect time. */
export interface BlockchainNetworkContext {
  blockNumber: number;
  gasPrice?: string;
  baseFee?: string;
  priorityFee?: string;
  congestionLevel: 'low' | 'medium' | 'high';
  timestamp: string;
}

/** EVM token approval risk summary captured at connect time. */
export interface TokenApproval {
  tokenAddress: string;
  tokenSymbol?: string;
  spender: string;
  spenderLabel?: string;
  allowance: string;
  isUnlimited: boolean;
  riskLevel: 'low' | 'medium' | 'high';
  chainId: number;
}

export interface WalletInfo {
  address: string;
  chainId: number | string;
  type: string;
  vm?: VMType;
  classification?: WalletClassification;
  ens?: string;
  sns?: string;
  isConnected: boolean;
  connectedAt?: string;
  domainNames?: DomainNames;
  networkSnapshot?: BlockchainNetworkContext;
  approvalRisk?: { hasUnlimitedApprovals: boolean; highRiskCount: number };
  bitcoinExtended?: BitcoinExtended;
}

export interface TransactionOptions {
  chainId?: number | string;
  type?: 'transfer' | 'swap' | 'stake' | 'mint' | 'approve' | 'custom'
    | 'bridge' | 'wrap' | 'unwrap' | 'governance' | 'nft_mint' | 'nft_transfer'
    | 'borrow' | 'repay' | 'liquidation' | 'flash_loan'
    | 'open_position' | 'close_position' | 'add_liquidity' | 'remove_liquidity';
  value?: string;
  from?: string;
  to?: string;
  vm?: VMType;
  protocol?: string;
  defiCategory?: DeFiCategory;
  metadata?: Record<string, unknown>;
}

/** Solana-specific transaction options */
export interface SolanaTransactionOptions extends TransactionOptions {
  signature?: string;
  cluster?: 'mainnet-beta' | 'devnet' | 'testnet';
  computeUnits?: number;
  priorityFee?: string;
}

/** Bitcoin-specific transaction options */
export interface BitcoinTransactionOptions extends TransactionOptions {
  utxos?: { txid: string; vout: number; value: number }[];
  feeRate?: number;
  isInscription?: boolean;
}

// =============================================================================
// CONSENT TYPES
// =============================================================================

export interface ConsentState {
  analytics: boolean;
  marketing: boolean;
  personalization: boolean;
  web3: boolean;
  agent: boolean;
  commerce: boolean;
  /** Always requires explicit opt-in — never granted by accept-all. */
  credit: boolean;
  /** Always requires explicit opt-in — never granted by accept-all. */
  location: boolean;
  updatedAt: string;
  policyVersion: string;
}

export type ConsentPurpose =
  | 'analytics'
  | 'marketing'
  | 'personalization'
  | 'web3'
  | 'agent'
  | 'commerce'
  | 'credit'
  | 'location';

export interface ConsentConfig {
  purposes: ConsentPurpose[];
  policyUrl: string;
  policyVersion: string;
  bannerConfig?: ConsentBannerConfig;
}

export interface ConsentBannerConfig {
  position?: 'bottom' | 'top' | 'center';
  theme?: 'light' | 'dark';
  title?: string;
  description?: string;
  acceptAllText?: string;
  rejectAllText?: string;
  customizeText?: string;
  accentColor?: string;
}

// =============================================================================
// PRODUCT / ECOMMERCE TYPES
// =============================================================================

export interface ProductItem {
  id: string;
  name: string;
  price: number;
  quantity: number;
  category?: string;
  brand?: string;
  variant?: string;
  [key: string]: unknown;
}

// =============================================================================
// CALLBACK / LISTENER TYPES
// =============================================================================

export type EventCallback = (event: AetherEvent) => void;
export type ErrorCallback = (error: Error) => void;
export type ConsentCallback = (consent: ConsentState) => void;
export type WalletChangeCallback = (wallets: ConnectedWallet[]) => void;

/** Plugin interface for extending SDK functionality */
export interface AetherPlugin {
  name: string;
  version: string;
  init(sdk: AetherSDKInterface): void;
  destroy(): void;
}

/** Public SDK interface */
export interface AetherSDKInterface {
  init(config: AetherConfig): void;
  track(event: string, properties?: Record<string, unknown>): void;
  error(message: string, error?: Error | unknown, properties?: Record<string, unknown>): void;
  pageView(page?: string, properties?: Record<string, unknown>): void;
  conversion(event: string, value?: number, properties?: Record<string, unknown>): void;
  hydrateIdentity(data: IdentityData): void;
  getIdentity(): Identity | null;
  reset(): void;
  flush(): Promise<void>;
  destroy(): void;
  startJourney(nameOrType: string, properties?: JourneyPayload): CurrentJourney | null;
  pauseJourney(reason?: string, properties?: JourneyPayload): void;
  resumeJourney(reason?: string, properties?: JourneyPayload): void;
  continueJourney(stepIdOrName: string, properties?: JourneyPayload): void;
  completeJourney(reason?: string, properties?: JourneyPayload): void;
  abandonJourney(reason?: string, properties?: JourneyPayload): void;
  checkpointJourney(stepIdOrName: string, properties?: JourneyPayload): void;
  getCurrentJourney(): CurrentJourney | null;
  onJourneyResumed(callback: (identity: ResolvedIdentity) => void): () => void;
  wallet: WalletInterface;
  consent: ConsentInterface;
  /** Thin emitter for commerce/access events (rail-agnostic). */
  commerce: CommerceInterface;
  /** Thin emitter for agent events (L2 + A2H). */
  agent: AgentInterface;
  /** Thin emitter for x402 payment capture (L3b). */
  x402: X402Interface;
  use(plugin: AetherPlugin): void;
}

/**
 * Thin commerce emitter — the SDK does no workflow logic; backend owns
 * approval, settlement, entitlement orchestration. SDK only records events.
 */
export interface CommerceInterface {
  paymentInitiated(props: PaymentInitiatedEvent['properties']): void;
  paymentCompleted(props: PaymentCompletedEvent['properties']): void;
  paymentFailed(props: PaymentFailedEvent['properties']): void;
  approvalRequested(props: ApprovalRequestedEvent['properties']): void;
  approvalResolved(props: ApprovalResolvedEvent['properties']): void;
  entitlementGranted(props: EntitlementGrantedEvent['properties']): void;
  entitlementRevoked(props: EntitlementRevokedEvent['properties']): void;
  accessGranted(props: AccessGrantedEvent['properties']): void;
  accessDenied(props: AccessDeniedEvent['properties']): void;
}

export interface AgentInterface {
  // Lifecycle emitters — granular events
  registered(props: AgentRegisteredEvent['properties']): void;
  updated(props: AgentUpdatedEvent['properties']): void;
  authorized(props: AgentAuthorizedEvent['properties']): void;
  deauthorized(props: AgentDeauthorizedEvent['properties']): void;
  capabilityGranted(props: AgentCapabilityGrantedEvent['properties']): void;
  capabilityRevoked(props: AgentCapabilityRevokedEvent['properties']): void;
  taskCreated(props: AgentTaskCreatedEvent['properties']): void;
  taskDecomposed(props: AgentTaskDecomposedEvent['properties']): void;
  taskStarted(props: AgentTaskStartedEvent['properties']): void;
  taskCompleted(props: AgentTaskCompletedEvent['properties']): void;
  taskFailed(props: AgentTaskFailedEvent['properties']): void;
  toolCalled(props: AgentToolCalledEvent['properties']): void;
  resourceRequested(props: AgentResourceRequestedEvent['properties']): void;
  delegatedTask(props: AgentDelegatedTaskEvent['properties']): void;
  subagentSpawned(props: AgentSubagentSpawnedEvent['properties']): void;
  policyEvaluated(props: AgentPolicyEvaluatedEvent['properties']): void;
  handoff(props: AgentHandoffEvent['properties']): void;
  escalatedToHuman(props: AgentEscalatedToHumanEvent['properties']): void;
  outcomeRecorded(props: AgentOutcomeRecordedEvent['properties']): void;
  // Legacy emitters — kept for backward compatibility
  task(props: AgentTaskEvent['properties']): void;
  decision(props: AgentDecisionEvent['properties']): void;
  interaction(props: A2HInteractionEvent['properties']): void;
}

export interface X402Interface {
  // Lifecycle emitters — granular events
  resourceRequested(props: X402ResourceRequestedEvent['properties']): void;
  paymentRequired(props: X402PaymentRequiredEvent['properties']): void;
  quoteReceived(props: X402QuoteReceivedEvent['properties']): void;
  authorizationRequested(props: X402AuthorizationRequestedEvent['properties']): void;
  authorizationResolved(props: X402AuthorizationResolvedEvent['properties']): void;
  paymentIntentCreated(props: X402PaymentIntentCreatedEvent['properties']): void;
  paymentSubmitted(props: X402PaymentSubmittedEvent['properties']): void;
  paymentSettled(props: X402PaymentSettledEvent['properties']): void;
  paymentFailed(props: X402PaymentFailedEvent['properties']): void;
  paymentTimeout(props: X402PaymentTimeoutEvent['properties']): void;
  receiptVerified(props: X402ReceiptVerifiedEvent['properties']): void;
  accessGranted(props: X402AccessGrantedEvent['properties']): void;
  accessDenied(props: X402AccessDeniedEvent['properties']): void;
  refundOrReversal(props: X402RefundOrReversalEvent['properties']): void;
  // Legacy emitter — kept for backward compatibility
  payment(props: X402PaymentEvent['properties']): void;
}

export interface WalletInterface {
  /** Connect an EVM wallet (backwards compatible) */
  connect(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a Solana wallet */
  connectSVM(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a Bitcoin wallet */
  connectBTC(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a SUI wallet */
  connectSUI(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a NEAR wallet */
  connectNEAR(accountId: string, options?: Partial<WalletInfo>): void;
  /** Connect a TRON wallet */
  connectTRON(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a Cosmos/SEI wallet */
  connectCosmos(address: string, options?: Partial<WalletInfo>): void;
  /** Connect an Aptos wallet */
  connectAptos(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a TON wallet */
  connectTON(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a Starknet wallet */
  connectStarknet(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a Cardano wallet */
  connectCardano(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a Polkadot/Substrate wallet */
  connectSubstrate(address: string, options?: Partial<WalletInfo>): void;
  /** Connect an Algorand wallet */
  connectAlgorand(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a Hedera wallet */
  connectHedera(address: string, options?: Partial<WalletInfo>): void;
  /** Connect a Stellar wallet */
  connectStellar(address: string, options?: Partial<WalletInfo>): void;
  /** Connect an ICP wallet */
  connectICP(address: string, options?: Partial<WalletInfo>): void;
  /** Disconnect a specific wallet or all wallets */
  disconnect(address?: string): void;
  /** Get primary wallet info (backwards compatible) */
  getInfo(): WalletInfo | null;
  /** Get all connected wallets */
  getWallets(): ConnectedWallet[];
  /** Get wallets filtered by VM */
  getWalletsByVM(vm: VMType): ConnectedWallet[];
  /** Track a transaction */
  transaction(txHash: string, options?: TransactionOptions): void;
  /** Register callback for wallet connection changes */
  onWalletChange(callback: WalletChangeCallback): () => void;
}

export interface ConsentInterface {
  getState(): ConsentState;
  grant(purposes: string[]): void;
  revoke(purposes: string[]): void;
  showBanner(config?: ConsentBannerConfig): void;
  hideBanner(): void;
  onUpdate(callback: ConsentCallback): () => void;
}
