import type { IconDescriptor } from './types';

export type Provenance = 'first_party' | 'provider' | 'customer_supplied' | 'inferred' | 'derived' | 'manual' | 'unknown';

/** Provenance answers origin. It must remain independent of confidence and freshness. */
export const provenanceIcons = {
  first_party: { icon: 'shield-check', label: 'First-party source', decorativeByDefault: true, description: 'Produced by an Olympus or Aether first-party system.' },
  provider: { icon: 'plug', label: 'Provider source', decorativeByDefault: true, description: 'Received from an external provider.' },
  customer_supplied: { icon: 'user-round-check', label: 'Customer-supplied source', decorativeByDefault: true, description: 'Provided by the customer or tenant.' },
  inferred: { icon: 'brain', label: 'Inferred', decorativeByDefault: true, description: 'Inferred from available evidence.' },
  derived: { icon: 'git-branch', label: 'Derived', decorativeByDefault: true, description: 'Derived by a deterministic or analytical process.' },
  manual: { icon: 'file-pen-line', label: 'Manual source', decorativeByDefault: true, description: 'Entered or asserted manually.' },
  unknown: { icon: 'circle-help', label: 'Unknown provenance', decorativeByDefault: true, description: 'Source provenance is not available.' },
} as const satisfies Readonly<Record<Provenance, IconDescriptor>>;
