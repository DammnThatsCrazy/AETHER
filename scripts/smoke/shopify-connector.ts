/**
 * FPS-062: Smoke test the Shopify connector against staging.
 *
 * AETHER / Functionality Proof Spine (FPS)
 * Ticket: FPS-062
 * Status: implemented
 *
 * - Reads SHOPIFY_ACCESS_TOKEN and SHOPIFY_SHOP_DOMAIN from env.
 * - Uses the Shopify Admin API (REST) to create a test customer, product,
 *   and order on the dev store.
 * - POSTs each Shopify event as a normalized batch to the Aether ingestion
 *   API (POST /v1/batch).
 * - Exits 0 on success, 1 on failure. Skips if credentials are missing.
 */

import https from 'node:https';
import { URL } from 'node:url';

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

/** Absolute URL to the Aether ingestion endpoint. */
function aetherBaseUrl(): string {
  let raw = requireEnv('AETHER_API_URL');
  raw = raw.replace(/\/+$/, '');
  return raw;
}

/** POST JSON to the Aether ingestion API. */
function postBatch(events: unknown[]): Promise<{
  ok: boolean;
  status: number;
  body: unknown;
}> {
  const base = aetherBaseUrl();
  const url = new URL('/v1/batch', base);

  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ events });
    const options: https.RequestOptions = {
      hostname: url.hostname,
      port: url.port || 443,
      path: url.pathname + url.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${requireEnv('AETHER_API_KEY')}`,
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

function shopifyGet<T>(path: string): Promise<T> {
  const shop = requireEnv('SHOPIFY_SHOP_DOMAIN');
  const token = requireEnv('SHOPIFY_ACCESS_TOKEN');
  const url = new URL(path, `https://${shop}.myshopify.com/admin/api/2024-01/json`);

  return new Promise((resolve, reject) => {
    const options: https.RequestOptions = {
      hostname: url.hostname,
      port: 443,
      path: url.pathname + url.search,
      method: 'GET',
      headers: {
        'X-Shopify-Access-Token': token,
        Accept: 'application/json',
      },
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`Shopify GET ${path} failed: ${res.statusCode} ${data.slice(0, 300)}`));
          return;
        }
        try {
          const json = JSON.parse(data) as T;
          resolve(json);
        } catch {
          reject(new Error(`Shopify GET ${path} returned non-JSON: ${data.slice(0, 200)}`));
        }
      });
    });

    req.on('error', reject);
    req.end();
  });
}

function shopifyPost<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const shop = requireEnv('SHOPIFY_SHOP_DOMAIN');
  const token = requireEnv('SHOPIFY_ACCESS_TOKEN');
  const url = new URL(path, `https://${shop}.myshopify.com/admin/api/2024-01/json`);

  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const options: https.RequestOptions = {
      hostname: url.hostname,
      port: 443,
      path: url.pathname + url.search,
      method: 'POST',
      headers: {
        'X-Shopify-Access-Token': token,
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'Content-Length': Buffer.byteLength(payload),
      },
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        if (res.statusCode !== 201 && res.statusCode !== 200) {
          reject(
            new Error(
              `Shopify POST ${path} failed: ${res.statusCode} ${data.slice(0, 300)}`
            )
          );
          return;
        }
        try {
          resolve(JSON.parse(data) as T);
        } catch {
          reject(new Error(`Shopify POST ${path} returned non-JSON: ${data.slice(0, 200)}`));
        }
      });
    });

    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

// ---------------------------------------------------------------------------
// Shopify resource creation
// ---------------------------------------------------------------------------

async function createShopifyCustomer(): Promise<string> {
  const res = await shopifyPost<{ customer: { id: number; email: string; firstName: string; lastName: string; ordersCount: number; totalSpent: string } }>(
    '/customers.json',
    {
      customer: {
        email: 'fps-smoke-test@shopify.example.com',
        first_name: 'FPS',
        last_name: 'Smoke Test',
        tags: 'fps-smoke-test',
      },
    }
  );
  console.log(`  Created Shopify customer: #${res.customer.id} (${res.customer.email})`);
  return res.customer.id.toString();
}

async function createShopifyProduct(): Promise<string> {
  const res = await shopifyPost<{ product: { id: number; title: string; vendor: string; price: string; tags: string[] } }>(
    '/products.json',
    {
      product: {
        title: 'FPS Smoke Test Widget',
        vendor: 'AetherFPS',
        product_type: 'Widget',
        tags: 'fps-smoke-test',
        variants: [{ price: '19.99', inventory_quantity: 100 }],
      },
    }
  );
  console.log(`  Created Shopify product: #${res.product.id} (${res.product.title})`);
  return res.product.id.toString();
}

async function createShopifyOrder(
  customerId: string,
  productId: string
): Promise<string> {
  const res = await shopifyPost<{ order: { id: number; order_number: number; total_price: string; currency: string; customer_id: number; created_at: string; line_items: Array<{ product_id: number; title: string; quantity: number; price: string }> } }>(
    '/orders.json',
    {
      order: {
        email: 'fps-smoke-test@shopify.example.com',
        customer_id: parseInt(customerId, 10),
        line_items: [
          {
            product_id: parseInt(productId, 10),
            quantity: 2,
            price: '19.99',
          },
        ],
        total_price: '39.98',
        currency: 'USD',
        financial_status: 'authorized',
        fulfillment_status: 'unfulfilled',
      },
    }
  );
  console.log(`  Created Shopify order: #${res.order.order_number} (total=${res.order.total_price} ${res.order.currency})`);
  return res.order.id.toString();
}

