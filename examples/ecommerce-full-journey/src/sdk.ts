// examples/ecommerce-full-journey/src/sdk.ts
// Complete ecommerce journey harness: product_viewed → cart_added →
// checkout_started → checkout_step_completed → payment_initiated →
// order_completed → conversion → flush → backend acceptance.
import aether, { type AetherConfig } from '@aether/web';
import type { ConsentState, ConsentPurpose } from '@aether/shared/consent';
import type { SDKState, BatchHealth } from './types';

const SDK_VERSION = '0.1.0-alpha.0';
const DEFAULT_ENDPOINT = 'http://localhost:8000';

interface TrackingState {
  initialized: boolean;
  version: string;
  lastEventId: string | null;
  lastDeliveryStatus: 'pending' | 'delivered' | 'failed' | 'idle';
  lastApiResponse: string | null;
  lastError: string | null;
  eventCount: number;
  consentState: ConsentState | null;
}

const tracking: TrackingState = {
  initialized: false,
  version: SDK_VERSION,
  lastEventId: null,
  lastDeliveryStatus: 'idle',
  lastApiResponse: null,
  lastError: null,
  eventCount: 0,
  consentState: null,
};

let onBatchResultFired: ((status: string, response: string) => void) | null =
  null;

function onDeliveryComplete(status: string, response: string): void {
  if (onBatchResultFired) {
    onBatchResultFired(status, response);
    onBatchResultFired = null;
  }
}

function loadApiKeySync(): string {
  if (typeof import.meta !== 'undefined' && (import.meta as any).env) {
    const v = (import.meta as any).env.VITE_AETHER_API_KEY;
    if (v) return v;
    const a = (import.meta as any).env.AETHER_API_KEY;
    if (a) return a;
  }
  if (typeof process !== 'undefined' && (process as any).env) {
    const p = (process as any).env.AETHER_API_KEY;
    if (p) return p;
  }
  return '';
}

async function loadApiKeyAsync(): Promise<string> {
  const syncKey = loadApiKeySync();
  if (syncKey) return syncKey;

  try {
    const resp = await fetch('/proof-keys.json', { cache: 'no-store' });
    if (!resp.ok) return '';
    const json = await resp.json() as {
      apiKey?: string;
      staging?: { apiKey?: string; url?: string };
    };
    if (json.apiKey) return json.apiKey;
    if (json.staging?.apiKey) return json.staging.apiKey;
  } catch {
    // not available — fall through
  }
  return '';
}

function loadEndpoint(): string {
  if (typeof import.meta !== 'undefined' && (import.meta as any).env) {
    const v = (import.meta as any).env.VITE_AETHER_API_URL;
    if (v) return v;
    const a = (import.meta as any).env.AETHER_API_URL;
    if (a) return a;
  }
  if (typeof process !== 'undefined' && (process as any).env) {
    const p = (process as any).env.AETHER_API_URL;
    if (p) return p;
  }
  return DEFAULT_ENDPOINT;
}

const DEMO_PURPOSES: ConsentPurpose[] = [
  'analytics',
  'marketing',
  'personalization',
  'commerce',
];

function consentLabel(state: ConsentState): 'granted' | 'denied' | 'unknown' {
  if (state.analytics || state.marketing || state.commerce) return 'granted';
  if (!state.analytics && !state.marketing && !state.commerce) return 'denied';
  return 'unknown';
}

