// @aether/proof-connectors — connector panel state + actions
// FPS-061–FPS-063: live connector state with real ingestion API calls
// + @aether/web SDK integration for canonical event envelopes

import type { ConnectorState, ConnectorProvider, CredentialStatus, TokenRefreshStatus, BackfillStatus, IncrementalSyncStatus, WebhookStatus, GraphWrites, GraphNode, GraphEdge } from './types';
import { initialConnectorState } from './types';
import * as sdk from './sdk';

// ---------------------------------------------------------------------------
// API helpers — direct POST to ingestion API (for connector action batches)
// ---------------------------------------------------------------------------

const AETHER_API_URL = (import.meta.env as { VITE_AETHER_API_URL?: string }).VITE_AETHER_API_URL ?? '';
const AETHER_API_KEY = (import.meta.env as { VITE_AETHER_API_KEY?: string }).VITE_AETHER_API_KEY ?? '';

function apiBaseUrl(): string {
  return AETHER_API_URL.replace(/\/+$/, '');
}

/**
 * POST a batch of events to the Aether ingestion API.
 * Body format: { batch: Event[], sentAt: string, consents: object }
 * Auth header: X-Aether-API-Key
 * Response: { batchId, receivedAt, accepted, duplicates, rejected, events: [{ eventId, status, error? }] }
 */
async function postBatch(events: unknown[]): Promise<{
  ok: boolean;
  status: number;
  batchId?: string;
  receivedAt?: string;
  accepted: number;
  rejected: number;
  duplicates: number;
  eventResults: Array<{ eventId: string; status: string; error?: string }>;
}> {
  if (!apiBaseUrl()) {
    throw new Error('VITE_AETHER_API_URL is not set — cannot reach ingestion API');
  }
  if (!AETHER_API_KEY) {
    throw new Error('VITE_AETHER_API_KEY is not set — cannot authenticate to ingestion API');
  }

  const base = apiBaseUrl();
  const url = new URL('/v1/batch', base);

  const payload = {
    batch: events,
    sentAt: new Date().toISOString(),
    consents: {},
  };

  const response = await fetch(url.toString(), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Aether-API-Key': AETHER_API_KEY,
    },
    body: JSON.stringify(payload),
  });

  const body = (await response.json()) as {
    batchId?: string;
    receivedAt?: string;
    accepted?: number;
    rejected?: number;
    duplicates?: number;
    events?: Array<{ eventId?: string; status?: string; error?: string }>;
  };

  return {
    ok: response.ok,
    status: response.status,
    batchId: body.batchId,
    receivedAt: body.receivedAt,
    accepted: body.accepted ?? 0,
    rejected: body.rejected ?? 0,
    duplicates: body.duplicates ?? 0,
    eventResults: (body.events ?? []).map((e) => ({
      eventId: e.eventId ?? 'unknown',
      status: e.status ?? 'unknown',
      error: e.error,
    })),
  };
}

// ---------------------------------------------------------------------------
// Fixture loaders (reads from @aether/proof-fixtures — bundled by Vite)
// ---------------------------------------------------------------------------

import {
  stripeCustomerFixture,
  stripePaymentFixture,
  stripeRefundFixture,
  shopifyCustomerFixture,
  shopifyOrderFixture,
  shopifyProductFixture,
  emailSentFixture,
  emailOpenFixture,
  emailClickFixture,
  emailBounceFixture,
  emailUnsubscribeFixture,
  graphProfileNodeFixture,
  graphJourneyNodeFixture,
  graphCampaignNodeFixture,
  graphCommunicationNodeFixture,
  graphConversionNodeFixture,
  graphValueNodeFixture,
  graphTouchpointEdgeFixture,
  graphAttributionEdgeFixture,
} from '@aether/proof-fixtures';

// ---------------------------------------------------------------------------
// Normalized event builders (for ingestion API payloads)
// ---------------------------------------------------------------------------

