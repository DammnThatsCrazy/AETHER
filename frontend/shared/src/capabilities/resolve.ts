/**
 * Resolve whether a navigation destination / route is available for the active
 * deployment profile, given the runtime capability contract. This is the single
 * source both the sidebar (hide/mark links) and the route guard consult, so nav
 * and direct-URL access can never disagree.
 */

import type { Capabilities, CapabilityRequirement, DestinationAvailability } from './types';

/** Plural route domain (``stablecoins``) matches its singular manifest entry. */
export function isDomainExcluded(caps: Capabilities, domain: string): boolean {
  const excluded = caps.release.excluded_domains;
  return (
    excluded.includes(domain) ||
    (domain.endsWith('s') && excluded.includes(domain.slice(0, -1)))
  );
}

/**
 * Resolve availability. With no requirement, or before capabilities have
 * loaded, a destination is treated as available (the server still hard-denies
 * excluded domains, so an optimistic render cannot leak data). An excluded
 * domain resolves to ``not_in_release``; an explicitly-off flag to ``disabled``.
 */
export function resolveDestinationAvailability(
  caps: Capabilities | null | undefined,
  requirement: CapabilityRequirement | undefined,
): Exclude<DestinationAvailability, 'loading'> {
  if (!requirement || !caps) return 'available';

  if (requirement.domain && isDomainExcluded(caps, requirement.domain)) {
    return 'not_in_release';
  }
  if (requirement.flag) {
    const flagValue = caps.feature_flags[requirement.flag];
    if (flagValue === false) return 'disabled';
  }
  return 'available';
}

/** Convenience: whether the destination should be shown in navigation. */
export function isDestinationVisible(
  caps: Capabilities | null | undefined,
  requirement: CapabilityRequirement | undefined,
): boolean {
  return resolveDestinationAvailability(caps, requirement) === 'available';
}
