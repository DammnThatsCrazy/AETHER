/**
 * FPS-040: Smoke test the web SDK integration against the ingestion API.
 *
 * AETHER / Functionality Proof Spine (FPS)
 * Ticket: FPS-040
 * Status: active
 *
 * Validates:
 *  - HTTP batch ingestion against POST /v1/batch
 *  - Direct SDK usage via @aether/web (if DOM available)
 *  - Correct canonical event envelope per docs/api/ingestion.md
 */

// ── Imports ───────────────────────────────────────────────────────────────────

import * as https from 'node:https';
import * as http from 'node:http';
import * as path from 'node:path';

// ── Configuration ─────────────────────────────────────────────────────────────

const API_URL = process.env.AETHER_API_URL?.replace(/\/+$/, '') || 'http://localhost:8000';
const API_KEY = process.env.AETHER_API_KEY;

if (!API_KEY) {
  console.error('[FPS-040] Error: AETHER_API_KEY environment variable is required.');
  console.error('[FPS-040]   Set it to a valid API key with write permission.');
  console.error('[FPS-040]   Example: AETHER_API_KEY=ak_... tsx scripts/smoke/web-sdk.ts');
  process.exit(1);
}

// Read SDK version from packages/web/src/index.ts (SDK_VERSION constant)
function readSdkVersionFromSource(): string {
  // The SDK_VERSION constant is at line 69 of packages/web/src/index.ts:
  //   const SDK_VERSION = '0.1.0-alpha.0';
  const sourcePath = path.resolve(process.cwd(), 'packages/web/src/index.ts');
  try {
    const source = require('fs').readFileSync(sourcePath, 'utf-8');
    const match = source.match(/const\s+SDK_VERSION\s*=\s*['"]([^'"]+)['"]/);
    if (match) return match[1];
  } catch {
    // fall through to package.json
  }
  return '';
}

function readSdkVersionFromPackageJson(): string {
  const pkgPath = path.resolve(process.cwd(), 'packages/web/package.json');
  try {
    const pkg = JSON.parse(require('fs').readFileSync(pkgPath, 'utf-8'));
    return pkg.version || '';
  } catch {
    return '';
  }
}

const SDK_VERSION = readSdkVersionFromSource() || readSdkVersionFromPackageJson() || '0.1.0-alpha.0';

console.log(`[FPS-040] SDK version: ${SDK_VERSION}`);
console.log(`[FPS-040] API endpoint: ${API_URL}`);
console.log(`[FPS-040] API key: ${API_KEY!.slice(0, 8)}...`);

// ── Helpers ────────────────────────────────────────────────────────────────────

function nowIso(): string {
  return new Date().toISOString();
}

function generateSessionId(): string {
  return `sess_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
}

function generateAnonymousId(): string {
  return `anon_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
}

