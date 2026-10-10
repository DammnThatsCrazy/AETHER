/**
 * Capability gate.
 *
 * ADVISORY ONLY — see the banner in `permissions.ts`. This component hides
 * controls the backend would refuse; it is not a security boundary.
 *
 * Props are intentionally backwards compatible with the previous role-based
 * gate (`requires` + `actionClass`), so existing pages keep compiling. The
 * `requires` names are now aliases for capability ids (see
 * `LEGACY_GATE_CAPABILITIES`) rather than role-table lookups.
 */

import type { ReactNode } from 'react';
import type { ActionClass, CapabilityId } from '@kyber/types';
import { usePermissions, type LegacyGate } from './permissions';

export interface PermissionGateProps {
  readonly children: ReactNode;
  /** Legacy alias gate (`canApprove`, `canCommand`, …). Prefer `capability`. */
  readonly requires?: LegacyGate | undefined;
  /** Explicit backend capability id, e.g. `kyber.tenant.mirror.read`. */
  readonly capability?: CapabilityId | undefined;
  /** Passes when the principal holds ANY of these capabilities. */
  readonly anyCapability?: readonly CapabilityId[] | undefined;
  /** Passes when the principal holds EVERY one of these capabilities. */
  readonly allCapabilities?: readonly CapabilityId[] | undefined;
  /** Compared against the backend `max_action_class`. */
  readonly actionClass?: ActionClass | undefined;
  /** Compared against the backend `max_disclosure`. */
  readonly disclosureLevel?: number | undefined;
  readonly fallback?: ReactNode;
}

export function PermissionGate({
  children,
  requires,
  capability,
  anyCapability,
  allCapabilities,
  actionClass,
  disclosureLevel,
  fallback,
}: PermissionGateProps) {
  const perms = usePermissions();

  const denied =
    (requires !== undefined && !perms[requires]) ||
    (capability !== undefined && !perms.has(capability)) ||
    (anyCapability !== undefined && !perms.hasAny(anyCapability)) ||
    (allCapabilities !== undefined && !perms.hasAll(allCapabilities)) ||
    (actionClass !== undefined && !perms.canPerformAction(actionClass)) ||
    (disclosureLevel !== undefined && !perms.canDisclose(disclosureLevel));

  if (denied) return fallback ? <>{fallback}</> : null;
  return <>{children}</>;
}
