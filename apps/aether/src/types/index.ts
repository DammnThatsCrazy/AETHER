// Customer domain types — add as features are built out.
export type {
  // Session, device, platform
  PlatformType, GeoContext, SessionSummary, DeviceSummary, PlatformSummary,
  // Temporal & frequency
  HourBucket, DayBucket, TemporalPattern, FrequencyMetrics, ChurnRisk,
  // Journeys & funnel
  JourneyStep, UserJourney, FunnelStep, CampaignFunnel,
  // Behavioural "Why"
  SignalFamily, SignalType, SignalSeverity, BehavioralSignal, WhyExplanation,
  // Attribution "Where"
  AttributionModel, AttributionCredit, AttributionResolution, Touchpoint,
  // Web3 wallet
  WalletType, TokenBalance, OnChainTransaction, ProtocolInteraction, Web3LoyaltySignals, Web3WalletProfile,
  // Loyalty
  LoyaltyTier, LoyaltyProfile,
} from '@aether/shared';

export type {
  // Actors & graph
  ActorClass, GraphNodeKind, InteractionClass, RelationType,
  RelationshipEdge, DelegationRecord, DelegationChain,
  IdentifierSet, FlowSummary,
  EntityProfile, ClusterMember, EntityCluster, CollectiveTissue,
  GraphEntityNode, EntityGraph, RelationshipSummary,
} from '@aether/shared';

export type AetherEnvironment = 'local-mocked' | 'local-live' | 'staging' | 'production';

export interface AetherUser {
  readonly id: string;
  readonly email: string;
  readonly displayName: string;
  readonly avatarUrl?: string | undefined;
}

export interface AuthTokens {
  readonly accessToken: string;
  readonly idToken: string;
  readonly refreshToken?: string | undefined;
  readonly expiresAt: number;
}

export interface AuthState {
  readonly isAuthenticated: boolean;
  readonly user: AetherUser | null;
  readonly isLoading: boolean;
  readonly error: string | null;
}