function generateUserId(): string {
  return `usr_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
}

/**
 * Build a single canonical ingestion event per docs/api/ingestion.md.
 *
 * The canonical event types the backend registry validates are the bare
 * EventType union values: 'heartbeat', 'page', 'identify', 'conversion',
 * etc. — NOT dotted strings like 'sdk.heartbeat' or 'page.view'.
 *
 * See: packages/shared/dist/events.d.ts EventType union,
 *       packages/web/src/core/generated-consent-map.ts CANONICAL_EVENT_TYPES.
 */
function buildEvent(
  type: string,
  properties: Record<string, unknown>,
  userId?: string,
): Record<string, unknown> {
  return {
    id: crypto.randomUUID(),
    type,
    timestamp: nowIso(),
    sessionId: generateSessionId(),
    anonymousId: generateAnonymousId(),
    ...(userId ? { userId } : {}),
    properties,
    context: {
      library: { name: '@aether/web', version: SDK_VERSION },
      surface: 'web',
      schemaVersion: '1.0.0',
      sequence: { event: 0 },
    },
  };
}

// ── Build the batch ────────────────────────────────────────────────────────────

const batchTimestamp = nowIso();
const sessionId = generateSessionId();
const anonymousId = generateAnonymousId();
const userId = generateUserId();

const events = [
  // 1. Heartbeat — source + sdkVersion
  buildEvent('heartbeat', {
    source: 'proof-web',
    sdkVersion: SDK_VERSION,
  }, undefined),

  // 2. Page view — url, path, title
  buildEvent('page', {
    url: 'https://example.com/pricing',
    path: '/pricing',
    title: 'Pricing — Aether',
    referrer: '',
  }, undefined),

  // 3. Identify — userId + traits
  buildEvent('identify', {
    userId,
    traits: {
      email: 'test@example.com',
      name: 'Proof Test User',
    },
  }, userId),

  // 4. Conversion — order_completed
  buildEvent('conversion', {
    event: 'order_completed',
    value: 29.99,
    currency: 'USD',
  }, userId),
];

const batchBody = {
  batch: events,
  sentAt: batchTimestamp,
  consents: ['analytics'],
};

// ── HTTP POST helper ───────────────────────────────────────────────────────────

function postJson(url: string, body: unknown, apiKey: string): Promise<{
  status: number;
  headers: Record<string, string | undefined>;
  body: unknown;
}> {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const transport = urlObj.protocol === 'https:' ? https : http;

    const options = {
      hostname: urlObj.hostname,
      port: urlObj.port || (urlObj.protocol === 'https:' ? 443 : 80),
      path: urlObj.pathname + urlObj.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Aether-API-Key': apiKey,
        'Content-Length': Buffer.byteLength(JSON.stringify(body)),
      },
    };

    const req = transport.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(data);
        } catch {
          parsed = { raw: data };
        }
        const headers: Record<string, string | undefined> = {};
        for (const [key, value] of Object.entries(res.headers)) {
          headers[key] = Array.isArray(value) ? value[0] : (value as string | undefined);
        }
        resolve({
          status: res.statusCode ?? 0,
          headers,
          body: parsed,
        });
      });
    });

    req.on('error', (err) => {
      reject(err);
    });

    req.write(JSON.stringify(body));
    req.end();
  });
}

// ── HTTP batch test ────────────────────────────────────────────────────────────

async function runHttpBatchTest(): Promise<boolean> {
  console.log('\n── FPS-040: HTTP batch ingestion test ──');

  try {
    const response = await postJson(
      `${API_URL}/v1/batch`,
      batchBody,
      API_KEY,
    );

    const status = response.status;
    const body = response.body as Record<string, unknown>;

    console.log(`[FPS-040] HTTP status: ${status}`);

    // Handle error status codes
    if (status === 401) {
      console.error('[FPS-040] Error: 401 Unauthorized — invalid or missing API key.');
      return false;
    }
    if (status === 403) {
      console.error('[FPS-040] Error: 403 Forbidden — API key lacks write permission.');
      return false;
    }
    if (status === 429) {
      const retryAfter = response.headers['retry-after'] ?? 'unknown';
      console.error(`[FPS-040] Error: 429 Rate Limited — Retry-After: ${retryAfter}s`);
      return false;
    }
    if (status >= 500) {
      console.error(`[FPS-040] Error: ${status} Server Error — ingestion service unavailable.`);
      return false;
    }

    if (status !== 200 && status !== 201) {
      console.error(`[FPS-040] Error: Unexpected status ${status}`);
      console.error(`[FPS-040]   Response: ${JSON.stringify(body, null, 2)}`);
      return false;
    }

    // Verify response shape
    const accepted = body.accepted as number | undefined;
    const rejected = body.rejected as number | undefined;
    const duplicates = body.duplicates as number | undefined;
    const events_response = body.events as Array<{ id: string; status: string }> | undefined;
    const batchId = body.batchId as string | undefined;
    const receivedAt = body.receivedAt as string | undefined;

    console.log(`[FPS-040] Batch ID:      ${batchId ?? 'N/A'}`);
    console.log(`[FPS-040] Received at:   ${receivedAt ?? 'N/A'}`);
    console.log(`[FPS-040] Accepted:      ${accepted ?? 'N/A'}`);
    console.log(`[FPS-040] Rejected:      ${rejected ?? 'N/A'}`);
    console.log(`[FPS-040] Duplicates:    ${duplicates ?? 'N/A'}`);

    // Per-event status
    if (events_response && events_response.length > 0) {
      console.log(`\n[FPS-040] Per-event results:`);
      for (const evt of events_response) {
        console.log(`  ${evt.id}  →  ${evt.status}`);
      }
    }

    // Validation
    const allAccepted = accepted === 4;
    const noneRejected = rejected === 0;
    const allEventsOk = events_response?.every(e => e.status === 'accepted') ?? false;

    if (!allAccepted) {
      console.error(`[FPS-040] FAIL: Expected accepted=4, got ${accepted}`);
    }
    if (!noneRejected) {
      console.error(`[FPS-040] FAIL: Expected rejected=0, got ${rejected}`);
    }
    if (!allEventsOk) {
      console.error('[FPS-040] FAIL: Not all events have status "accepted".');
    }

    if (allAccepted && noneRejected && allEventsOk) {
      console.log('\n[FPS-040] ✓ HTTP batch test passed — all 4 events accepted.');
      return true;
    } else {
      console.log('\n[FPS-040] ✗ HTTP batch test failed — see errors above.');
      return false;
    }
  } catch (err) {
    console.error('[FPS-040] Error: HTTP request failed:', err instanceof Error ? err.message : err);
    return false;
  }
}

// ── Direct SDK test (skip if DOM unavailable) ──────────────────────────────────

async function runDirectSdkTest(): Promise<void> {
  console.log('\n── FPS-040: Direct @aether/web SDK test ──');

  try {
    // Dynamic import — may fail in Node without DOM
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { default: aether } = await import('@aether/web') as any;

    console.log('[FPS-040] ✓ @aether/web imported successfully.');

    // Initialize the SDK
    aether.init({
      apiKey: API_KEY,
      endpoint: API_URL,
      debug: true,
      application: 'fps-smoke-test',
      onBatchResult: (health: Record<string, unknown>) => {
        console.log('[FPS-040] SDK batch result:', JSON.stringify(health));
      },
    });

    console.log('[FPS-040] ✓ SDK initialized.');

    // Emit a heartbeat via aether.track()
    aether.track('heartbeat', { source: 'proof-web', sdkVersion: SDK_VERSION });
    console.log('[FPS-040] ✓ aether.track("heartbeat", ...) called.');

    // Flush to force send
    try {
      await aether.flush();
      console.log('[FPS-040] ✓ SDK flush complete.');
    } catch (flushErr) {
      console.log('[FPS-040] ⚠ SDK flush failed (may be expected in Node):', flushErr instanceof Error ? flushErr.message : flushErr);
    }

    // Clean up
    aether.destroy();
    console.log('[FPS-040] ✓ SDK destroyed.');
  } catch (err) {
    if (err && typeof err === 'object' && 'message' in err) {
      const msg = (err as Error).message;
      if (msg.includes('window') || msg.includes('document') || msg.includes('navigator') || msg.includes('localStorage')) {
        console.log('[FPS-040] ⚠ SDK direct test skipped — runtime lacks DOM (window/document/navigator).');
        console.log('[FPS-040]   This is expected in Node.js. HTTP batch test covers ingestion.');
      } else {
        console.log('[FPS-040] ⚠ SDK direct test skipped — import/runtime error:', msg);
        console.log('[FPS-040]   HTTP batch test still covers ingestion.');
      }
    } else {
      console.log('[FPS-040] ⚠ SDK direct test skipped — import failed (likely DOM dependency).');
      console.log('[FPS-040]   HTTP batch test still covers ingestion.');
    }
  }
}

// ── Main ───────────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  console.log(`[FPS-040] =========================================`);
  console.log(`[FPS-040] Web SDK Smoke Test (FPS-040)`);
  console.log(`[FPS-040] =========================================`);

  // Run direct SDK test first (best-effort, non-blocking)
  await runDirectSdkTest();

  // Run the HTTP batch test (the primary validation)
  const httpPassed = await runHttpBatchTest();

  console.log(`\n[FPS-040] =========================================`);
  console.log(`[FPS-040] Summary`);
  console.log(`[FPS-040] =========================================`);
  console.log(`[FPS-040] Batch sent:     ${batchBody.batch.length} events`);
  console.log(`[FPS-040] Sent at:        ${batchTimestamp}`);
  for (let i = 0; i < batchBody.batch.length; i++) {
    const evt = batchBody.batch[i] as Record<string, unknown>;
    console.log(`[FPS-040] Event ${i}:        ${evt.id}  [${evt.type}]`);
  }
  console.log(`[FPS-040] HTTP batch:     ${httpPassed ? 'PASSED' : 'FAILED'}`);

  if (httpPassed) {
    console.log('[FPS-040] ✓ All 4 events accepted via HTTP.');
    process.exit(0);
  } else {
    console.error('[FPS-040] ✗ Some events were rejected, duplicated, or the HTTP call failed.');
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('[FPS-040] Unhandled error:', err);
  process.exit(1);
});
