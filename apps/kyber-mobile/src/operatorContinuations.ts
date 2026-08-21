/**
 * Kyber Mobile — operator continuation-plane helpers (M5d).
 *
 * The operator continuation router (M5b) mirrors the tenant `/v1/continuations`
 * shapes under `/v1/kyber/continuations` and is flag-gated by the backend
 * (`settings.continuation.enabled`); when the gate is off the router returns 404.
 *
 * 404-safe reads:
 *   - `fetchOperatorContinuations()` maps the flag-gated 404 to
 *     `{ available: false, continuations: [] }` so the surface renders
 *     "unavailable" rather than an error state (and never crashes).
 *   - `resumeOperatorContinuation()` reads one continuation (GET
 *     /v1/kyber/continuations/{id}) then resolves the deep link back to the
 *     desktop app; a missing device installation or an unavailable resolve
 *     endpoint degrades to `unavailableReason` instead of throwing.
 *
 * READ-ONLY by construction: the only POST here is `resolveDeepLink`, which is a
 * resolution read, not a mutation.
 */
import {
  MobileApiError,
  type ContinuationContext,
  type DeepLinkResolution,
  type MobileInstallation,
} from '@aether/mobile-core';

import { client } from './client';

/** The operator continuation feed, with flag-gating made explicit. */
export interface OperatorContinuationsFeed {
  /** False when the flag-gated operator router is off (404) — surface unavailable. */
  available: boolean;
  continuations: ContinuationContext[];
}

/** Result of opening one operator continuation and resolving its deep link. */
export interface OperatorResumeResult {
  continuation: ContinuationContext;
  /** The resolved deep link, when the device has an installation to resolve against. */
  resolution: DeepLinkResolution | null;
  /** Non-null when the deep-link resolve could not run (surface unavailable). */
  unavailableReason: string | null;
}

/** 404-safe read of GET /v1/kyber/continuations/recent. */
export async function fetchOperatorContinuations(): Promise<OperatorContinuationsFeed> {
  try {
    const continuations = await client.operatorRecentContinuations();
    return { available: true, continuations };
  } catch (err) {
    if (err instanceof MobileApiError && err.status === 404) {
      return { available: false, continuations: [] };
    }
    throw err;
  }
}

/** The device's own installation id, discovered read-only (kyber app kind). */
export async function currentOperatorInstallationId(): Promise<string | null> {
  try {
    const installations: MobileInstallation[] = await client.listInstallations();
    const own = installations.find(installation => installation.app_kind === 'kyber') ?? installations[0];
    return own?.id ?? null;
  } catch {
    return null;
  }
}

/**
 * Open one operator continuation and resolve it to a deep link. 404-safe by
 * construction: a missing continuation rejects (surfaced by the caller); a missing
 * installation or an unavailable resolve endpoint degrades to `unavailableReason`
 * instead of crashing.
 */
export async function resumeOperatorContinuation(
  continuationId: string,
): Promise<OperatorResumeResult> {
  const continuation = await client.operatorGetContinuation(continuationId);
  const installationId = await currentOperatorInstallationId();
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
