/**
 * Lightweight runtime guards for wire responses.
 *
 * The backend is authoritative, but a mobile client must fail loudly on a payload
 * that does not match the contract (a stale build talking to a newer server, or the
 * reverse). These guards validate the enum-bearing fields against the `@aether/shared`
 * const vocabularies — the same arrays the parity tests pin — so a runtime check can
 * never drift from the compile-time contract.
 */
import {
  installationTrustStates,
  pushProviders,
  syncChangeTypes,
  type MobileInstallation,
  type SyncEvent,
} from '@aether/shared';

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isOneOf<T extends readonly string[]>(vocab: T, value: unknown): value is T[number] {
  return typeof value === 'string' && (vocab as readonly string[]).includes(value);
}

export function isMobileInstallation(value: unknown): value is MobileInstallation {
  return (
    isObject(value) &&
    typeof value.id === 'string' &&
    typeof value.principal_id === 'string' &&
    typeof value.bundle_id === 'string' &&
    isOneOf(installationTrustStates, value.trust_state)
  );
}

export function isPushProvider(value: unknown): boolean {
  return isOneOf(pushProviders, value);
}

export function isSyncEvent(value: unknown): value is SyncEvent {
  return (
    isObject(value) &&
    typeof value.id === 'string' &&
    typeof value.seq === 'number' &&
    isOneOf(syncChangeTypes, value.change_type)
  );
}

/** Assert-style guard: throws a descriptive error when the shape is wrong. */
export function assertMobileInstallation(value: unknown): MobileInstallation {
  if (!isMobileInstallation(value)) {
    throw new Error('response is not a MobileInstallation (contract drift?)');
  }
  return value;
}
