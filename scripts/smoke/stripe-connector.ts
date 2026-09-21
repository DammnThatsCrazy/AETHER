/**
 * FPS-061: Smoke test the Stripe connector against staging.
 *
 * AETHER / Functionality Proof Spine (FPS)
 * Ticket: FPS-061
 * Status: implemented
 *
 * - Reads STRIPE_SECRET_KEY (Stripe test mode secret, e.g. sk_test_...).
 * - Reads AETHER_API_URL and AETHER_API_KEY from env.
 * - Uses the Stripe test API to create a test customer, payment intent,
 *   and refund.
 * - POSTs each Stripe event as a normalized batch to the Aether ingestion
 *   API (POST /v1/batch).
 * - Exits 0 on success, 1 on failure. Skips if STRIPE_SECRET_KEY is missing.
 */

import https from 'node:https';
import { URL, URLSearchParams } from 'node:url';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getEnv(name: string): string | undefined {
  return process.env[name];
}

function requireEnv(name: string): string {
  const value = getEnv(name);
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function stripBearer(token: string): string {
  return token.replace(/^Bearer\s+/i, '');
}

/** Build an Authorization header value for the Aether API. */
function aetherAuth(): string {
  const raw = requireEnv('AETHER_API_KEY');
  return `Bearer ${stripBearer(raw)}`;
}

/** Absolute URL to the Aether ingestion endpoint. */
function aetherBaseUrl(): string {
  let raw = requireEnv('AETHER_API_URL');
  // Strip trailing slash so pathname concatenation is predictable.
  raw = raw.replace(/\/+$/, '');
  return raw;
}

/** POST JSON to the Aether ingestion API and return the parsed response. */
function postBatch(events: unknown[]): Promise<{
  ok: boolean;
  status: number;
  body: unknown;
}> {
  const base = aetherBaseUrl();
  const path = '/v1/batch';
  const url = new URL(path, base);

  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ events });
    const options: https.RequestOptions = {
      hostname: url.hostname,
      port: url.port || 443,
      path: url.pathname + url.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: aetherAuth(),
        'Content-Length': Buffer.byteLength(body),
      },
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(data);
        } catch {
          parsed = { raw: data };
        }
        const status = res.statusCode ?? 0;
        resolve({
          ok: status >= 200 && status < 300,
          status,
          body: parsed,
        });
      });
    });

    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

/** Pretty-print a result line. */
function logResult(label: string, ok: boolean, status: number, eventId: string): void {
  const symbol = ok ? '✓' : '✗';
  console.log(`[${symbol}] ${label} (status=${status}, event_id=${eventId})`);
}

// ---------------------------------------------------------------------------
// Stripe helpers (test mode only)
// ---------------------------------------------------------------------------

interface StripeResponse {
  id?: string;
  object?: string;
  error?: { message: string };
  [key: string]: unknown;
}

function stripeRequest(
  method: string,
  path: string,
  payload?: Record<string, string | number | boolean>
): Promise<StripeResponse> {
  const key = requireEnv('STRIPE_SECRET_KEY');
  if (!key.startsWith('sk_test_')) {
    throw new Error(
      'STRIPE_SECRET_KEY must be a Stripe test-mode secret key (sk_test_...)'
    );
  }
  // URL treats a leading slash as an absolute host path. Normalize it away so
  // every request remains under Stripe's versioned /v1 API prefix.
  const url = new URL(path.replace(/^\/+/, ''), 'https://api.stripe.com/v1/');
  return new Promise((resolve, reject) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(payload ?? {})) {
      params.set(key, String(value));
    }
    const body = params.toString();
    const options: https.RequestOptions = {
      hostname: url.hostname,
      port: 443,
      path: url.pathname + url.search,
      method,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        Authorization: `Bearer ${key}`,
        'Content-Length': Buffer.byteLength(body),
      },
    };
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.error) reject(new Error(parsed.error.message));
          else resolve(parsed);
        } catch {
          reject(
            new Error(`Stripe responded with non-JSON: ${data.slice(0, 200)}`)
          );
        }
      });
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

async function createStripeCustomer(): Promise<string> {
  const res = await stripeRequest('POST', '/customers', {
    email: 'fps-smoke-test@example.com',
    name: 'FPS Smoke Test Customer',
    description:
      'Created by FPS-061 stripe-connector smoke test',
  });
  if (!res.id) throw new Error('Stripe customer creation returned no id');
  console.log(`  Created Stripe customer: ${res.id}`);
  return res.id as string;
}

async function createStripePaymentIntent(
  customerId: string
): Promise<string> {
  const res = await stripeRequest('POST', '/payment_intents', {
    amount: 2000, // $20.00 USD
    currency: 'usd',
    customer: customerId,
    payment_method: 'pm_card_visa',
    description: 'FPS-061 smoke test payment intent',
    confirm: true,
  });
  if (!res.id) throw new Error('Stripe payment intent creation returned no id');
  if (res.status !== 'succeeded') {
    throw new Error(`Stripe payment intent did not succeed (status=${res.status})`);
  }
  console.log(`  Created Stripe payment intent: ${res.id} (status=${res.status})`);
  return res.id as string;
}

