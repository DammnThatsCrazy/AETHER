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

/** SDK configuration passed to Aether.init() */
export interface AetherConfig {
  /** API key from the Aether dashboard (required) */
  apiKey: string;
  /** Deployment environment */
  environment?: 'production' | 'staging' | 'development';
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
  // Wallet / multi-VM capture
  walletTracking?: boolean;   // evm
  svmTracking?: boolean;
  bitcoinTracking?: boolean;
  moveTracking?: boolean;
  nearTracking?: boolean;
  tronTracking?: boolean;
  cosmosTracking?: boolean;
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
export type VMType = 'evm' | 'svm' | 'bitcoin' | 'movevm' | 'near' | 'tvm' | 'cosmos';

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
  // Agent (optional)
  | 'agent_task'
  | 'agent_decision'
  | 'a2h_interaction'
  // x402 (optional)
  | 'x402_payment';

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

export type AetherEvent =
  | TrackEvent
  | PageEvent
  | IdentifyEvent
  | ConversionEvent
  | WalletEvent
  | TransactionEvent
  | ErrorEvent
  | AgentTaskEvent
  | AgentDecisionEvent
  | A2HInteractionEvent
  | PaymentInitiatedEvent
  | PaymentCompletedEvent
  | PaymentFailedEvent
  | ApprovalRequestedEvent
  | ApprovalResolvedEvent
  | EntitlementGrantedEvent
  | EntitlementRevokedEvent
  | AccessGrantedEvent
  | AccessDeniedEvent
  | X402PaymentEvent
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
  web3: boolean;
  agent: boolean;     // Intelligence Graph — agent behavioral tracking
  commerce: boolean;  // Intelligence Graph — commerce/payment processing
  updatedAt: string;
  policyVersion: string;
}

export interface ConsentConfig {
  purposes: ('analytics' | 'marketing' | 'web3' | 'agent' | 'commerce')[];
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
  pageView(page?: string, properties?: Record<string, unknown>): void;
  conversion(event: string, value?: number, properties?: Record<string, unknown>): void;
  hydrateIdentity(data: IdentityData): void;
  getIdentity(): Identity | null;
  reset(): void;
  flush(): Promise<void>;
  destroy(): void;
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
  task(props: AgentTaskEvent['properties']): void;
  decision(props: AgentDecisionEvent['properties']): void;
  interaction(props: A2HInteractionEvent['properties']): void;
}

export interface X402Interface {
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
