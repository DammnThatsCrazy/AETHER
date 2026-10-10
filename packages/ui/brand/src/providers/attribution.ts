import { resolveProvider } from './registry';
import type { ProviderVisualIdentity } from './types';

export interface ProviderAttribution {
  readonly required: boolean;
  readonly label: string;
  readonly guidance: string;
}

/**
 * Attribute a third-party brand in nearby text when its mark materially aids
 * identification. A provider mark never communicates Aether status, severity,
 * trust, or remediation state.
 */
export function providerAttribution(provider: ProviderVisualIdentity | string): ProviderAttribution {
  const identity = typeof provider === 'string' ? resolveProvider(provider).identity : provider;
  return {
    required: identity.attributionRequired,
    label: identity.label,
    guidance: identity.trademarkGuidance,
  };
}

export const providerPlacementRules = [
  'Use a provider identity to answer who or what an external platform is, not to signal health, severity, or an action.',
  'Pair provider marks with a text label in dense and accessible product interfaces.',
  'Prefer a neutral initials fallback until a legally reviewed local provider mark is added to the registry.',
  'Do not load third-party marks remotely or create feature-local copies of a provider asset.',
] as const;