async function createStripeRefund(
  paymentIntentId: string
): Promise<string> {
  // Refunds are created against charges; find the charge from the PI.
  const piRes = await stripeRequest(
    'GET',
    `/payment_intents/${encodeURIComponent(paymentIntentId)}?expand[]=latest_charge`,
  );
  const latestCharge = piRes.latest_charge;
  const chargeId =
    typeof latestCharge === 'string'
      ? latestCharge
      : typeof latestCharge === 'object' && latestCharge !== null
        ? (latestCharge as { id?: string }).id
        : (piRes as { charges?: { data?: Array<{ id?: string }> } }).charges
            ?.data?.[0]?.id;
  if (!chargeId) throw new Error('No charge found for payment intent');

  const res = await stripeRequest('POST', '/refunds', {
    charge: chargeId,
    amount: 500, // $5.00 partial refund
    reason: 'requested_by_customer',
    description: 'FPS-061 smoke test refund',
  });
  if (!res.id) throw new Error('Stripe refund creation returned no id');
  console.log(`  Created Stripe refund: ${res.id}`);
  return res.id as string;
}

// ---------------------------------------------------------------------------
// Normalized event builders
// ---------------------------------------------------------------------------

interface NormalizedStripeEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  source: string;
  data: Record<string, unknown>;
}

function customerCreatedEvent(customerId: string): NormalizedStripeEvent {
  return {
    event_id: `evt_cust_${customerId}`,
    event_type: 'customer.created',
    timestamp: new Date().toISOString(),
    source: 'stripe',
    data: {
      customer_id: customerId,
      email: 'fps-smoke-test@example.com',
      name: 'FPS Smoke Test Customer',
    },
  };
}

function paymentSucceededEvent(
  paymentIntentId: string
): NormalizedStripeEvent {
  return {
    event_id: `evt_pay_${paymentIntentId}`,
    event_type: 'payment_intent.succeeded',
    timestamp: new Date().toISOString(),
    source: 'stripe',
    data: {
      payment_intent_id: paymentIntentId,
      amount: 2000,
      currency: 'usd',
      status: 'succeeded',
    },
  };
}

function refundCreatedEvent(refundId: string): NormalizedStripeEvent {
  return {
    event_id: `evt_ref_${refundId}`,
    event_type: 'refund.created',
    timestamp: new Date().toISOString(),
    source: 'stripe',
    data: {
      refund_id: refundId,
      amount: 500,
      currency: 'usd',
      reason: 'requested_by_customer',
      status: 'succeeded',
    },
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  console.log('[FPS-061] smoke:stripe-connector starting...');

  // --- Guard: skip if no Stripe key -----------------------------------------
  const stripeKey = getEnv('STRIPE_SECRET_KEY');
  if (!stripeKey) {
    console.log(
      '[FPS-061] smoke:stripe-connector: SKIP — STRIPE_SECRET_KEY not set.'
    );
    console.log(
      '[FPS-061] smoke:stripe-connector: Set STRIPE_SECRET_KEY=sk_test_... to run.'
    );
    console.log('[FPS-061] smoke:stripe-connector complete (skipped).');
    process.exit(0);
  }

  // --- Guard: required env for Aether API -----------------------------------
  try {
    requireEnv('AETHER_API_URL');
    requireEnv('AETHER_API_KEY');
  } catch (err) {
    console.error(`[FPS-061] smoke:stripe-connector: FAIL — ${err}`);
    process.exit(1);
  }

  const customerId = await createStripeCustomer();
  const paymentIntentId = await createStripePaymentIntent(customerId);
  const refundId = await createStripeRefund(paymentIntentId);

  // --- Build normalized batch ------------------------------------------------
  const events: NormalizedStripeEvent[] = [
    customerCreatedEvent(customerId),
    paymentSucceededEvent(paymentIntentId),
    refundCreatedEvent(refundId),
  ];

  console.log(
    `[FPS-061] smoke:stripe-connector: POSTing ${events.length} normalized events to Aether ingestion...`
  );

  const result = await postBatch(events);

  if (!result.ok) {
    console.error(
      `[FPS-061] smoke:stripe-connector: FAIL — ingestion API returned ${result.status}`
    );
    console.error(
      '[FPS-061] smoke:stripe-connector:',
      JSON.stringify(result.body, null, 2)
    );
    process.exit(1);
  }

  console.log(
    `[FPS-061] smoke:stripe-connector: ingestion API accepted batch (status=${result.status})`
  );
  console.log(
    '[FPS-061] smoke:stripe-connector:',
    JSON.stringify(result.body, null, 2)
  );

  // --- Per-event verification -------------------------------------------------
  const accepted = (result.body as { accepted?: number }).accepted;
  const rejected = (result.body as { rejected?: number }).rejected;

  if (accepted !== events.length) {
    console.error(
      `[FPS-061] smoke:stripe-connector: FAIL — expected ${events.length} accepted, got ${accepted}`
    );
    process.exit(1);
  }

  console.log(
    `[FPS-061] smoke:stripe-connector: All ${events.length} events accepted (${rejected} rejected).`
  );

  // --- Log per-event result --------------------------------------------------
  for (const evt of events) {
    logResult(
      `Stripe event ${evt.event_type}`,
      true,
      result.status,
      evt.event_id
    );
  }

  console.log('[FPS-061] smoke:stripe-connector complete.');
  process.exit(0);
}

main().catch((err) => {
  console.error('[FPS-061] smoke:stripe-connector: FAIL —', err);
  process.exit(1);
});
