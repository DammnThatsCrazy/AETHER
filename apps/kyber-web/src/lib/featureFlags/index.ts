import { env } from '@kyber/lib/env/config';

interface FeatureFlags {
  readonly enableNoesisReplay: boolean;
  readonly enableLabExport: boolean;
  readonly enableSlackNotifications: boolean;
  readonly enableEmailNotifications: boolean;
  readonly enableBrowserNotifications: boolean;
  readonly enableAggressiveAutomation: boolean;
  readonly enableMobilePush: boolean;
  readonly enablePagerDuty: boolean;
  readonly enableWebhookSinks: boolean;
  readonly enableExternalAgentTelemetry: boolean;
  readonly enablePaymentRails: boolean;
  readonly enableCardLinkedPaymentRails: boolean;
  readonly enableAiEfficiency: boolean;
  readonly enableTargetingIntelligence: boolean;
  readonly enableAgentCommandCenter: boolean;
  readonly enableKyberContinuations: boolean;
  readonly kyberStablecoinOps: boolean;
  readonly kyberDerivativesOps: boolean;
  readonly kyberInteropOps: boolean;
  /** Kyber provider-connections UI (read/monitor + operator-certify). Default OFF. */
  readonly enableProviderRuntime: boolean;
  /** Model-runtime control-plane operator admin surfaces (ADR-008 D8/D9). Default OFF. */
  readonly enableModelHarness: boolean;
  /** Ingestion control plane (Kyber Observation Inspector + ingestion funnel +
   * SDK-fleet mount). Mirrors AETHER_INGESTION_OBSERVABILITY_ENABLED (default
   * OFF); the /v1/kyber/ingest/observability + /v1/kyber/ingest/replay endpoints
   * are the real grant gate, so routing is not a grant. */
  readonly enableIngestionOps: boolean;
}

const DEFAULT_FLAGS: FeatureFlags = {
  enableNoesisReplay: true,
  enableLabExport: true,
  enableSlackNotifications: true,
  enableEmailNotifications: true,
  enableBrowserNotifications: true,
  enableAggressiveAutomation: false,
  enableMobilePush: false,
  enablePagerDuty: false,
  enableWebhookSinks: false,
  enableExternalAgentTelemetry: false,
  enablePaymentRails: false,
  enableCardLinkedPaymentRails: false,
  enableAiEfficiency: false,
  enableTargetingIntelligence: false,
  enableAgentCommandCenter: false,
  // Continuation routing lands in M5 — the hooks are inert stubs, default OFF
  // (D8) so no runtime behavior changes until the operator continuation router ships.
  enableKyberContinuations: false,
  // Economic & interoperability ops surfaces default OFF with their domains
  kyberStablecoinOps: false,
  kyberDerivativesOps: false,
  kyberInteropOps: false,
  // Provider Runtime UI is aggregate-only (read/monitor + certify); default OFF
  // (fail-closed) until the backend runtime flag is enabled in an environment.
  enableProviderRuntime: false,
  // Model-runtime admin surfaces default OFF (D8/D9, fail-closed) until an
  // environment flips the flag on together with the model-runtime control-plane
  // backend; routing is never a grant — the /v1/model-runtime/* endpoints gate.
  enableModelHarness: false,
  // Ingestion control plane mirrors the backend ingestion-observability flag
  // (default OFF); the page renders honest disabled/empty states from what the
  // backend reports, and /v1/kyber/* endpoints gate every request.
  enableIngestionOps: false,
};

function loadFlags(): FeatureFlags {
  try {
    const raw = env.VITE_FEATURE_FLAGS;
    if (raw && raw !== '{}') {
      const parsed = JSON.parse(raw) as Partial<FeatureFlags>;
      return { ...DEFAULT_FLAGS, ...parsed };
    }
  } catch {
    console.warn('[KYBER] Failed to parse feature flags, using defaults');
  }
  return DEFAULT_FLAGS;
}

export const featureFlags = loadFlags();

export function isFeatureEnabled(flag: keyof FeatureFlags): boolean {
  return featureFlags[flag];
}