function buildCustomerCreatedEvent(customerId: string): unknown {
  return {
    event_id: `evt_cust_${customerId}`,
    event_type: 'customer.created',
    timestamp: new Date().toISOString(),
    source: 'stripe',
    data: {
      customer_id: customerId,
      email: 'stripe@example.com',
      name: 'Test Customer',
    },
  };
}

function buildPaymentSucceededEvent(paymentId: string): unknown {
  return {
    event_id: `evt_pay_${paymentId}`,
    event_type: 'payment_intent.succeeded',
    timestamp: new Date().toISOString(),
    source: 'stripe',
    data: {
      payment_intent_id: paymentId,
      amount: 9999,
      currency: 'usd',
      status: 'succeeded',
      customer_id: 'cus_test_001',
    },
  };
}

function buildRefundCreatedEvent(refundId: string): unknown {
  return {
    event_id: `evt_ref_${refundId}`,
    event_type: 'refund.created',
    timestamp: new Date().toISOString(),
    source: 'stripe',
    data: {
      refund_id: refundId,
      amount: 5000,
      currency: 'usd',
      reason: 'requested_by_customer',
      status: 'succeeded',
    },
  };
}

function buildShopifyCustomerEvent(customerId: string): unknown {
  return {
    event_id: `shop_evt_cust_${customerId}`,
    event_type: 'customer.created',
    timestamp: new Date().toISOString(),
    source: 'shopify',
    data: {
      customer_id: customerId,
      email: 'shopify@example.com',
      first_name: 'Jane',
      last_name: 'Doe',
      orders_count: 3,
      total_spent: '250.00',
    },
  };
}

function buildShopifyProductEvent(productId: string): unknown {
  return {
    event_id: `shop_evt_prod_${productId}`,
    event_type: 'product.created',
    timestamp: new Date().toISOString(),
    source: 'shopify',
    data: {
      product_id: productId,
      title: 'Demo Widget',
      vendor: 'AetherDemo',
      product_type: 'Widget',
    },
  };
}

function buildShopifyOrderEvent(orderId: string, customerId: string, productId: string): unknown {
  return {
    event_id: `shop_evt_ord_${orderId}`,
    event_type: 'order.created',
    timestamp: new Date().toISOString(),
    source: 'shopify',
    data: {
      order_id: orderId,
      order_number: '#1001',
      customer_id: customerId,
      customer_email: 'shopify@example.com',
      total_value: 75.00,
      currency: 'usd',
      items: [
        {
          product_id: productId,
          name: 'Demo Widget',
          quantity: 2,
          unit_price: 25.00,
        },
      ],
    },
  };
}

function buildEmailEvent(
  fixture: { type: string; email: string; campaignId: string; timestamp: number; metadata?: Record<string, string> },
  eventType: string
): unknown {
  return {
    event_id: `email_${eventType}_${fixture.email.replace(/[^a-z0-9]/gi, '_')}`,
    event_type: `email.${eventType}`,
    timestamp: new Date(fixture.timestamp).toISOString(),
    source: 'sendgrid',
    data: {
      message_id: `msg_${eventType}_001`,
      sender: 'noreply@example.com',
      recipient: fixture.email,
      subject: 'Welcome!',
      campaign_id: fixture.campaignId,
      ...(fixture.metadata ?? {}),
    },
  };
}

// ---------------------------------------------------------------------------
// Graph write builders (for View Graph Writes)
// ---------------------------------------------------------------------------

