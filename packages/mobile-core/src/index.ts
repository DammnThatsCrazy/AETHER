/**
 * @aether/mobile-core — the platform-agnostic mobile SDK core.
 *
 * Re-exports the `@aether/shared` contract twins the mobile apps consume, plus the
 * typed API client, transport abstraction, config, and runtime guards. No React
 * Native / Expo dependency lives here; the host app injects transport + auth.
 */

// Contract twins (snake_case wire types) shared with the backend.
export type {
  ClientSyncResponse,
  ContinuationContext,
  ContinuationSummary,
  InstallationAppKind,
  InstallationPlatform,
  InstallationRegistration,
  InstallationTrustState,
  MobileInstallation,
  PushProvider,
  PushSubscription,
  SyncChangeType,
  SyncEvent,
} from '@aether/shared';

export {
  installationAppKinds,
  installationPlatforms,
  installationTrustStates,
  pushProviders,
  syncChangeTypes,
} from '@aether/shared';

export type { MobileAppKind, MobileConfig } from './config';
export { normalizeBaseUrl } from './config';

export type {
  AuthProvider,
  FetchLike,
  FetchRequestInit,
  FetchResponseLike,
  HttpClientDeps,
} from './http';
export { HttpClient, MobileApiError } from './http';

export type {
  DeepLinkContinuation,
  DeepLinkResolution,
  InstallationRegisterInput,
  OperatorRecentContinuations,
  RegistrationResult,
  SubscriptionInput,
} from './client';
export { AetherMobileClient } from './client';

// Kyber mobile contracts (D6 snake_case wire twins) + pure-TS ES256 signer.
export type {
  CommandReceipt,
  CommandReceiptDetail,
  CommandReceiptList,
  KyberSession,
  KyberSessionView,
  MobileActionItem,
  MobileActionsDigest,
  MobileProofKey,
  MobileProofKeyListEntry,
  ProofKeyRegisterInput,
  StepUpGrant,
  StepUpOptions,
  StepUpVerifyInput,
} from './kyber';
export type { RandomBytesSource } from './p256';
export { derivePublicKey, generateP256KeyPair, P256Signer, signChallenge } from './p256';

export {
  assertMobileInstallation,
  isMobileInstallation,
  isPushProvider,
  isSyncEvent,
} from './validate';

export type { CryptoProvider, PkcePair, SecureStore } from './auth';
export { createPkcePair, SecureStoreAuthProvider } from './auth';

// Read-only offline cache (platform-agnostic; storage injected by the host app).
export type {
  CacheEntry,
  CacheState,
  CacheStorage,
  CachedRead,
  OfflineCache,
  OfflineCacheOptions,
  ReadOfflineOptions,
  WriteOfflineOptions,
} from './offline';
export { createOfflineCache } from './offline';
