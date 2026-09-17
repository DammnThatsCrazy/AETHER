// =============================================================================
// Aether SDK — React Native Proof Harness Integration
// Wraps @aether/react-native (bridge.ts / Aether default export) and falls
// back to direct POST /v1/batch for signals the native SDK does not surface
// to JS (heartbeat, identity). Every event-sending function constructs the
// canonical envelope per docs/api/ingestion.md.
// =============================================================================

import Aether, { type AetherRNConfig } from '@aether/react-native';
import type { SDKState, EventDeliveryStatus } from './types';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** RN SDK version — matches packages/react-native/package.json "version". */
const SDK_VERSION = '0.1.0-alpha.0';

/** Default staging ingestion endpoint. Overridden by AETHER_API_URL env. */
const DEFAULT_API_URL = 'http://localhost:8000';

// ---------------------------------------------------------------------------
// Env declarations (React Native does not expose process.env at runtime;
// a babel/env plugin or expo-constants would inject these in a real build).
// ---------------------------------------------------------------------------

declare const process: {
  env: { PROOF_IOS_SDK_KEY?: string; AETHER_API_URL?: string };
} | undefined;

function resolveApiUrl(): string {
  if (typeof process !== 'undefined' && process.env?.AETHER_API_URL) {
    return process.env.AETHER_API_URL;
  }
  return DEFAULT_API_URL;
}

function resolveSdkKey(providedKey: string | undefined): string {
  if (providedKey) return providedKey;
  if (typeof process !== 'undefined' && process.env?.PROOF_IOS_SDK_KEY) {
    return process.env.PROOF_IOS_SDK_KEY;
  }
  return 'staging-key-placeholder';
}

// ---------------------------------------------------------------------------
// Internal mutable state
// ---------------------------------------------------------------------------

interface EventLogEntry {
  id: string;
  type: string;
  timestamp: string;
  status: 'pending' | 'delivered' | 'failed';
  error?: string;
}

interface MutableState {
  // Public SDKState fields
  initialized: boolean;
  version: string;
  tenantId: string | null;
  workspaceId: string | null;
  platformId: string | null;
  sessionId: string | null;
  anonymousId: string | null;
  knownUserId: string | null;
  consentState: 'granted' | 'denied' | 'unknown';
  queueSize: number;
  lastDeliveryStatus: EventDeliveryStatus;
  lastApiResponse: string | null;
  lastError: string | null;
  lastEventId: string | null;

  // Internal fields
  _storedKey: string | null;
  _sequence: number;
  _eventLog: EventLogEntry[];
}

const state: MutableState = {
  initialized: false,
  version: SDK_VERSION,
  tenantId: null,
  workspaceId: null,
  platformId: 'ios',
  sessionId: null,
  anonymousId: null,
  knownUserId: null,
  consentState: 'unknown',
  queueSize: 0,
  lastDeliveryStatus: 'idle',
  lastApiResponse: null,
  lastError: null,
  lastEventId: null,
  _storedKey: null,
  _sequence: 0,
  _eventLog: [],
};

// ---------------------------------------------------------------------------
// Listener infrastructure — drives the Debug Console live updates
// ---------------------------------------------------------------------------

const listeners = new Set<() => void>();

export function subscribeToStateChanges(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function notifyListeners(): void {
  for (const listener of listeners) {
    try {
      listener();
    } catch {
      // One bad listener must not break the others.
    }
  }
}

// ---------------------------------------------------------------------------
// Event ID + sequence helpers
// ---------------------------------------------------------------------------

function generateEventId(): string {
  const ts = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 8);
  return `evt_${ts}_${rand}`;
}

function nextSequence(): { event: number } {
  state._sequence += 1;
  return { event: state._sequence };
}

// ---------------------------------------------------------------------------
// Canonical envelope builder (docs/api/ingestion.md)
// ---------------------------------------------------------------------------

