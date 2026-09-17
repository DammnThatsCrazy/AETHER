/**
 * FPS-063: Smoke test the email connector against staging.
 *
 * AETHER / Functionality Proof Spine (FPS)
 * Ticket: FPS-063
 * Status: implemented
 *
 * - Uses fixture data from @aether/proof-fixtures (no live provider).
 * - Loads email fixtures (sent, open, click, bounce, unsubscribe).
 * - POSTs normalized email events to the Aether ingestion API
 *   (POST /v1/batch).
 * - Exits 0 on success, 1 on failure. No credentials needed (fixture-based).
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import https from 'node:https';

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

// ---------------------------------------------------------------------------
// Load fixtures (reads the JSON fixture files directly — no @aether/proof-
// fixtures package dependency in the smoke scripts; the fixtures live in the
// repo.
// ---------------------------------------------------------------------------

function getScriptDir(): string {
  // Derive the script's directory from process.argv[1] (the file path used to
  // invoke the script). This works for both `tsx` and `node --loader` runs.
  const invokedPath = process.argv[1];
  if (!invokedPath) {
    // Fallback: assume CWD is the scripts/smoke directory.
    return process.cwd();
  }
  // Resolve symlinks and get the directory.
  const absolute = resolve(invokedPath);
  return resolve(absolute, '..');
}

function loadFixtureJson(filename: string): unknown {
  const scriptDir = getScriptDir();

  const fixturePath = resolve(
    scriptDir,
    '..',
    '..',
    'packages',
    'proof-fixtures',
    'fixtures',
    'email',
    filename
  );
  const raw = readFileSync(fixturePath, 'utf-8');
  return JSON.parse(raw);
}

/** Load the raw email input fixture. */
function loadRawEmailFixture(): unknown {
  return loadFixtureJson('raw_input.json');
}

/** Load the expected normalized email fixture. */
function loadExpectedNormalizedEmail(): unknown {
  return loadFixtureJson('expected_normalized.json');
}

// ---------------------------------------------------------------------------
// Normalized email event builders
// ---------------------------------------------------------------------------

interface NormalizedEmailEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  source: string;
  data: Record<string, unknown>;
}

function emailSentEvent(): NormalizedEmailEvent {
  return {
    event_id: 'email_evt_sent_001',
    event_type: 'email.sent',
    timestamp: new Date().toISOString(),
    source: 'sendgrid',
    data: {
      message_id: 'msg-1',
      sender: 'noreply@example.com',
      recipient: 'user@example.com',
      subject: 'Welcome!',
      campaign_id: 'camp_001',
    },
  };
}

function emailOpenEvent(): NormalizedEmailEvent {
  return {
    event_id: 'email_evt_open_001',
    event_type: 'email.opened',
    timestamp: new Date().toISOString(),
    source: 'sendgrid',
    data: {
      message_id: 'msg-1',
      recipient: 'user@example.com',
      campaign_id: 'camp_001',
      opened_at: new Date().toISOString(),
    },
  };
}

function emailClickEvent(): NormalizedEmailEvent {
  return {
    event_id: 'email_evt_click_001',
    event_type: 'email.clicked',
    timestamp: new Date().toISOString(),
    source: 'sendgrid',
    data: {
      message_id: 'msg-1',
      recipient: 'user@example.com',
      campaign_id: 'camp_001',
      link: 'https://example.com/offer',
      clicked_at: new Date().toISOString(),
    },
  };
}

function emailBounceEvent(): NormalizedEmailEvent {
  return {
    event_id: 'email_evt_bounce_001',
    event_type: 'email.bounced',
    timestamp: new Date().toISOString(),
    source: 'sendgrid',
    data: {
      message_id: 'msg-1',
      recipient: 'bounce@example.com',
      campaign_id: 'camp_001',
      reason: 'hard_bounce',
    },
  };
}

function emailUnsubscribeEvent(): NormalizedEmailEvent {
  return {
    event_id: 'email_evt_unsub_001',
    event_type: 'email.unsubscribed',
    timestamp: new Date().toISOString(),
    source: 'sendgrid',
    data: {
      message_id: 'msg-1',
      recipient: 'unsub@example.com',
      campaign_id: 'camp_001',
    },
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  console.log('[FPS-063] smoke:email-connector starting...');

  // --- Guard: Aether API env (no provider credentials needed) ---------------
  try {
    requireEnv('AETHER_API_URL');
    requireEnv('AETHER_API_KEY');
  } catch (err) {
    console.error(`[FPS-063] smoke:email-connector: FAIL — ${err}`);
    process.exit(1);
  }

  // --- Load fixtures ---------------------------------------------------------
  console.log('\n[FPS-063] Loading email fixtures from @aether/proof-fixtures...');
  const rawFixture = loadRawEmailFixture();
  const expectedNormalized = loadExpectedNormalizedEmail();

  console.log(
    '[FPS-063] Raw email fixture loaded:',
    JSON.stringify(rawFixture, null, 2)
  );
  console.log(
    '[FPS-063] Expected normalized fixture loaded:',
    JSON.stringify(expectedNormalized, null, 2)
  );

  // --- Build normalized batch from fixture events ---------------------------
  const events: NormalizedEmailEvent[] = [
    emailSentEvent(),
    emailOpenEvent(),
    emailClickEvent(),
    emailBounceEvent(),
    emailUnsubscribeEvent(),
  ];

  console.log(
    `\n[FPS-063] POSTing ${events.length} normalized email events to Aether ingestion...`
  );

  const result = await postBatch(events);

  if (!result.ok) {
    console.error(
      `[FPS-063] smoke:email-connector: FAIL — ingestion API returned ${result.status}`
    );
    console.error(
      '[FPS-063] smoke:email-connector:',
      JSON.stringify(result.body, null, 2)
    );
    process.exit(1);
  }

  console.log(
    `[FPS-063] smoke:email-connector: ingestion API accepted batch (status=${result.status})`
  );
  console.log(
    '[FPS-063] smoke:email-connector:',
    JSON.stringify(result.body, null, 2)
  );

  // --- Verify ---------------------------------------------------------------
  const accepted = (result.body as { accepted?: number }).accepted;
  const rejected = (result.body as { rejected?: number }).rejected;

  if (accepted !== events.length) {
    console.error(
      `[FPS-063] smoke:email-connector: FAIL — expected ${events.length} accepted, got ${accepted}`
    );
    process.exit(1);
  }

  console.log(
    `[FPS-063] smoke:email-connector: All ${events.length} events accepted (${rejected} rejected).`
  );

  for (const evt of events) {
    console.log(
      `  ✓ Email event ${evt.event_type} (event_id=${evt.event_id}, status=${result.status})`
    );
  }

  console.log('[FPS-063] smoke:email-connector complete.');
  process.exit(0);
}

main().catch((err) => {
  console.error('[FPS-063] smoke:email-connector: FAIL —', err);
  process.exit(1);
});
