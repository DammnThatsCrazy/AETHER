import { env } from '@shiki/lib/env/config';

interface FeatureFlags {
  readonly enableGoufReplay: boolean;
  readonly enableLabExport: boolean;
  readonly enableSlackNotifications: boolean;
  readonly enableEmailNotifications: boolean;
  readonly enableBrowserNotifications: boolean;
  readonly enableAggressiveAutomation: boolean;
  readonly enableMobilePush: boolean;
  readonly enablePagerDuty: boolean;
  readonly enableWebhookSinks: boolean;
}

const DEFAULT_FLAGS: FeatureFlags = {
  enableGoufReplay: true,
  enableLabExport: true,
  enableSlackNotifications: true,
  enableEmailNotifications: true,
  enableBrowserNotifications: true,
  enableAggressiveAutomation: false,
  enableMobilePush: false,
  enablePagerDuty: false,
  enableWebhookSinks: false,
};

function loadFlags(): FeatureFlags {
  try {
    const raw = env.VITE_FEATURE_FLAGS;
    if (raw && raw !== '{}') {
      const parsed = JSON.parse(raw) as Partial<FeatureFlags>;
      return { ...DEFAULT_FLAGS, ...parsed };
    }
  } catch {
    console.warn('[SHIKI] Failed to parse feature flags, using defaults');
  }
  return DEFAULT_FLAGS;
}

export const featureFlags = loadFlags();

export function isFeatureEnabled(flag: keyof FeatureFlags): boolean {
  return featureFlags[flag];
}
