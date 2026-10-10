import type { BrandId, LockupVariant } from '../identity';

export interface LockupResponsiveRule {
  readonly brand: BrandId;
  readonly variant: LockupVariant;
  readonly minAvailableWidth: number;
  readonly usage: string;
}

/** Minimum available inline width; select the largest rule that fits. */
export const lockupResponsiveRules: readonly LockupResponsiveRule[] = [
  { brand: 'olympus', variant: 'full', minAvailableWidth: 144, usage: 'Corporate and documentation headers.' },
  { brand: 'olympus', variant: 'mark', minAvailableWidth: 20, usage: 'Compact attribution only.' },
  { brand: 'aether', variant: 'full', minAvailableWidth: 112, usage: 'Standard product header.' },
  { brand: 'aether', variant: 'compact', minAvailableWidth: 72, usage: 'Compact navigation with wordmark.' },
  { brand: 'aether', variant: 'mark', minAvailableWidth: 20, usage: 'Collapsed or mobile navigation.' },
  { brand: 'kyber', variant: 'full', minAvailableWidth: 132, usage: 'Operator shell with Aether Operations descriptor.' },
  { brand: 'kyber', variant: 'compact', minAvailableWidth: 84, usage: 'Operator shell without descriptor.' },
  { brand: 'kyber', variant: 'mark', minAvailableWidth: 20, usage: 'Collapsed operator navigation; accessible label remains Kyber.' },
];

export function lockupVariantFor(brand: BrandId, availableWidth: number): LockupVariant {
  const candidates = lockupResponsiveRules
    .filter(rule => rule.brand === brand && availableWidth >= rule.minAvailableWidth)
    .sort((left, right) => right.minAvailableWidth - left.minAvailableWidth);
  return candidates[0]?.variant ?? 'mark';
}
