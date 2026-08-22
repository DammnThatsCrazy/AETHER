// =============================================================================
// Aether SDK — REMOTE MANIFEST (React Native, JS-side apply)
//
// The backend SDK manifest (GET /v1/config/sdk/manifest → SDKManifest) was
// fetched in two places and discarded in both, while the SDK advertised
// `remoteManifest: true`. This module is the SINGLE owner: it fetches the
// manifest once, stores it, and APPLIES it to the JS surface —
//   - flags/features → RNFeatureFlags overrides (isEnabled/getValue reflect it)
//   - rollout_percentage → a JS-side sampling rate for JS-emitted events
//   - endpoints → per-name endpoint overrides
// Native signature verification (manifestSignatureVerification) remains the
// native layer's responsibility; this JS apply trusts the authenticated HTTPS
// response, consistent with the SDK's other config/heartbeat calls.
// =============================================================================

import { RNFeatureFlags } from './FeatureFlags';

export interface SDKManifest {
  features?: Record<string, unknown>;
  flags?: Record<string, unknown>;
  endpoints?: Record<string, string>;
  rollout_percentage?: number;
  schema_version?: string;
  min_sdk_version?: string;
  signature?: string;
  [key: string]: unknown;
}

let current: SDKManifest | null = null;

/** Store the fetched manifest and apply its flags/features to RNFeatureFlags. */
export function applyManifest(manifest: SDKManifest | null | undefined): void {
  if (!manifest || typeof manifest !== 'object') return;
  current = manifest;
  const entries: Record<string, unknown> = {
    ...(manifest.features && typeof manifest.features === 'object' ? manifest.features : {}),
    ...(manifest.flags && typeof manifest.flags === 'object' ? manifest.flags : {}),
  };
  for (const [key, value] of Object.entries(entries)) {
    try {
      // No-ops if the native feature-flag module is not linked.
      RNFeatureFlags.setOverride(key, value as boolean | unknown);
    } catch {
      // Applying a single flag must never break init.
    }
  }
}

/** The last-applied manifest, or null if none has been fetched yet. */
export function getManifest(): SDKManifest | null {
  return current;
}

/** Endpoint override for a named endpoint, if the manifest provides one. */
export function getEndpointOverride(name: string): string | undefined {
  const endpoints = current?.endpoints;
  return endpoints && typeof endpoints === 'object' ? endpoints[name] : undefined;
}

/** Sampling rate in [0,1] derived from rollout_percentage; 1 when unset. */
export function getSamplingRate(): number {
  const pct = current?.rollout_percentage;
  if (typeof pct === 'number' && pct >= 0 && pct <= 100) return pct / 100;
  return 1;
}

/**
 * Fetch the manifest once and apply it. Fire-and-forget and non-fatal: a
 * failure leaves the SDK on its built-in defaults.
 */
export async function fetchAndApplyManifest(endpoint: string, apiKey: string): Promise<void> {
  try {
    const res = await fetch(`${endpoint}/v1/config/sdk/manifest`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    if (res && res.ok && typeof res.json === 'function') {
      const body = (await res.json()) as { data?: SDKManifest } & SDKManifest;
      // The backend wraps the manifest in an APIResponse envelope (`data`).
      applyManifest(body && typeof body === 'object' && 'data' in body ? body.data : body);
    }
  } catch {
    // Non-fatal — remote config is best-effort.
  }
}

/** Test helper — reset the stored manifest between cases. */
export function _resetManifest(): void {
  current = null;
}
