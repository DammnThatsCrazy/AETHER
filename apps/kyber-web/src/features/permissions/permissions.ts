/**
 * Kyber permissions — capability-driven, backend-authoritative.
 *
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │ FRONTEND PERMISSION STATE IS ADVISORY.                                   │
 * │                                                                          │
 * │ Everything in this module exists to HIDE CONTROLS an operator cannot use │
 * │ so the UI does not offer dead-ends. It DECIDES NOTHING. The backend      │
 * │ re-checks every capability, action class and disclosure level on every   │
 * │ request and is the only authority. A tampered client can flip any        │
 * │ boolean here and still get a 403.                                        │
 * │                                                                          │
 * │ Never gate a security property on this module. Never re-derive a         │
 * │ capability the backend did not send.                                     │
 * └──────────────────────────────────────────────────────────────────────────┘
 *
 * Replaced (do not reintroduce):
 *   - `ROLE_PERMISSIONS` / `ROLE_MAX_ACTION_CLASS`: client-side role tables.
 *     Roles are now `role_template_ids` sent by the backend and the ceiling is
 *     `max_action_class`.
 *   - `canViewAll`: it was `true` for every role including `kyber_observer`,
 *     i.e. a privilege escalation dressed up as a flag. It is deleted. Every
 *     read gate must name a specific capability.
 */

import type { ActionClass, CapabilityId } from '@kyber/types';
import { useAuth } from '@kyber/features/auth';

export interface PermissionCheck {
  readonly allowed: boolean;
  readonly reason?: string;
  readonly requiresApproval: boolean;
  readonly approvalClass?: ActionClass;
}

/**
 * Legacy boolean gate names mapped onto real capability identifiers.
 *
 * These exist so the pages already using `<PermissionGate requires="...">`
 * keep working while they migrate to explicit `capability=` props. New code
 * should pass a capability id directly.
 */
export const LEGACY_GATE_CAPABILITIES = {
  canApprove: 'kyber.approvals.decide',
  canIntervene: 'kyber.controller.intervene',
  canCommand: 'kyber.command.dispatch',
  canDiagnose: 'kyber.diagnostics.run',
  canRevert: 'kyber.action.revert',
  canWriteNotes: 'kyber.notes.write',
  canViewDiagnostics: 'kyber.diagnostics.read',
  canExport: 'kyber.export.create',
} as const;

export type LegacyGate = keyof typeof LEGACY_GATE_CAPABILITIES;

export const LEGACY_GATE_NAMES = Object.keys(LEGACY_GATE_CAPABILITIES) as readonly LegacyGate[];

/** Pure predicate over a backend-supplied capability list. */
export function hasCapability(
  capabilities: readonly CapabilityId[],
  capability: CapabilityId,
): boolean {
  return capabilities.includes(capability);
}

export function hasAnyCapability(
  capabilities: readonly CapabilityId[],
  wanted: readonly CapabilityId[],
): boolean {
  return wanted.some((capability) => capabilities.includes(capability));
}

export function hasAllCapabilities(
  capabilities: readonly CapabilityId[],
  wanted: readonly CapabilityId[],
): boolean {
  return wanted.every((capability) => capabilities.includes(capability));
}

/**
 * Compare a requested action class against the backend's ceiling.
 *
 * `maxActionClass` comes straight from `KyberPrincipalView.max_action_class`.
 * There is no posture heuristic and no environment special-case here any more:
 * the backend already folded policy, posture and environment into the number
 * it sent us.
 */
export function checkActionClass(maxActionClass: number, actionClass: ActionClass): PermissionCheck {
  if (actionClass > maxActionClass) {
    return {
      allowed: false,
      reason: `Action class ${actionClass} exceeds the backend ceiling of ${maxActionClass}`,
      requiresApproval: false,
    };
  }
  return { allowed: true, requiresApproval: false };
}

/** Disclosure ceiling check against `KyberPrincipalView.max_disclosure`. */
export function checkDisclosureLevel(maxDisclosure: number, level: number): PermissionCheck {
  if (level > maxDisclosure) {
    return {
      allowed: false,
      reason: `Disclosure level ${level} exceeds the backend ceiling of ${maxDisclosure}`,
      requiresApproval: false,
    };
  }
  return { allowed: true, requiresApproval: false };
}

// ── Hooks ────────────────────────────────────────────────────────────────────

export interface CapabilitySnapshot {
  readonly capabilities: readonly CapabilityId[];
  readonly roleTemplateIds: readonly string[];
  readonly maxActionClass: number;
  readonly maxDisclosure: number;
  readonly isLoading: boolean;
  readonly has: (capability: CapabilityId) => boolean;
  readonly hasAny: (capabilities: readonly CapabilityId[]) => boolean;
  readonly hasAll: (capabilities: readonly CapabilityId[]) => boolean;
  readonly canPerformAction: (actionClass: ActionClass) => boolean;
  readonly canDisclose: (level: number) => boolean;
  readonly checkAction: (actionClass: ActionClass) => PermissionCheck;
  readonly checkDisclosure: (level: number) => PermissionCheck;
}

/**
 * The backend capability grant for the current principal.
 *
 * An unauthenticated or still-loading principal has NO capabilities. Deny by
 * default: it is better to briefly hide a control than to flash one that the
 * server will refuse.
 */
export function useCapabilities(): CapabilitySnapshot {
  const { principal, isLoading } = useAuth();
  const capabilities = principal?.capabilities ?? [];
  const maxActionClass = principal?.max_action_class ?? 0;
  const maxDisclosure = principal?.max_disclosure ?? 0;

  return {
    capabilities,
    roleTemplateIds: principal?.role_template_ids ?? [],
    maxActionClass,
    maxDisclosure,
    isLoading,
    has: (capability) => hasCapability(capabilities, capability),
    hasAny: (wanted) => hasAnyCapability(capabilities, wanted),
    hasAll: (wanted) => hasAllCapabilities(capabilities, wanted),
    canPerformAction: (actionClass) => checkActionClass(maxActionClass, actionClass).allowed,
    canDisclose: (level) => checkDisclosureLevel(maxDisclosure, level).allowed,
    checkAction: (actionClass) => checkActionClass(maxActionClass, actionClass),
    checkDisclosure: (level) => checkDisclosureLevel(maxDisclosure, level),
  };
}

export type PermissionsSnapshot = CapabilitySnapshot & {
  /**
   * Primary backend role template id, for DISPLAY only. This is not derived in
   * the browser — it is `role_template_ids[0]` exactly as the server sent it.
   * Prefer a capability check over comparing this string.
   */
  readonly role: string;
} & { readonly [K in LegacyGate]: boolean };

/**
 * Back-compatible view used by existing pages. The legacy boolean names are
 * now thin aliases over capability checks — there is no role table behind
 * them, and `canViewAll` no longer exists.
 */
export function usePermissions(): PermissionsSnapshot {
  const snapshot = useCapabilities();
  const legacy = {} as { [K in LegacyGate]: boolean };
  for (const gate of LEGACY_GATE_NAMES) {
    legacy[gate] = snapshot.has(LEGACY_GATE_CAPABILITIES[gate]);
  }
  return {
    ...snapshot,
    ...legacy,
    role: snapshot.roleTemplateIds[0] ?? '',
  };
}
