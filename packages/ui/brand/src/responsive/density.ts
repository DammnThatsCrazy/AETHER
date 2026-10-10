export const densityRules = {
  comfortable: {
    rowMinHeight: 44,
    controlMinHitTarget: 44,
    providerMarkSize: 24,
    showProviderLabel: true,
  },
  compact: {
    rowMinHeight: 32,
    controlMinHitTarget: 32,
    providerMarkSize: 20,
    showProviderLabel: true,
  },
  narrow: {
    rowMinHeight: 44,
    controlMinHitTarget: 44,
    providerMarkSize: 20,
    showProviderLabel: true,
  },
} as const;

export type Density = keyof typeof densityRules;

/** Critical state and remediation text outrank a provider mark on narrow layouts. */
export const providerNarrowLayoutRules = [
  'Keep the provider label adjacent to its mark; do not rely on initials alone.',
  'Wrap or stack secondary metadata before hiding status, remediation, or an accessible provider label.',
  'Use the compact mark size before removing provider identity.',
] as const;