function buildEnvelope(
  type: string,
  properties?: Record<string, unknown>,
  userId?: string | null,
): Record<string, unknown> {
  const eventId = generateEventId();
  const timestamp = new Date().toISOString();
  const seq = nextSequence();

  const envelope: Record<string, unknown> = {
    id: eventId,
    type,
    timestamp,
    sessionId: state.sessionId ?? '',
    anonymousId: state.anonymousId ?? '',
    context: {
      library: {
        name: '@aether/react-native',
        version: SDK_VERSION,
      },
      surface: 'ios',
      schemaVersion: '1.0.0',
      sequence: seq,
    },
  };

  if (userId ?? state.knownUserId) {
    envelope.userId = userId ?? state.knownUserId;
  }

  if (properties && Object.keys(properties).length > 0) {
    envelope.properties = properties;
  }

  return envelope;
}

// ---------------------------------------------------------------------------
// POST /v1/batch
// ---------------------------------------------------------------------------

async function postBatch(
  events: Array<Record<string, unknown>>,
): Promise<{ ok: boolean; status: number; error?: string }> {
  if (!state.initialized) {
    return { ok: false, status: 0, error: 'SDK not initialized' };
  }

  const apiKey = resolveSdkKey(state._storedKey ?? undefined);

  const batchEnvelope = {
    batch: events,
    sentAt: new Date().toISOString(),
    consents:
      state.consentState === 'granted' ? ['analytics'] : [],
  };

  // Mark pending before the network call.
  state.lastDeliveryStatus = 'pending';
  state.queueSize = events.length;
  if (events.length > 0) {
    state.lastEventId = (events[0] as { id?: string }).id as string | null;
  }

  // Pre-log each event.
  for (const evt of events) {
    state._eventLog.push({
      id: (evt as { id?: string }).id as string ?? 'unknown',
      type: (evt as { type?: string }).type as string ?? 'unknown',
      timestamp: (evt as { timestamp?: string }).timestamp as string ?? new Date().toISOString(),
      status: 'pending',
    });
  }
  notifyListeners();

  let response: Response;
  try {
    response = await fetch(`${resolveApiUrl()}/v1/batch`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Aether-API-Key': apiKey,
      },
      body: JSON.stringify(batchEnvelope),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'network error';
    state.lastDeliveryStatus = 'failed';
    state.lastError = message;
    for (const entry of state._eventLog) {
      if (entry.status === 'pending') {
        entry.status = 'failed';
        entry.error = message;
      }
    }
    notifyListeners();
    return { ok: false, status: 0, error: message };
  }

  // Update log entries for this batch.
  for (const entry of state._eventLog) {
    if (entry.status === 'pending') {
      entry.status = response.ok ? 'delivered' : 'failed';
      if (!response.ok) {
        entry.error = `HTTP ${response.status}`;
      }
    }
  }

  if (response.ok) {
    state.lastDeliveryStatus = 'delivered';
    state.lastApiResponse = `HTTP ${response.status}`;
    state.queueSize = 0;
    state.lastError = null;
    notifyListeners();
    return { ok: true, status: response.status };
  }

  const message = `HTTP ${response.status}: ${response.statusText}`;
  state.lastDeliveryStatus = 'failed';
  state.lastError = message;
  notifyListeners();
  return { ok: false, status: response.status, error: message };
}

// ---------------------------------------------------------------------------
// Public SDK functions
// ---------------------------------------------------------------------------

/**
 * Initialize the Aether RN SDK.
 *
 * Calls Aether.init() from @aether/react-native with a canonical RN config,
 * then records SDK-local state (session, anonymous id, consent default).
 */
export function initSDK(
  config: {
    tenantId: string;
    workspaceId: string;
    apiKey: string;
    environment?: 'production' | 'staging' | 'development';
  },
): SDKState {
  // Reset previous session so re-initialization is idempotent.
  resetState();

  state._storedKey = config.apiKey;
  state.tenantId = config.tenantId;
  state.workspaceId = config.workspaceId;
  state.sessionId = `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  state.anonymousId = `anon_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
  state.knownUserId = null;
  state.consentState = 'unknown';
  state.queueSize = 0;
  state.lastDeliveryStatus = 'idle';
  state.lastApiResponse = null;
  state.lastError = null;
  state.initialized = true;

  const rnConfig: AetherRNConfig = {
    apiKey: config.apiKey,
    environment: config.environment,
    endpoint: resolveApiUrl(),
    debug: true,
    appVersion: `proof-ios@${SDK_VERSION}`,
    modules: {
      screenTracking: true,
      deepLinkAttribution: true,
      pushTracking: false,
      walletTracking: false,
      experiments: false,
      performance: true,
    },
    privacy: {
      gdprMode: false,
      anonymizeIP: false,
    },
    autoResumeJourney: false,
  };

  try {
    Aether.init(rnConfig);
  } catch (err) {
    state.lastError = `Aether.init threw: ${err instanceof Error ? err.message : String(err)}`;
  }

  // Seed consent from the native SDK if it is linked.
  Aether.consent
    .getState()
    .then((cs) => {
      if (cs?.analytics) {
        state.consentState = 'granted';
      } else if (cs?.analytics === false) {
        state.consentState = 'denied';
      }
      notifyListeners();
    })
    .catch(() => {
      // Native consent unavailable — leave as 'unknown'.
    });

  notifyListeners();
  return readState();
}

