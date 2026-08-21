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