function buildGraphWrites(): GraphWrites {
  const toNode = (f: Record<string, unknown>): GraphNode => ({
    id: (f.id as string) ?? 'unknown',
    type: (f.type as string) ?? 'unknown',
    properties: (f.properties as Record<string, unknown>) ?? {},
    ...(f.createdAt != null ? { created_at: new Date(f.createdAt as number).toISOString() } : {}),
    ...(f.updatedAt != null ? { updated_at: new Date(f.updatedAt as number).toISOString() } : {}),
  });
  const toEdge = (f: Record<string, unknown>): GraphEdge => {
    const edge: GraphEdge = {
      id: (f.id as string) ?? 'unknown',
      source: (f.source as string) ?? 'unknown',
      target: (f.target as string) ?? 'unknown',
      type: (f.type as string) ?? 'unknown',
      properties: (f.properties as Record<string, unknown>) ?? {},
      created_at: new Date().toISOString(),
    };
    if (f.weight != null) {
      edge.weight = f.weight as number;
    }
    return edge;
  };
  return {
    nodes: [
      toNode(graphProfileNodeFixture as Record<string, unknown>),
      toNode(graphJourneyNodeFixture as Record<string, unknown>),
      toNode(graphCampaignNodeFixture as Record<string, unknown>),
      toNode(graphCommunicationNodeFixture as Record<string, unknown>),
      toNode(graphConversionNodeFixture as Record<string, unknown>),
      toNode(graphValueNodeFixture as Record<string, unknown>),
    ],
    edges: [
      toEdge(graphTouchpointEdgeFixture as Record<string, unknown>),
      toEdge(graphAttributionEdgeFixture as Record<string, unknown>),
    ],
  };
}

// ---------------------------------------------------------------------------
// State management (mutable singleton — consumed by React via subscription)
// ---------------------------------------------------------------------------

let state: ConnectorState = { ...initialConnectorState };
const listeners: Array<() => void> = [];

function notify(): void {
  for (const fn of listeners) {
    try { fn(); } catch { /* isolate listener errors */ }
  }
}

export function subscribe(fn: () => void): () => void {
  listeners.push(fn);
  return () => {
    const idx = listeners.indexOf(fn);
    if (idx !== -1) listeners.splice(idx, 1);
  };
}

export function getState(): ConnectorState {
  return state;
}

function setState(partial: Partial<ConnectorState>): void {
  state = { ...state, ...partial };
  notify();
}

// ---------------------------------------------------------------------------
// Connector actions
// ---------------------------------------------------------------------------

export async function connectProvider(providerType: ConnectorProvider): Promise<void> {
  setState({
    status: 'connecting',
    provider: providerType,
    lastAction: `connect:${providerType}`,
    lastActionResult: null,
    credentialStatus: 'valid' as CredentialStatus,
    tokenRefreshStatus: 'valid' as TokenRefreshStatus,
  });

  // Prove the connector was activated via the @aether/web SDK.
  sdk.identifyConnector(providerType);
  sdk.trackConnectorEvent('connector.connect', { provider: providerType });
  sdk.emitHeartbeat();
  await sdk.flushConnectorEvents().catch(() => {});

  // Brief simulated delay, then mark connected.
  await new Promise((r) => setTimeout(r, 300));

  setState({
    status: 'connected',
    lastActionResult: { success: true, message: `${providerType} provider connected` },
  });
}

export async function disconnectProvider(): Promise<void> {
  // Signal disconnect via SDK before clearing state.
  sdk.signalDisconnect();
  sdk.trackConnectorEvent('connector.disconnect', { provider: state.provider });
  await sdk.flushConnectorEvents().catch(() => {});

  setState({
    status: 'disconnected',
    provider: null,
    credentialStatus: 'missing',
    backfillStatus: 'idle',
    webhookStatus: 'idle',
    incrementalSyncStatus: 'idle',
    lastAction: 'disconnect',
    lastActionResult: { success: true, message: 'Provider disconnected' },
    sync: {
      recordsReceived: 0,
      recordsAccepted: 0,
      recordsRejected: 0,
      recordsNormalized: 0,
      recordsWritten: 0,
      lastError: null,
      degradedReason: null,
      lastSyncAt: null,
    },
  });
}

export async function reconnectProvider(): Promise<void> {
  if (!state.provider) {
    setState({
      lastAction: 'reconnect',
      lastActionResult: { success: false, message: 'No provider to reconnect — connect first' },
    });
    return;
  }
  await disconnectProvider();
  await new Promise((r) => setTimeout(r, 100));
  // Re-identify and emit heartbeat to prove reconnection.
  sdk.identifyConnector(state.provider);
  sdk.trackConnectorEvent('connector.reconnect', { provider: state.provider });
  sdk.emitHeartbeat();
  await sdk.flushConnectorEvents().catch(() => {});
  await connectProvider(state.provider);
}

