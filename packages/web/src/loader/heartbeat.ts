// =============================================================================
// Aether SDK — INSTALL SIGNAL (client half of the first-heartbeat verifier)
//
// Reports load / init / init-failure back to the platform so a tenant can see
// whether their install actually worked, instead of inferring it from an
// absence of traffic.
//
// This deliberately does NOT go through the SDK's event queue. The signal that
// matters most is `sdk_init_failed` — the one case where the SDK is, by
// definition, not working. Routing it through the SDK would mean the failure
// report depends on the thing that just failed. So the signal is posted
// directly, with the same wire contract the queue uses.
//
// A signal that never arrives is itself information: the server-side
// `sdk_heartbeat_received` is derived from first accepted ingestion, so a
// loader blocked by CSP, a network policy, or an extension shows up as silent
// rather than falsely healthy.
// =============================================================================

import type { InstallMode } from './auto-init';

/**
 * Mirrors CONTRACT_SCHEMA_VERSION in packages/shared/schema-version.ts.
 *
 * The loader bundles standalone (it is the first thing a page downloads and
 * must carry no dependencies), so it repeats the literal rather than importing
 * it. scripts/validate_sdk_release_alignment.py holds this copy and the SDK's
 * copy in packages/web/src/index.ts to the shared value.
 */
const CONTRACT_SCHEMA_VERSION = '1.0.0';

/** Canonical event types emitted at each install milestone. */
export type InstallSignal = 'sdk_loaded' | 'sdk_initialized' | 'sdk_init_failed';

export interface InstallSignalInput {
  signal: InstallSignal;
  installMode: InstallMode;
  /** Version of the loader bundle that is running, from its own build. */
  loaderVersion: string;
  /** Resolved SDK bundle version, once known. */
  sdkVersion?: string | null;
  /** Publishable SDK key from the snippet — same credential the SDK uses. */
  sdkKey: string;
  siteId: string;
  endpoint: string;
  /** Human-readable cause, for the failure signal. */
  reason?: string;
  /** Non-fatal snippet problems worth surfacing to the site owner. */
  warnings?: string[];
  /** Injected for deterministic tests. */
  now?: () => Date;
  /** Injected for deterministic tests. */
  randomId?: () => string;
}

/**
 * Sends one already-serialized signal. Swappable so tests never touch the
 * network, and so a caller can route signals through their own transport.
 */
export type SignalTransport = (
  url: string,
  body: string,
  headers: Record<string, string>,
) => void;

/** The canonical envelope fields the batch endpoint requires. */
export interface InstallSignalEvent {
  id: string;
  type: InstallSignal;
  timestamp: string;
  sessionId: string;
  anonymousId: string;
  properties: Record<string, unknown>;
  context: {
    library: { name: string; version: string };
    surface: string;
    schemaVersion: string;
    sequence: { event: number };
  };
}

function defaultRandomId(): string {
  const cryptoObj = (globalThis as { crypto?: Crypto }).crypto;
  if (cryptoObj?.randomUUID) return cryptoObj.randomUUID();
  // Non-cryptographic fallback: this id only has to be unique within a tenant's
  // event stream, and it is never used as a credential.
  return `sdk_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Build the canonical event for a signal.
 *
 * `sessionId`/`anonymousId` are minted here rather than reused from the SDK:
 * for `sdk_init_failed` there is no SDK session to read, and a verifier that
 * only worked on the happy path would be useless for the case it exists for.
 */
export function buildSignalEvent(input: InstallSignalInput): InstallSignalEvent {
  const now = (input.now ?? (() => new Date()))();
  const randomId = input.randomId ?? defaultRandomId;
  const marker = randomId();

  const properties: Record<string, unknown> = {
    installMode: input.installMode,
    loaderVersion: input.loaderVersion,
    siteId: input.siteId,
  };
  if (input.sdkVersion) properties.sdkVersion = input.sdkVersion;
  if (input.reason) properties.reason = input.reason;
  if (input.warnings && input.warnings.length > 0) {
    properties.warnings = input.warnings;
  }

  return {
    id: marker,
    type: input.signal,
    timestamp: now.toISOString(),
    // One-shot install markers: they share a session id so a verifier can
    // correlate the whole handshake, and never collide with a real session.
    sessionId: `install_${marker}`,
    anonymousId: `install_${marker}`,
    properties,
    // The canonical envelope, stamped exactly as the SDK stamps it on its own
    // events (src/index.ts). This is not decoration: every sdk_* signal is a
    // `core`-family event, and `core` is release-critical, so with
    // envelope_required_fields_enforced on (the default in staging and
    // production) an event missing any of these three is rejected per-event
    // with `envelope_missing:<field>`. Without them the install verifier would
    // go silent in precisely the two environments it exists to serve.
    //
    // `sequence` is 0 because a signal is one-shot: it opens and closes its own
    // `install_<marker>` session in the same request.
    context: {
      library: { name: '@aether/sdk', version: input.loaderVersion },
      surface: 'web',
      schemaVersion: CONTRACT_SCHEMA_VERSION,
      sequence: { event: 0 },
    },
  };
}

/**
 * POST transport matching the SDK's own batch contract.
 *
 * Uses fetch with `keepalive` rather than `navigator.sendBeacon`: sendBeacon
 * cannot carry an Authorization header, which would force the publishable key
 * into the URL — visible in proxy logs, CDN logs and referrer headers.
 */
export function createBeaconTransport(
  fetchImpl: typeof fetch | undefined = (globalThis as { fetch?: typeof fetch }).fetch,
): SignalTransport {
  return (url, body, headers) => {
    if (typeof fetchImpl !== 'function') return;
    try {
      void fetchImpl(url, { method: 'POST', headers, body, keepalive: true }).catch(() => {
        // Best-effort by design: a failed signal must never surface as a page
        // error, and the server-side heartbeat covers the silent case.
      });
    } catch {
      // Synchronous throw (bad URL, blocked fetch) — same reasoning.
    }
  };
}

/**
 * Emit one install signal. Returns whether it was handed to the transport;
 * never throws, because a reporting failure must not break the page.
 */
export function reportInstallSignal(
  input: InstallSignalInput,
  transport: SignalTransport = createBeaconTransport(),
): boolean {
  if (!input.endpoint || !input.sdkKey) return false;
  try {
    const event = buildSignalEvent(input);
    transport(
      `${input.endpoint}/v1/batch`,
      JSON.stringify({
        batch: [event],
        sentAt: (input.now ?? (() => new Date()))().toISOString(),
        context: { library: { name: '@aether/sdk', version: input.loaderVersion } },
      }),
      {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${input.sdkKey}`,
        'X-Aether-SDK': 'web',
        ...(input.siteId ? { 'X-Aether-Site': input.siteId } : {}),
      },
    );
    return true;
  } catch {
    return false;
  }
}