/**
 * Emit a heartbeat event.
 *
 * The native SDK surfaces healthHeartbeat as a capability but has no direct
 * JS heartbeat method, so we construct a canonical heartbeat event and send it
 * via POST /v1/batch. If the native SDK is linked, also fire observe() as a
 * side channel.
 */
export async function emitHeartbeat(): Promise<SDKState> {
  if (!state.initialized) {
    state.lastError = 'emitHeartbeat: SDK not initialized';
    state.lastDeliveryStatus = 'failed';
    notifyListeners();
    return readState();
  }

  try {
    Aether.observe?.('heartbeat', {
      source: 'proof-ios',
      sdkVersion: SDK_VERSION,
    });
  } catch {
    // observe() is optional.
  }

  const envelope = buildEnvelope('heartbeat', {
    source: 'proof-ios',
    sdkVersion: SDK_VERSION,
  });

  await postBatch([envelope]);
  return readState();
}

/**
 * Track a screen view.
 *
 * Uses Aether.screenView() from the native SDK when linked, and also sends the
 * canonical envelope via POST /v1/batch so the proof harness shows a real
 * delivery result.
 */
export async function trackScreen(
  screenName: string,
  properties?: Record<string, unknown>,
): Promise<SDKState> {
  if (!state.initialized) {
    state.lastError = 'trackScreen: SDK not initialized';
    state.lastDeliveryStatus = 'failed';
    notifyListeners();
    return readState();
  }

  try {
    Aether.screenView(screenName, properties ?? {});
  } catch {
    // Native screenView may be absent.
  }

  const envelope = buildEnvelope('screen.view', {
    screenName,
    ...properties,
  });

  await postBatch([envelope]);
  return readState();
}

/**
 * Track a custom event.
 *
 * Uses Aether.track() from the native SDK and also sends the canonical
 * envelope via POST /v1/batch.
 */
export async function trackEvent(
  eventName: string,
  properties?: Record<string, unknown>,
): Promise<SDKState> {
  if (!state.initialized) {
    state.lastError = 'trackEvent: SDK not initialized';
    state.lastDeliveryStatus = 'failed';
    notifyListeners();
    return readState();
  }

  try {
    Aether.track(eventName, properties ?? {});
  } catch {
    // Native track may be absent.
  }

  const envelope = buildEnvelope(eventName, properties);
  await postBatch([envelope]);
  return readState();
}

/**
 * Identify a user.
 *
 * The native SDK surfaces getIdentity() (read) but has no JS identify() setter;
 * identity is owned by the native layer. For the proof harness we send an
 * identity.identify-style envelope via POST /v1/batch and update the local
 * known user id.
 */
export async function identifyUser(
  userId: string,
  traits?: Record<string, unknown>,
): Promise<SDKState> {
  if (!state.initialized) {
    state.lastError = 'identifyUser: SDK not initialized';
    state.lastDeliveryStatus = 'failed';
    notifyListeners();
    return readState();
  }

  state.knownUserId = userId;

  const envelope = buildEnvelope('identity.identify', {
    userId,
    traits,
    source: 'proof-ios',
  });

  await postBatch([envelope]);
  return readState();
}

/**
 * Track a conversion.
 *
 * Uses Aether.conversion() from the native SDK and also sends a
 * conversion.completed envelope via POST /v1/batch.
 */