export async function startBackfill(): Promise<void> {
  if (!state.provider) {
    setState({
      lastAction: 'backfill',
      lastActionResult: { success: false, message: 'No provider connected — connect first' },
    });
    return;
  }

  setState({
    status: 'backfilling',
    backfillStatus: 'running',
    lastAction: 'backfill',
    lastActionResult: null,
    incrementalSyncStatus: 'idle' as IncrementalSyncStatus,
  });

  // Prove the backfill started via the @aether/web SDK.
  sdk.trackConnectorEvent('connector.backfill_start', {
    provider: state.provider,
    recordCount: 3,
  });
  await sdk.flushConnectorEvents().catch(() => {});

  // Read fixture data and POST to the ingestion API as a batch.
  let events: unknown[];
  try {
    if (state.provider === 'stripe') {
      const customer = stripeCustomerFixture as Record<string, unknown>;
      const payment = stripePaymentFixture as Record<string, unknown>;
      const refund = stripeRefundFixture as Record<string, unknown>;
      const cid = ((customer.properties as Record<string, unknown>)?.id ?? 'cus_test_001') as string;
      const pid = ((payment.properties as Record<string, unknown>)?.id ?? 'pay_test_001') as string;
      const rid = ((refund.id as string) ?? 'ref_test_001') as string;
      events = [
        buildCustomerCreatedEvent(cid),
        buildPaymentSucceededEvent(pid),
        buildRefundCreatedEvent(rid),
      ];
    } else if (state.provider === 'shopify') {
      const customer = shopifyCustomerFixture as Record<string, unknown>;
      const order = shopifyOrderFixture as Record<string, unknown>;
      const product = shopifyProductFixture as Record<string, unknown>;
      const cid = ((customer.properties as Record<string, unknown>)?.id ?? 'shop_cus_001') as string;
      const oid = ((order.id as string) ?? 'shop_ord_001') as string;
      const pid = ((product.id as string) ?? 'shop_prod_001') as string;
      events = [
        buildShopifyCustomerEvent(cid),
        buildShopifyProductEvent(pid),
        buildShopifyOrderEvent(oid, cid, pid),
      ];
    } else {
      // email fixture
      const sent = emailSentFixture as Record<string, unknown>;
      const opened = emailOpenFixture as Record<string, unknown>;
      const clicked = emailClickFixture as Record<string, unknown>;
      const bounced = emailBounceFixture as Record<string, unknown>;
      const unsubed = emailUnsubscribeFixture as Record<string, unknown>;

      events = [
        buildEmailEvent(
          { type: 'sent', email: (sent.email as string) ?? 'user@example.com', campaignId: (sent.campaignId as string) ?? 'camp_001', timestamp: (sent.timestamp as number) ?? 1726000000000 },
          'sent'
        ),
        buildEmailEvent(
          { type: 'open', email: (opened.email as string) ?? 'user@example.com', campaignId: (opened.campaignId as string) ?? 'camp_001', timestamp: (opened.timestamp as number) ?? 1726000001000 },
          'open'
        ),
        buildEmailEvent(
          { type: 'click', email: (clicked.email as string) ?? 'user@example.com', campaignId: (clicked.campaignId as string) ?? 'camp_001', timestamp: (clicked.timestamp as number) ?? 1726000002000, metadata: (clicked.metadata as Record<string, string>) ?? { link: 'https://example.com/offer' } },
          'click'
        ),
        buildEmailEvent(
          { type: 'bounce', email: (bounced.email as string) ?? 'bounce@example.com', campaignId: (bounced.campaignId as string) ?? 'camp_001', timestamp: (bounced.timestamp as number) ?? 1726000000000, metadata: (bounced.metadata as Record<string, string>) ?? { reason: 'hard_bounce' } },
          'bounce'
        ),
        buildEmailEvent(
          { type: 'unsubscribe', email: (unsubed.email as string) ?? 'unsub@example.com', campaignId: (unsubed.campaignId as string) ?? 'camp_001', timestamp: (unsubed.timestamp as number) ?? 1726000000000 },
          'unsubscribe'
        ),
      ];
    }
  } catch (err) {
    setState({
      status: 'error',
      backfillStatus: 'failed',
      lastAction: 'backfill',
      lastActionResult: { success: false, message: `Fixture load failed: ${err}` },
      sync: {
        ...state.sync,
        lastError: `Fixture load failed: ${err}`,
        degradedReason: 'fixture_error',
      },
    });
    return;
  }

  try {
    const result = await postBatch(events);

    if (!result.ok) {
      throw new Error(`Ingestion API returned ${result.status}`);
    }

    setState({
      status: 'connected',
      backfillStatus: 'completed',
      incrementalSyncStatus: 'idle',
      lastAction: 'backfill',
      lastActionResult: {
        success: true,
        message: `Backfill complete: ${result.accepted} accepted, ${result.rejected} rejected`,
        batchResult: result,
      },
      sync: {
        recordsReceived: events.length,
        recordsAccepted: result.accepted,
        recordsRejected: result.rejected,
        recordsNormalized: result.accepted,
        recordsWritten: result.accepted,
        lastError: null,
        degradedReason: null,
        lastSyncAt: Date.now(),
      },
    });
  } catch (err) {
    setState({
      status: 'error',
      backfillStatus: 'failed',
      incrementalSyncStatus: 'idle',
      lastAction: 'backfill',
      lastActionResult: { success: false, message: `Backfill failed: ${err}` },
      sync: {
        ...state.sync,
        lastError: `Backfill failed: ${err}`,
        degradedReason: 'ingestion_error',
      },
    });
  }
}