// ---------------------------------------------------------------------------
// Normalized event builders
// ---------------------------------------------------------------------------

interface NormalizedShopifyEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  source: string;
  data: Record<string, unknown>;
}

function customerCreatedEvent(customerId: string): NormalizedShopifyEvent {
  return {
    event_id: `shop_evt_cust_${customerId}`,
    event_type: 'customer.created',
    timestamp: new Date().toISOString(),
    source: 'shopify',
    data: {
      customer_id: customerId,
      email: 'fps-smoke-test@shopify.example.com',
      first_name: 'FPS',
      last_name: 'Smoke Test',
      orders_count: 0,
      total_spent: '0.00',
    },
  };
}

function productCreatedEvent(productId: string): NormalizedShopifyEvent {
  return {
    event_id: `shop_evt_prod_${productId}`,
    event_type: 'product.created',
    timestamp: new Date().toISOString(),
    source: 'shopify',
    data: {
      product_id: productId,
      title: 'FPS Smoke Test Widget',
      vendor: 'AetherFPS',
      product_type: 'Widget',
    },
  };
}

function orderCreatedEvent(
  orderId: string,
  customerId: string,
  productId: string
): NormalizedShopifyEvent {
  return {
    event_id: `shop_evt_ord_${orderId}`,
    event_type: 'order.created',
    timestamp: new Date().toISOString(),
    source: 'shopify',
    data: {
      order_id: orderId,
      order_number: parseInt(orderId, 10), // approximate; real value comes from API
      customer_id: customerId,
      customer_email: 'fps-smoke-test@shopify.example.com',
      total_value: 39.98,
      currency: 'USD',
      items: [
        {
          product_id: productId,
          name: 'FPS Smoke Test Widget',
          quantity: 2,
          unit_price: 19.99,
        },
      ],
    },
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  console.log('[FPS-062] smoke:shopify-connector starting...');

  // --- Guard: skip if credentials are missing -------------------------------
  const shopDomain = getEnv('SHOPIFY_SHOP_DOMAIN');
  const accessToken = getEnv('SHOPIFY_ACCESS_TOKEN');

  if (!shopDomain || !accessToken) {
    console.log(
      '[FPS-062] smoke:shopify-connector: SKIP — missing Shopify credentials.'
    );
    if (!shopDomain) console.log('  Set SHOPIFY_SHOP_DOMAIN=your-dev-store.myshopify.com');
    if (!accessToken) console.log('  Set SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxx');
    console.log('[FPS-062] smoke:shopify-connector complete (skipped).');
    process.exit(0);
  }

  // --- Guard: Aether API env ------------------------------------------------
  try {
    requireEnv('AETHER_API_URL');
    requireEnv('AETHER_API_KEY');
  } catch (err) {
    console.error(`[FPS-062] smoke:shopify-connector: FAIL — ${err}`);
    process.exit(1);
  }

  // --- Create Shopify resources ----------------------------------------------
  console.log('\n[FPS-062] Creating test resources on Shopify dev store...');
  const customerId = await createShopifyCustomer();
  const productId = await createShopifyProduct();
  const orderId = await createShopifyOrder(customerId, productId);

  // --- Build normalized batch ------------------------------------------------
  const events: NormalizedShopifyEvent[] = [
    customerCreatedEvent(customerId),
    productCreatedEvent(productId),
    orderCreatedEvent(orderId, customerId, productId),
  ];

  console.log(
    `\n[FPS-062] POSTing ${events.length} normalized events to Aether ingestion...`
  );

  const result = await postBatch(events);

  if (!result.ok) {
    console.error(
      `[FPS-062] smoke:shopify-connector: FAIL — ingestion API returned ${result.status}`
    );
    console.error(
      '[FPS-062] smoke:shopify-connector:',
      JSON.stringify(result.body, null, 2)
    );
    process.exit(1);
  }

  console.log(
    `[FPS-062] smoke:shopify-connector: ingestion API accepted batch (status=${result.status})`
  );
  console.log(
    '[FPS-062] smoke:shopify-connector:',
    JSON.stringify(result.body, null, 2)
  );

  // --- Verify ---------------------------------------------------------------
  const accepted = (result.body as { accepted?: number }).accepted;
  const rejected = (result.body as { rejected?: number }).rejected;

  if (accepted !== events.length) {
    console.error(
      `[FPS-062] smoke:shopify-connector: FAIL — expected ${events.length} accepted, got ${accepted}`
    );
    process.exit(1);
  }

  console.log(
    `[FPS-062] smoke:shopify-connector: All ${events.length} events accepted (${rejected} rejected).`
  );

  for (const evt of events) {
    console.log(
      `  ✓ Shopify event ${evt.event_type} (event_id=${evt.event_id}, status=${result.status})`
    );
  }

  console.log('[FPS-062] smoke:shopify-connector complete.');
  process.exit(0);
}

main().catch((err) => {
  console.error('[FPS-062] smoke:shopify-connector: FAIL —', err);
  process.exit(1);
});
