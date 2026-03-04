// =============================================================================
// AETHER SDK — CORE TYPE DEFINITIONS
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

export interface ModuleConfig {
  intentPrediction?: boolean;
  walletTracking?: boolean;
  formTracking?: boolean;
  errorTracking?: boolean;
  performanceTracking?: boolean;
  scrollDepth?: boolean;
  onChainAttribution?: boolean;
  tokenGating?: boolean;
  gasTracking?: boolean;
  whaleTracking?: boolean;
  experiments?: boolean;
  cohortAnalysis?: boolean;
  predictiveAnalytics?: boolean;
  autoDiscovery?: boolean;
  rageClickDetection?: boolean;
  deadClickDetection?: boolean;
  // Multi-VM Web3 modules
  svmTracking?: boolean;
  bitcoinTracking?: boolean;
  moveTracking?: boolean;
  nearTracking?: boolean;
  tronTracking?: boolean;
  cosmosTracking?: boolean;
  // DeFi tracking modules
  tokenTracking?: boolean;
  nftDetection?: boolean;
  defiTracking?: boolean;
  portfolioTracking?: boolean;
  whaleAlerts?: boolean;
  walletClassification?: boolean;
  bridgeTracking?: boolean;
  cexTracking?: boolean;
  perpetualsTracking?: boolean;
  optionsTracking?: boolean;
  yieldTracking?: boolean;
  governanceTracking?: boolean;
  insuranceTracking?: boolean;
  launchpadTracking?: boolean;
  paymentsTracking?: boolean;
  nftMarketplaceTracking?: boolean;
  restakingTracking?: boolean;
}

export interface PrivacyConfig {
  /** Send ML vectors instead of raw behavioral data */
  vectorizeData?: boolean;
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
  /** Offload processing to Web Worker */
  useWebWorker?: boolean;
  /** Pre-fetch ML predictions speculatively */
  speculativeExecution?: boolean;
  /** Run ML inference locally on-device */
  edgeComputation?: boolean;
  /** Use WASM for data vectorization acceleration */
  wasmVectorization?: boolean;
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

export type EventType =
  | 'track'
  | 'page'
  | 'screen'
  | 'identify'
  | 'conversion'
  | 'wallet'
  | 'transaction'
  | 'error'
  | 'performance'
  | 'experiment'
  | 'consent'
  | 'heartbeat'
  // Multi-VM Web3 events
  | 'token_balance'
  | 'nft_detection'
  | 'whale_alert'
  | 'portfolio_update'
  | 'defi_interaction'
  | 'bridge_transfer'
  | 'cex_transfer'
  | 'perpetual_trade'
  | 'options_trade'
  | 'governance_vote'
  | 'yield_harvest'
  | 'nft_trade'
  | 'staking_action'
  | 'insurance_action'
  | 'launchpad_action'
  | 'payment_stream';

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

export interface PerformanceEvent extends BaseEvent {
  type: 'performance';
  properties: {
    lcp?: number;
    fid?: number;
    cls?: number;
    ttfb?: number;
    fcp?: number;
    domReady?: number;
    loadComplete?: number;
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
  | PerformanceEvent;

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
// ML / PREDICTION TYPES
// =============================================================================

export interface IntentVector {
  predictedAction: 'purchase' | 'signup' | 'browse' | 'exit' | 'engage' | 'idle';
  confidenceScore: number;
  highExitRisk: boolean;
  highConversionProbability: boolean;
  journeyStage: 'awareness' | 'consideration' | 'decision' | 'retention';
  features: Record<string, number>;
  timestamp: string;
}

export interface BotScore {
  likelyBot: boolean;
  confidenceScore: number;
  botType: 'human' | 'scraper' | 'automated_test' | 'click_farm' | 'legitimate_bot';
  signals: BehaviorSignature;
}

export interface BehaviorSignature {
  avgTimeBetweenActions: number;
  actionTimingVariance: number;
  clickToScrollRatio: number;
  mouseMovementEntropy: number;
  navigationEntropy: number;
  interactionDiversityScore: number;
  hasNaturalPauses: boolean;
  hasErraticMovement: boolean;
  hasPerfectTiming: boolean;
}

export interface SessionScore {
  engagementScore: number;
  conversionProbability: number;
  recommendedIntervention: 'none' | 'soft_cta' | 'hard_cta' | 'exit_offer';
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
  updatedAt: string;
  policyVersion: string;
}

export interface ConsentConfig {
  purposes: ('analytics' | 'marketing' | 'web3')[];
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
// EXPERIMENT TYPES
// =============================================================================

export interface ExperimentConfig {
  id: string;
  variants: Record<string, () => void>;
  weights?: Record<string, number>;
}

export interface ExperimentAssignment {
  experimentId: string;
  variantId: string;
  assignedAt: string;
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

export type IntentCallback = (intent: IntentVector) => void;
export type BotCallback = (score: BotScore) => void;
export type SessionCallback = (score: SessionScore) => void;
export type EventCallback = (event: AetherEvent) => void;
export type ErrorCallback = (error: Error) => void;
export type ConsentCallback = (consent: ConsentState) => void;
export type WalletChangeCallback = (wallets: ConnectedWallet[]) => void;
export type PortfolioCallback = (portfolio: PortfolioSnapshot) => void;
export type WhaleCallback = (alert: WhaleAlert) => void;
export type DeFiCallback = (position: DeFiPosition) => void;

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
  experiments: ExperimentInterface;
  consent: ConsentInterface;
  onIntentPrediction(callback: IntentCallback): () => void;
  onBotDetection(callback: BotCallback): () => void;
  onSessionScore(callback: SessionCallback): () => void;
  use(plugin: AetherPlugin): void;
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
  /** Get cross-chain portfolio */
  getPortfolio(): PortfolioSnapshot | null;
  /** Register callback for wallet connection changes */
  onWalletChange(callback: WalletChangeCallback): () => void;
  /** Classify a wallet address */
  classifyWallet(address: string, vm: VMType): WalletClassification;
}

export interface ExperimentInterface {
  run(config: ExperimentConfig): string;
  getAssignment(experimentId: string): ExperimentAssignment | null;
}

export interface ConsentInterface {
  getState(): ConsentState;
  grant(purposes: string[]): void;
  revoke(purposes: string[]): void;
  showBanner(config?: ConsentBannerConfig): void;
  hideBanner(): void;
  onUpdate(callback: ConsentCallback): () => void;
}
