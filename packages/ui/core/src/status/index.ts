// Canonical capability credential-lifecycle state matrix — one shared vocabulary
// so both apps (tenant Aether + operator Kyber) render capability status
// consistently and never present not-live/mock data as live.

export {
  capabilityStates,
  capabilityStateStyle,
  capabilityStatePrecedence,
  worstCapabilityState,
  isCapabilityState,
  toneVariant,
  fromImplementationStatus,
  fromDimensionState,
  resolveCapabilityState,
} from './capability-state';
export type {
  CapabilityState,
  CapabilityTone,
  CapabilityStateStyle,
} from './capability-state';

export { CapabilityStateBadge, CapabilityStatePanel } from './capability-state-badge';
export type { CapabilityStateBadgeProps, CapabilityStatePanelProps } from './capability-state-badge';
