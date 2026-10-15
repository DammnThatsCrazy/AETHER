// @aether/proof-connectors — thin @aether/web SDK wrapper
// Initializes the real Aether SDK with proof-connectors platform context and
// exposes connector-lifecycle event emitters that send canonical envelopes to
// POST /v1/batch via the SDK's EventQueue.
//
// SDK import: default export is the singleton AetherSDK instance.
// Import: import Aether from '@aether/web';
// Init: Aether.init(config);
// Emit: Aether.observe(type, props) for canonical events, Aether.track(name, props) for custom events.

import Aether from '@aether/web';
import type { AetherConfig } from '@aether/web';
import type { ConnectorState } from './types';

// ---------------------------------------------------------------------------
// Config from environment (Vite exposes VITE_* vars to client code)
// ---------------------------------------------------------------------------

const AETHER_API_URL = (import.meta.env as { VITE_AETHER_API_URL?: string }).VITE_AETHER_API_URL ?? '';
const AETHER_API_KEY = (import.meta.env as { VITE_AETHER_API_KEY?: string }).VITE_AETHER_API_KEY ?? '';

// ---------------------------------------------------------------------------
// SDK singleton state
// ---------------------------------------------------------------------------

let sdkInitialized = false;
let sdkVersion = '0.1.0-alpha.0'; // mirrors @aether/web package.json version

// ---------------------------------------------------------------------------
// Config builder
// ---------------------------------------------------------------------------

