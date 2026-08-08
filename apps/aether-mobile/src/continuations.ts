/**
 * Aether Mobile — continuation-plane helpers (M5d).
 *
 * Cross-device continuation plane: the SDK's `recentContinuations()` reads the
 * tenant `/v1/continuations/recent` feed; a "resume" re-fetches the continuation
 * (GET /v1/continuations/{id}) and then resolves the deep link back to the desktop
 * app (`resolveDeepLink`) so the phone can show where the work continues.
 *
 * READ-ONLY: the only POST here is `resolveDeepLink`, which is a resolution read,
 * not a mutation. The device's own installation id is discovered via the read-only
 * `listInstallations()`; when none has been registered the deep-link resolve is
 * reported unavailable rather than fabricating one.
 */
import { client } from './client';
import type {
  ContinuationContext,
  DeepLinkResolution,
  MobileInstallation,
} from '@aether/mobile-core';

export interface ContinueOnDesktopResult {
  continuation: ContinuationContext;
  /** The resolved deep link, when the device has an installation to resolve against. */
  resolution: DeepLinkResolution | null;
  /** Non-null when the deep-link resolve could not run (surface unavailable). */
  unavailableReason: string | null;
}

/** The device's own installation id, discovered read-only. */
export async function currentInstallationId(): Promise<string | null> {
  const own = await currentInstallation();
  return own?.id ?? null;
}

/**
 * The device's own principal id (the authenticated user), discovered read-only.
 * The gateway derives `principal_id` server-side from the session; the profile
 * projection is scoped by this value (`user_id` query param).
 */
export async function currentPrincipalId(): Promise<string | null> {
  const own = await currentInstallation();
  return own?.principal_id ?? null;
}

/** The device's own installation record, discovered read-only. */
async function currentInstallation(): Promise<MobileInstallation | null> {
  try {
    const installations: MobileInstallation[] = await client.listInstallations();
    return installations.find(installation => installation.app_kind === 'aether') ?? installations[0] ?? null;
  } catch {
    return null;
  }
}

/**
 * Open a continuation and resolve it to a deep link. 404-safe by construction: a
 * missing continuation rejects (surfaced by the caller); a missing installation or
 * an unavailable resolve endpoint degrades to `unavailableReason` instead of
 * crashing.
 */
export async function resumeContinuation(continuationId: string): Promise<ContinueOnDesktopResult> {
  const continuation = await client.getContinuation(continuationId);
  const installationId = await currentInstallationId();
  if (!installationId) {
    return {
      continuation,
      resolution: null,
      unavailableReason: 'No device installation registered — deep-link resume unavailable.',
    };
  }
  try {
    const resolution = await client.resolveDeepLink(installationId, continuationId);
    return { continuation, resolution, unavailableReason: null };
  } catch {
    return {
      continuation,
      resolution: null,
      unavailableReason: 'Deep-link resolve is unavailable right now.',
    };
  }
}
