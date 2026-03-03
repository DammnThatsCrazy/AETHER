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
  | 'heartbeat';

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
    action: 'connect' | 'disconnect' | 'switch_chain' | 'sign' | 'approve';
    address: string;
    chainId: number;
    walletType: string;
    ens?: string;
    [key: string]: unknown;
  };
}

export interface TransactionEvent extends BaseEvent {
  type: 'transaction';
  properties: {
    txHash: string;
    chainId: number;
    from: string;
    to: string;
    value?: string;
    gasUsed?: string;
    gasPrice?: string;
    status: 'pending' | 'confirmed' | 'failed';
    type?: 'transfer' | 'swap' | 'stake' | 'mint' | 'approve' | 'custom';
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
}

export interface Identity {
  anonymousId: string;
  userId?: string;
  walletAddress?: string;
  walletType?: string;
  chainId?: number;
  ens?: string;
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
  chainId: number;
  type: string;
  ens?: string;
  isConnected: boolean;
  connectedAt?: string;
}

export interface TransactionOptions {
  chainId?: number;
  type?: 'transfer' | 'swap' | 'stake' | 'mint' | 'approve' | 'custom';
  value?: string;
  from?: string;
  to?: string;
  metadata?: Record<string, unknown>;
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
  connect(address: string, options?: Partial<WalletInfo>): void;
  disconnect(): void;
  getInfo(): WalletInfo | null;
  transaction(txHash: string, options?: TransactionOptions): void;
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