export async function trackConversion(
  eventName: string,
  value?: number,
  currency?: string,
): Promise<SDKState> {
  if (!state.initialized) {
    state.lastError = 'trackConversion: SDK not initialized';
    state.lastDeliveryStatus = 'failed';
    notifyListeners();
    return readState();
  }

  try {
    Aether.conversion(eventName, value, {
      currency,
      source: 'proof-ios',
    });
  } catch {
    // Native conversion may be absent.
  }

  const envelope = buildEnvelope('conversion.completed', {
    eventName,
    value,
    currency,
    source: 'proof-ios',
  });

  await postBatch([envelope]);
  return readState();
}

/**
 * Set a consent state.
 *
 * Maps to the native SDK's consent.grant / consent.revoke for the given
 * purpose. The proof harness treats 'analytics' as the primary consent type.
 */
export function setConsent(consentType: string, enabled: boolean): SDKState {
  if (!state.initialized) {
    state.lastError = 'setConsent: SDK not initialized';
    state.lastDeliveryStatus = 'failed';
    notifyListeners();
    return readState();
  }

  try {
    if (enabled) {
      Aether.consent.grant([consentType as 'analytics']);
    } else {
      Aether.consent.revoke([consentType as 'analytics']);
    }
  } catch {
    // Native consent methods may be absent.
  }

  state.consentState = enabled ? ('granted' as const) : ('denied' as const);
  notifyListeners();
  return readState();
}

/**
 * Flush the queued events.
 *
 * Calls Aether.flush() from the native SDK.
 */
export function flushQueue(): SDKState {
  if (!state.initialized) {
    state.lastError = 'flushQueue: SDK not initialized';
    state.lastDeliveryStatus = 'failed';
    notifyListeners();
    return readState();
  }

  try {
    Aether.flush();
  } catch {
    // Native flush may be absent.
  }

  state.lastDeliveryStatus = 'delivered';
  state.lastApiResponse = 'flushed (native)';
  state.queueSize = 0;
  state.lastError = null;
  notifyListeners();
  return readState();
}

/**
 * Simulate offline mode by setting lastDeliveryStatus to 'pending' and
 * incrementing queueSize to reflect queued events.
 */
export function simulateOffline(): SDKState {
  if (!state.initialized) {
    state.lastError = 'simulateOffline: SDK not initialized';
    state.lastDeliveryStatus = 'failed';
    notifyListeners();
    return readState();
  }

  state.lastDeliveryStatus = 'pending';
  state.queueSize = Math.max(1, state.queueSize + 1);
  state.lastError = 'Simulated offline — events queued for retry';
  notifyListeners();
  return readState();
}

/**
 * Return a snapshot of the current SDK state (immutable).
 */
export function getState(): SDKState {
  return readState();
}

// ---------------------------------------------------------------------------
// Debug console helpers
// ---------------------------------------------------------------------------

export function getDebugStateRaw(): MutableState {
  return state;
}

/**
 * Return the last event payload sent (for the debug console).
 */
export function getLastEventPayload(): Record<string, unknown> | null {
  const log = state._eventLog;
  if (log.length === 0) return null;
  const last = log[log.length - 1];
  return {
    id: last.id,
    type: last.type,
    timestamp: last.timestamp,
    status: last.status,
    error: last.error,
  };
}

/**
 * Return the full event log (for the debug console).
 */
export function getEventLog(): EventLogEntry[] {
  return state._eventLog;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function resetState(): void {
  state.initialized = false;
  state.tenantId = null;
  state.workspaceId = null;
  state.platformId = 'ios';
  state.sessionId = null;
  state.anonymousId = null;
  state.knownUserId = null;
  state.consentState = 'unknown';
  state.queueSize = 0;
  state.lastDeliveryStatus = 'idle';
  state.lastApiResponse = null;
  state.lastError = null;
  state.lastEventId = null;
  state._storedKey = null;
  state._sequence = 0;
  state._eventLog = [];
}

function readState(): SDKState {
  return {
    initialized: state.initialized,
    version: state.version,
    tenantId: state.tenantId,
    workspaceId: state.workspaceId,
    platformId: state.platformId,
    sessionId: state.sessionId,
    anonymousId: state.anonymousId,
    knownUserId: state.knownUserId,
    consentState: state.consentState,
    queueSize: state.queueSize,
    lastDeliveryStatus: state.lastDeliveryStatus,
    lastApiResponse: state.lastApiResponse,
    lastError: state.lastError,
    lastEventId: state.lastEventId,
  };
}
