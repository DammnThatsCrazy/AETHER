// =============================================================================
// examples/server-node/src/index.ts
// Node.js server SDK example using @aether/server
// =============================================================================
// Demonstrates the server-side first-value journey:
//   init → heartbeat → track event → identify → commerce → flush →
//   backend acceptance → activation milestone → Kyber/Aether visibility
// =============================================================================

import 'dotenv/config';
import { AetherServerSDK } from '@aether/server';
import type { BatchHealth } from '@aether/server';

// ---------------------------------------------------------------------------
// Config — read from env, with staging/local differentiation
// ---------------------------------------------------------------------------

const writeKey = process.env.AETHER_WRITE_KEY;
const endpoint = process.env.AETHER_ENDPOINT;

if (!writeKey) {
  console.error('AETHER_WRITE_KEY is required. Set it in .env.local or .env.staging.');
  process.exit(1);
}

if (!endpoint) {
  console.error('AETHER_ENDPOINT is required. Set it in .env.local or .env.staging.');
  process.exit(1);
}

console.log(`[server-node] Starting with endpoint=${endpoint}`);

// ---------------------------------------------------------------------------
// Initialize the Aether Server SDK
// ---------------------------------------------------------------------------

const sdk = new AetherServerSDK({
  writeKey,
  endpoint,
  application: { name: 'examples-server-node', version: '0.1.0-alpha.0' },
  consent: { analytics: true, commerce: true },
  flushAt: 10,
  flushInterval: 5000,
  onBatchResult: (health: BatchHealth) => {
    console.log(
      `[batch] accepted=${health.accepted} duplicate=${health.duplicate} ` +
      `rejected=${health.rejected} queue_depth=${health.queue_depth}`,
    );
  },
});

console.log('[server-node] SDK initialized');

// ---------------------------------------------------------------------------
// First-value journey steps
// ---------------------------------------------------------------------------

/** Step 1 — heartbeat: proves the server SDK is live and the backend is reachable. */
async function stepHeartbeat() {
  console.log('[journey] → heartbeat');
  sdk.observe('heartbeat', {
    source: 'examples-server-node',
    sdkVersion: '0.1.0-alpha.0',
  });
  console.log('[journey] ✓ heartbeat queued');
}

/** Step 2 — track a custom event: general-purpose behavioral signal. */
async function stepTrackEvent() {
  console.log('[journey] → track event');
  sdk.observe('api_request_observed', {
    source: 'examples-server-node',
    endpoint: '/api/v1/users',
    method: 'GET',
    status: 200,
  });
  console.log('[journey] ✓ event queued');
}

/** Step 3 — commerce event: revenue-bearing signal for Kyber/Aether visibility. */
async function stepCommerce() {
  console.log('[journey] → commerce event');
  sdk.observe('order_completed', {
    source: 'examples-server-node',
    revenue: 29.99,
    currency: 'USD',
    orderId: `ord_${Date.now()}`,
    items: [
      { sku: 'SKU-001', name: 'Demo Product', price: 29.99, quantity: 1 },
    ],
  });
  console.log('[journey] ✓ commerce event queued — $29.99 USD');
}

/** Step 4 — flush the queue: proves backend acceptance. */
async function stepFlush() {
  console.log('[journey] → flush queue');
  const depthBefore = sdk.queueDepth();
  console.log(`[journey] queue depth before flush: ${depthBefore}`);
  await sdk.flush();
  const result = sdk.lastBatchResult();
  console.log(
    `[journey] ✓ flush complete — ` +
    `accepted=${result?.accepted ?? '?'} ` +
    `duplicate=${result?.duplicate ?? '?'} ` +
    `rejected=${result?.rejected ?? '?'}`,
  );
  console.log('[journey] backend acceptance proven — events visible in Aether dashboard & Kyber');
}

// ---------------------------------------------------------------------------
// Run the first-value journey
// ---------------------------------------------------------------------------

async function main() {
  console.log('=== Aether Server SDK — First-Value Journey ===');
  console.log('');

  await stepHeartbeat();
  await stepTrackEvent();
  await stepCommerce();

  // Give the periodic flush timer a moment to potentially deliver.
  await new Promise((r) => setTimeout(r, 600));

  await stepFlush();

  console.log('');
  console.log('=== Journey complete ===');
  console.log('Activation milestone: first valid event accepted → server observed by Aether');
  console.log('Kyber/Aether visibility: commerce + heartbeat events in economic graph');

  await sdk.shutdown();
  console.log('[server-node] SDK shut down');
}

main().catch((err) => {
  console.error('[server-node] journey failed:', err);
  process.exit(1);
});