function getSdkConfig(): AetherConfig {
  const apiKey = AETHER_API_KEY || '';
  return {
    apiKey,
    endpoint: AETHER_API_URL.replace(/\/+$/, ''),
    environment: 'staging',
    appVersion: '0.1.0-alpha.0',
    debug: true,
    application: {
      name: 'proof-connectors',
      version: '0.1.0-alpha.0',
      environment: 'staging',
      namespace: 'proof-connectors',
    },
    modules: {
      autoDiscovery: false,
      commerceDetection: false,
      ecommerce: false,
      formAnalytics: false,
      featureFlags: false,
      heatmaps: false,
      funnels: false,
      performance: false,
      walletTracking: false,
      svmTracking: false,
      bitcoinTracking: false,
      moveTracking: false,
      nearTracking: false,
      tronTracking: false,
      cosmosTracking: false,
      aptosTracking: false,
      tonTracking: false,
      starknetTracking: false,
      cardanoTracking: false,
      substrateTracking: false,
      algorandTracking: false,
      hederaTracking: false,
      stellarTracking: false,
      icpTracking: false,
    },
    privacy: {
      respectDNT: false,
      sanitizeUrls: false,
      gdprMode: false,
    },
    advanced: {
      batchSize: 10,
      flushInterval: 1000,
      maxQueueSize: 100,
      heartbeatInterval: 30000,
    },
    // Note: 'platform' and 'version' are not part of the public AetherConfig type.
    // The SDK stamps platform context via application.namespace and the event
    // envelope — connector-specific platform tagging is done per-event in
    // trackConnectorEvent / emitHeartbeat.
  };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Returns the @aether/web SDK version string. */
export function getSDKVersion(): string {
  return sdkVersion;
}

/**
 * Initialize the @aether/web SDK singleton with proof-connectors platform context.
 * Must be called before any track/observe/flush calls.
 */
export async function initSDK(): Promise<void> {
  if (sdkInitialized) {
    // Re-init: destroy previous instance, fresh start
    Aether.destroy();
    sdkInitialized = false;
  }

  if (!AETHER_API_KEY) {
    console.warn('[proof-connectors/sdk] No VITE_AETHER_API_KEY set — SDK init skipped (events will not be sent)');
    return;
  }

  if (!AETHER_API_URL) {
    console.warn('[proof-connectors/sdk] No VITE_AETHER_API_URL set — SDK init skipped (events will not be sent)');
    return;
  }

  const config = getSdkConfig();
  Aether.init(config);
  sdkInitialized = true;

  console.log(`[proof-connectors/sdk] Initialized @aether/web v${sdkVersion} → ${config.endpoint}/v1/batch`);
}

/** True if the SDK was initialized with a valid API key and endpoint. */
export function isSDKAvailable(): boolean {
  return sdkInitialized;
}

/**
 * Emit a heartbeat event via the SDK's EventQueue → POST /v1/batch.
 * Uses observe() with the canonical 'heartbeat' event type.
 */
export function emitHeartbeat(): void {
  if (!isSDKAvailable()) {
    console.warn('[proof-connectors/sdk] emitHeartbeat: SDK not available');
    return;
  }
  Aether.observe('heartbeat', {
    platform_id: 'proof-connectors',
    tenant_id: (import.meta.env as { VITE_AETHER_TENANT_ID?: string }).VITE_AETHER_TENANT_ID ?? 'aether-proof-tenant',
    workspace_id: (import.meta.env as { VITE_AETHER_WORKSPACE_ID?: string }).VITE_AETHER_WORKSPACE_ID ?? 'proof-lab',
    connector_status: 'active',
  });
}

/**
 * Track a connector action event via the SDK.
 * Uses track() for custom application events — the event name is the connector
 * action identifier (e.g. 'connector.connect', 'connector.backfill.start').
 *
 * The SDK wraps this as a 'track' type event with the event name in properties.
 * For canonical event types (heartbeat, integration_connected, etc.), use observe().
 */
export function trackConnectorEvent(eventType: string, properties: Record<string, unknown> = {}): void {
  if (!isSDKAvailable()) {
    console.warn(`[proof-connectors/sdk] trackConnectorEvent('${eventType}'): SDK not available`);
    return;
  }
  Aether.track(eventType, {
    ...properties,
    platform_id: 'proof-connectors',
    tenant_id: (import.meta.env as { VITE_AETHER_TENANT_ID?: string }).VITE_AETHER_TENANT_ID ?? 'aether-proof-tenant',
    workspace_id: (import.meta.env as { VITE_AETHER_WORKSPACE_ID?: string }).VITE_AETHER_WORKSPACE_ID ?? 'proof-lab',
  });
}

/**
 * Identify a connector provider — emits an identify event so the backend knows
 * which provider this proof session is acting as.
 */
export function identifyConnector(providerId: string): void {
  if (!isSDKAvailable()) {
    console.warn('[proof-connectors/sdk] identifyConnector: SDK not available');
    return;
  }
  // The @aether/web SDK does not expose a dedicated `identify()` method on the
  // singleton. Emit the identity as a canonical `identify` event via observe()
  // (which accepts any registry event type) — this is the correct public path.
  Aether.observe('identify', {
    provider_id: providerId,
    platform_id: 'proof-connectors',
    tenant_id: (import.meta.env as { VITE_AETHER_TENANT_ID?: string }).VITE_AETHER_TENANT_ID ?? 'aether-proof-tenant',
    workspace_id: (import.meta.env as { VITE_AETHER_WORKSPACE_ID?: string }).VITE_AETHER_WORKSPACE_ID ?? 'proof-lab',
    connector_type: 'proof-connector',
  });
}

/**
 * Signal that a connector was disconnected — emits an integration_disconnected
 * canonical event via observe().
 */
export function signalDisconnect(): void {
  if (!isSDKAvailable()) return;
  Aether.observe('integration_disconnected', {
    platform_id: 'proof-connectors',
    tenant_id: (import.meta.env as { VITE_AETHER_TENANT_ID?: string }).VITE_AETHER_TENANT_ID ?? 'aether-proof-tenant',
    workspace_id: (import.meta.env as { VITE_AETHER_WORKSPACE_ID?: string }).VITE_AETHER_WORKSPACE_ID ?? 'proof-lab',
  });
}

/**
 * Force-flush the SDK's event queue so events are sent immediately rather
 * than waiting for the next flush interval.
 */
export async function flushConnectorEvents(): Promise<void> {
  if (!isSDKAvailable()) return;
  await Aether.flush();
}

/**
 * Return a snapshot of the SDK's known state.
 */
export function getSDKState(): {
  initialized: boolean;
  version: string;
  apiUrl: string;
  apiKeySet: boolean;
} {
  return {
    initialized: sdkInitialized,
    version: sdkVersion,
    apiUrl: AETHER_API_URL,
    apiKeySet: !!AETHER_API_KEY,
  };
}