export async function triggerIncrementalSync(): Promise<void> {
  if (!state.provider) {
    setState({
      lastAction: 'incremental_sync',
      lastActionResult: { success: false, message: 'No provider connected — connect first' },
    });
    return;
  }

  setState({
    status: 'syncing',
    incrementalSyncStatus: 'running' as IncrementalSyncStatus,
    lastAction: 'incremental_sync',
    lastActionResult: null,
  });

  // Prove the incremental sync started via the @aether/web SDK.
  sdk.trackConnectorEvent('connector.sync_start', {
    provider: state.provider,
    syncType: 'incremental',
  });
  await sdk.flushConnectorEvents().catch(() => {});

  // Build a small incremental batch (simulate a single new event).
  let events: unknown[];
  try {
    if (state.provider === 'stripe') {
      events = [buildPaymentSucceededEvent(`incremental_${Date.now()}`)];
    } else if (state.provider === 'shopify') {
      events = [buildShopifyOrderEvent(`ord_incr_${Date.now()}`, 'cust_incr', 'prod_incr')];
    } else {
      events = [buildEmailEvent(
        { type: 'click', email: 'user@example.com', campaignId: 'camp_001', timestamp: 1726000002000, metadata: { link: 'https://example.com/offer' } },
        'click'
      )];
    }
  } catch (err) {
    setState({
      status: 'error',
      lastAction: 'incremental_sync',
      lastActionResult: { success: false, message: `Incremental sync failed: ${err}` },
    });
    return;
  }

  try {
    const result = await postBatch(events);

    if (!result.ok) {
      throw new Error(`Ingestion API returned ${result.status}`);
    }

    setState({
      status: 'connected',
      incrementalSyncStatus: 'completed',
      lastAction: 'incremental_sync',
      lastActionResult: {
        success: true,
        message: `Incremental sync complete: ${result.accepted} accepted, ${result.rejected} rejected`,
        batchResult: result,
      },
      sync: {
        recordsReceived: state.sync.recordsReceived + events.length,
        recordsAccepted: state.sync.recordsAccepted + result.accepted,
        recordsRejected: state.sync.recordsRejected + result.rejected,
        recordsNormalized: state.sync.recordsNormalized + result.accepted,
        recordsWritten: state.sync.recordsWritten + result.accepted,
        lastError: null,
        degradedReason: null,
        lastSyncAt: Date.now(),
      },
    });
  } catch (err) {
    setState({
      status: 'error',
      incrementalSyncStatus: 'failed',
      lastAction: 'incremental_sync',
      lastActionResult: { success: false, message: `Incremental sync failed: ${err}` },
      sync: {
        ...state.sync,
        lastError: `Incremental sync failed: ${err}`,
        degradedReason: 'ingestion_error',
      },
    });
  }
}