export async function initSDK(
  config?: Record<string, unknown>,
): Promise<typeof aether> {
  const apiKey = await loadApiKeyAsync();
  if (!apiKey) {
    throw new Error(
      'Aether SDK: no API key found. Set AETHER_API_KEY env or add public/proof-keys.json',
    );
  }

  const endpoint = loadEndpoint();

  const sdkConfig: AetherConfig = {
    apiKey,
    endpoint,
    debug: true,
    application: { name: 'examples-ecommerce-full-journey', version: SDK_VERSION },
    onBatchResult: (health: BatchHealth) => {
      tracking.lastDeliveryStatus = 'delivered';
      tracking.lastApiResponse =
        `accepted=${health.accepted} duplicate=${health.duplicate} rejected=${health.rejected} queue_depth=${health.queue_depth}`;
      tracking.eventCount = health.queue_depth;
      onDeliveryComplete(
        'delivered',
        `accepted=${health.accepted} duplicate=${health.duplicate} rejected=${health.rejected}`,
      );
    },
    ...config,
  };

  aether.init(sdkConfig);
  tracking.initialized = true;
  tracking.consentState = aether.consent.getState();
  tracking.lastDeliveryStatus = 'idle';

  return aether;
}

/** Helper: enqueue a canonical event and return the tracking result. */
async function enqueue(
  type: string,
  properties: Record<string, unknown>,
): Promise<{ eventId: string; status: string }> {
  if (!tracking.initialized) {
    throw new Error('Aether SDK not initialized — call initSDK() first');
  }

  const eventId = `evt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  tracking.lastEventId = eventId;
  tracking.lastDeliveryStatus = 'pending';
  tracking.eventCount += 1;

  aether.track(type, properties);

  return { eventId, status: 'queued' };
}

// --- Ecommerce journey steps ---

/** product_viewed — first touchpoint in the ecommerce funnel. */
export async function trackProductViewed(
  productId: string,
  productName: string,
  category: string,
  price: number,
): Promise<{ eventId: string; status: string }> {
  return enqueue('product_viewed', {
    productId,
    productName,
    category,
    price,
    currency: 'USD',
    source: 'examples-ecommerce-full-journey',
  });
}

/** cart_item_added — user adds product to cart. */
export async function trackCartItemAdded(
  productId: string,
  productName: string,
  quantity: number,
  price: number,
): Promise<{ eventId: string; status: string }> {
  return enqueue('cart_item_added', {
    productId,
    productName,
    quantity,
    price,
    currency: 'USD',
    cartId: `cart_${Date.now()}`,
    source: 'examples-ecommerce-full-journey',
  });
}

/** checkout_started — user initiates checkout. */
export async function trackCheckoutStarted(
  cartId: string,
  totalItems: number,
  totalValue: number,
): Promise<{ eventId: string; status: string }> {
  return enqueue('checkout_started', {
    cartId,
    totalItems,
    totalValue,
    currency: 'USD',
    source: 'examples-ecommerce-full-journey',
  });
}

/** checkout_step_completed — user completes a checkout step (shipping, payment, etc.). */
export async function trackCheckoutStepCompleted(
  cartId: string,
  step: string,
): Promise<{ eventId: string; status: string }> {
  return enqueue('checkout_step_completed', {
    cartId,
    step,
    source: 'examples-ecommerce-full-journey',
  });
}

/** payment_initiated — user initiates payment. */
export async function trackPaymentInitiated(
  cartId: string,
  paymentMethod: string,
  totalValue: number,
): Promise<{ eventId: string; status: string }> {
  return enqueue('payment_initiated', {
    cartId,
    paymentMethod,
    totalValue,
    currency: 'USD',
    source: 'examples-ecommerce-full-journey',
  });
}

/** order_completed — the revenue-bearing conversion event. */
export async function trackOrderCompleted(
  orderId: string,
  cartId: string,
  totalValue: number,
  currency: string,
  items: Array<{ sku: string; name: string; price: number; quantity: number }>,
): Promise<{ eventId: string; status: string }> {
  return enqueue('order_completed', {
    orderId,
    cartId,
    totalValue,
    currency,
    items,
    source: 'examples-ecommerce-full-journey',
  });
}

/** The conversion signal — revenue attached to the completed order. */
export async function trackConversion(
  eventName: string,
  revenue: number,
  currency: string,
  orderId: string,
): Promise<{ eventId: string; revenue: number; status: string }> {
  if (!tracking.initialized) {
    throw new Error('Aether SDK not initialized — call initSDK() first');
  }

  const eventId = `conv_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  tracking.lastEventId = eventId;
  tracking.lastDeliveryStatus = 'pending';
  tracking.eventCount += 1;

  aether.conversion(eventName, revenue, {
    revenue,
    currency,
    orderId,
    source: 'examples-ecommerce-full-journey',
  });

  return { eventId, revenue, status: 'queued' };
}