export async function replayWebhook(): Promise<void> {
  setState({
    webhookStatus: 'replaying' as WebhookStatus,
    lastAction: 'replay_webhook',
    lastActionResult: null,
  });

  // Prove the webhook replay started via the @aether/web SDK.
  sdk.trackConnectorEvent('connector.webhook_replay', {
    provider: state.provider ?? 'stripe',
    eventType: 'checkout.session.completed',
  });
  await sdk.flushConnectorEvents().catch(() => {});

  // Load the raw Stripe fixture as the "webhook payload" and show it.
  const rawPayload = {
    platform: 'stripe',
    account_id: 'acct_1234567890',
    events: [
      {
        id: 'evt_1',
        type: 'checkout.session.completed',
        created: 1705315800,
        data: {
          object: {
            amount_total: 9999,
            currency: 'usd',
            customer: 'cus_123',
            customer_email: 'payer@example.com',
          },
        },
      },
    ],
  };

  setState({ rawPayload, showRawPayload: true });

  // Build a normalized event from the webhook payload and POST it.
  const events = [
    {
      event_id: 'evt_1',
      event_type: 'checkout.session.completed',
      timestamp: new Date(1705315800 * 1000).toISOString(),
      source: 'stripe',
      data: {
        amount_cents: 9999,
        currency: 'usd',
        customer_id: 'cus_123',
        customer_email: 'payer@example.com',
      },
    },
  ];

  try {
    const result = await postBatch(events);

    if (!result.ok) {
      throw new Error(`Ingestion API returned ${result.status}`);
    }

    setState({
      webhookStatus: 'completed',
      backfillStatus: 'idle',
      incrementalSyncStatus: 'idle',
      lastAction: 'replay_webhook',
      lastActionResult: {
        success: true,
        message: `Webhook replayed: ${events.length} event(s) sent`,
        batchResult: result,
      },
      showRawPayload: false,
    });
  } catch (err) {
    setState({
      webhookStatus: 'failed',
      backfillStatus: 'idle',
      incrementalSyncStatus: 'idle',
      lastAction: 'replay_webhook',
      lastActionResult: { success: false, message: `Webhook replay failed: ${err}` },
      sync: {
        ...state.sync,
        lastError: `Webhook replay failed: ${err}`,
        degradedReason: 'webhook_error',
      },
    });
  }
}

export function simulateTokenExpiration(): void {
  setState({
    status: 'error',
    credentialStatus: 'expired',
    tokenRefreshStatus: 'expired',
    lastAction: 'simulate_token_expiration',
    lastActionResult: { success: true, message: 'Token expiration simulated' },
    sync: {
      ...state.sync,
      lastError: 'Token expired (simulated)',
      degradedReason: 'credential_expired',
    },
  });
  // Emit SDK event for the token expiration
  sdk.trackConnectorEvent('connector.token_expired', {
    provider: state.provider,
    reason: 'simulated',
  });
  sdk.flushConnectorEvents().catch(() => {});
}

export function simulateProviderError(): void {
  setState({
    status: 'error',
    credentialStatus: 'invalid',
    tokenRefreshStatus: 'valid',
    lastAction: 'simulate_provider_error',
    lastActionResult: { success: true, message: 'Provider error simulated' },
    sync: {
      ...state.sync,
      lastError: 'Provider returned 503 (simulated)',
      degradedReason: 'provider_error',
    },
  });
  // Emit SDK event for the provider error
  sdk.trackConnectorEvent('connector.provider_error', {
    provider: state.provider,
    reason: 'simulated_503',
  });
  sdk.flushConnectorEvents().catch(() => {});
}

export function viewRawPayload(): void {
  // Show the raw fixture payload for the currently selected provider.
  let payload: unknown;
  try {
    if (state.provider === 'stripe') {
      payload = {
        platform: 'stripe',
        account_id: 'acct_1234567890',
        events: [
          {
            id: 'evt_1',
            type: 'checkout.session.completed',
            created: 1705315800,
            data: {
              object: {
                amount_total: 9999,
                currency: 'usd',
                customer: 'cus_123',
                customer_email: 'payer@example.com',
              },
            },
          },
        ],
      };
    } else if (state.provider === 'shopify') {
      payload = {
        platform: 'shopify',
        shop_id: 'shop-001',
        orders: [
          {
            order_id: 'order-1001',
            customer: { id: 'cust-1', email: 'buyer@example.com' },
            total_price: '49.99',
            currency: 'USD',
            created_at: '2025-01-15T10:30:00Z',
            line_items: [
              { product_id: 'prod-1', title: 'Widget', quantity: 2, price: '24.99' },
            ],
          },
        ],
      };
    } else {
      payload = {
        platform: 'email',
        provider: 'sendgrid',
        messages: [
          {
            msg_id: 'msg-1',
            from: 'noreply@example.com',
            to: ['user@example.com'],
            subject: 'Welcome!',
            event: 'delivered',
            timestamp: '2025-01-15T10:30:00Z',
          },
        ],
      };
    }
  } catch {
    payload = { error: 'Failed to load raw payload' };
  }

  setState({ rawPayload: payload, showRawPayload: true, showNormalizedPayload: false, showGraphWrites: false });
}

export function viewNormalizedPayload(): void {
  // Show what the normalized output would look like for the current provider.
  let payload: unknown;
  try {
    if (state.provider === 'stripe') {
      payload = {
        platform: 'stripe',
        account_id: 'acct_1234567890',
        normalized_events: [
          {
            event_id: 'evt_1',
            event_type: 'checkout.session.completed',
            timestamp: '2025-01-15T10:30:00.000Z',
            amount_cents: 9999,
            currency: 'usd',
            customer_id: 'cus_123',
            customer_email: 'payer@example.com',
          },
        ],
      };
    } else if (state.provider === 'shopify') {
      payload = {
        platform: 'shopify',
        shop_id: 'shop-001',
        normalized_orders: [
          {
            order_id: 'order-1001',
            customer_id: 'cust-1',
            customer_email: 'buyer@example.com',
            total_value: 49.99,
            currency: 'USD',
            timestamp: '2025-01-15T10:30:00.000Z',
            items: [
              { product_id: 'prod-1', name: 'Widget', quantity: 2, unit_price: 24.99 },
            ],
          },
        ],
      };
    } else {
      payload = {
        platform: 'email',
        provider: 'sendgrid',
        normalized_messages: [
          {
            message_id: 'msg-1',
            sender: 'noreply@example.com',
            recipient: 'user@example.com',
            subject: 'Welcome!',
            event_type: 'delivered',
            timestamp: '2025-01-15T10:30:00.000Z',
          },
        ],
      };
    }
  } catch {
    payload = { error: 'Failed to load normalized payload' };
  }

  setState({ normalizedPayload: payload, showNormalizedPayload: true, showRawPayload: false, showGraphWrites: false });
}

export function viewGraphWrites(): void {
  const writes = buildGraphWrites();
  setState({ graphWrites: writes, showGraphWrites: true, showRawPayload: false, showNormalizedPayload: false });
}

export function closeModal(modal: 'raw' | 'normalized' | 'graph'): void {
  setState({
    showRawPayload: modal !== 'raw' ? state.showRawPayload : false,
    showNormalizedPayload: modal !== 'normalized' ? state.showNormalizedPayload : false,
    showGraphWrites: modal !== 'graph' ? state.showGraphWrites : false,
  });
}

export function openProviderSelector(): void {
  setState({ providerSelectorOpen: true });
}

export function closeProviderSelector(): void {
  setState({ providerSelectorOpen: false });
}