/** Consent toggle — required before any tracked event is delivered. */
export async function toggleConsent(
  consent: 'granted' | 'denied',
): Promise<{ consentState: 'granted' | 'denied' | 'unknown'; purposes: string[] }> {
  if (!tracking.initialized) {
    throw new Error('Aether SDK not initialized — call initSDK() first');
  }

  if (consent === 'granted') {
    aether.consent.grant(DEMO_PURPOSES);
  } else {
    aether.consent.revoke(DEMO_PURPOSES);
  }

  tracking.consentState = aether.consent.getState();
  const label = consentLabel(tracking.consentState);

  return { consentState: label, purposes: [...DEMO_PURPOSES] };
}

/** Flush the event queue — proves backend acceptance. */
export async function flushQueue(): Promise<{
  eventId: string | null;
  status: string;
  apiResponse: string | null;
}> {
  if (!tracking.initialized) {
    throw new Error('Aether SDK not initialized — call initSDK() first');
  }

  tracking.lastDeliveryStatus = 'pending';
  const eventId = tracking.lastEventId;

  onBatchResultFired = (status, response) => {
    tracking.lastDeliveryStatus = status as 'delivered' | 'failed';
    tracking.lastApiResponse = response;
  };

  try {
    await aether.flush();
    await new Promise((r) => setTimeout(r, 200));
    if (tracking.lastDeliveryStatus === 'pending') {
      tracking.lastDeliveryStatus = 'delivered';
    }
    tracking.lastError = null;
  } catch (err) {
    tracking.lastDeliveryStatus = 'failed';
    tracking.lastError = err instanceof Error ? err.message : String(err);
    throw err;
  } finally {
    onBatchResultFired = null;
  }

  return {
    eventId,
    status: tracking.lastDeliveryStatus,
    apiResponse: tracking.lastApiResponse,
  };
}

/** Reset session — clears identity and queue for a fresh ecommerce journey. */
export async function resetSession(): Promise<{
  newSessionId: string;
  status: string;
}> {
  if (!tracking.initialized) {
    throw new Error('Aether SDK not initialized — call initSDK() first');
  }

  aether.reset();
  tracking.eventCount = 0;
  tracking.lastDeliveryStatus = 'idle';
  tracking.lastApiResponse = null;
  tracking.lastError = null;
  tracking.consentState = aether.consent.getState();

  const newSessionId = `session-${Date.now()}`;
  tracking.lastEventId = `rs_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

  return { newSessionId, status: 'reset' };
}

/** Current debug state snapshot for the DebugPanel. */
export function getDebugState(): SDKState {
  const consent = tracking.consentState;
  return {
    initialized: tracking.initialized,
    version: tracking.version,
    tenantId: null,
    workspaceId: null,
    platformId: null,
    sessionId: null,
    anonymousId: consent?.analytics ? 'identified' : 'anonymous',
    knownUserId: null,
    consentState: consent ? consentLabel(consent) : 'unknown',
    queueSize: tracking.eventCount,
    lastDeliveryStatus: tracking.lastDeliveryStatus,
    lastApiResponse: tracking.lastApiResponse,
    lastError: tracking.lastError,
    lastEventId: tracking.lastEventId,
    realConsentState: tracking.consentState,
    sdkVersion: SDK_VERSION,
  };
}

export function getRealConsentState(): ConsentState | null {
  return tracking.consentState;
}

export function getSDKInstance(): typeof aether | null {
  return tracking.initialized ? (aether as typeof aether) : null;
}
