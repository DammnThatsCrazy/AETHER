#!/usr/bin/env node
// W3 real-tenant certification for the Access Kit (design-partner readiness).
//
// Drives the surfaces a design partner uses — Node client, CLI, local stdio
// MCP and (optionally) the hosted MCP — against a deployed API with two
// tenants, and writes a JSON evidence report. Every step records request IDs
// and audit/usage references so the report can be checked against the server.
//
//   1. Ingest one observation for tenant A through the CLI (publishable key).
//   2. Wait until identity resolution makes it findable: profile360.search.
//   3. Read the Profile360 frame through every surface; slot IDs and states
//      must agree across surfaces.
//   4. Check every slot carries a state and a freshness record.
//   5. Tenant B must not find or read tenant A's subject.
//   6. Usage must count the reads, and audit/usage reconciliation must answer.
//
// Read-only for the tenant apart from the single ingested observation. It
// never wakes, deploys or changes staging. Run `--plan` to print the steps.
//
// Environment:
//   AETHER_API_URL               API origin (required)
//   AETHER_W3_TENANT_A_KEY       read API key for tenant A (required)
//   AETHER_W3_TENANT_A_ADMIN_KEY admin API key for tenant A, used only for reconciliation (required)
//   AETHER_W3_TENANT_B_KEY       read API key for tenant B (required)
//   AETHER_W3_PUBLISHABLE_KEY    tenant A site-bound pk_ key for ingest (required)
//   AETHER_W3_SITE_ID            site bound to that key (required)
//   AETHER_MCP_URL               hosted MCP endpoint (optional; skipped if unset)
//   AETHER_W3_RESOLVE_TIMEOUT_S  seconds to wait for identity resolution (default 300)

import { spawn, spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { AccessApiError, requestAether } from '../src/api.mjs';
import { createAccessClient } from '../src/index.mjs';

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const cliPath = path.join(packageRoot, 'bin', 'aether.js');
const mcpPath = path.join(packageRoot, 'bin', 'aether-mcp.js');
const PROTOCOL_VERSION = '2026-07-28';

export const STEPS = Object.freeze([
  'ingest_observation_cli',
  'resolve_subject_profile360_search',
  'profile360_frame_node_client',
  'profile360_frame_cli',
  'profile360_frame_local_mcp',
  'profile360_frame_hosted_mcp',
  'cross_surface_agreement',
  'slot_state_and_freshness',
  'cross_tenant_denial',
  'usage_and_reconciliation',
]);

const REQUIRED_ENV = [
  'AETHER_API_URL', 'AETHER_W3_TENANT_A_KEY', 'AETHER_W3_TENANT_A_ADMIN_KEY', 'AETHER_W3_TENANT_B_KEY',
  'AETHER_W3_PUBLISHABLE_KEY', 'AETHER_W3_SITE_ID',
];

export function readConfig(env) {
  const missing = REQUIRED_ENV.filter((name) => !env[name]?.trim());
  if (missing.length) throw new Error(`Missing required environment: ${missing.join(', ')}`);
  const apiUrl = new URL(env.AETHER_API_URL);
  if (apiUrl.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(apiUrl.hostname)) {
    throw new Error('AETHER_API_URL must use HTTPS outside loopback.');
  }
  if (env.AETHER_W3_TENANT_A_KEY === env.AETHER_W3_TENANT_B_KEY) {
    throw new Error('Tenant A and tenant B keys must differ.');
  }
  const timeout = Number(env.AETHER_W3_RESOLVE_TIMEOUT_S || 300);
  if (!Number.isInteger(timeout) || timeout < 10 || timeout > 3600) {
    throw new Error('AETHER_W3_RESOLVE_TIMEOUT_S must be an integer from 10 to 3600.');
  }
  return {
    apiUrl: apiUrl.origin,
    keyA: env.AETHER_W3_TENANT_A_KEY.trim(),
    keyB: env.AETHER_W3_TENANT_B_KEY.trim(),
    // Reconciliation is an admin route; the access checks keep the read-only key.
    adminKeyA: env.AETHER_W3_TENANT_A_ADMIN_KEY.trim(),
    publishableKey: env.AETHER_W3_PUBLISHABLE_KEY.trim(),
    siteId: env.AETHER_W3_SITE_ID.trim(),
    mcpUrl: env.AETHER_MCP_URL?.trim() || null,
    resolveTimeoutSeconds: timeout,
  };
}

function cli(args, env) {
  const result = spawnSync(process.execPath, [cliPath, ...args, '--json'], {
    encoding: 'utf8', env, timeout: 60_000, maxBuffer: 8 * 1024 * 1024,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`CLI ${args.slice(0, 3).join(' ')} failed (exit ${result.status}).`);
  }
  return JSON.parse(result.stdout);
}

function readEnv(config, key) {
  return {
    PATH: process.env.PATH, HOME: process.env.HOME,
    AETHER_API_URL: config.apiUrl, AETHER_API_KEY: key,
  };
}

async function localMcpCall(env, name, args) {
  const child = spawn(process.execPath, [mcpPath], { env, stdio: ['pipe', 'pipe', 'pipe'] });
  const pending = new Map();
  let buffer = '';
  child.stdout.on('data', (chunk) => {
    buffer += chunk;
    let index;
    while ((index = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, index).trim();
      buffer = buffer.slice(index + 1);
      if (!line) continue;
      const message = JSON.parse(line);
      pending.get(message.id)?.(message);
    }
  });
  const send = (id, method, params) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`local MCP ${method} timed out`)), 60_000);
    pending.set(id, (message) => { clearTimeout(timer); resolve(message); });
    child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`);
  });
  try {
    await send(1, 'initialize', {
      protocolVersion: PROTOCOL_VERSION, capabilities: {},
      clientInfo: { name: 'aether-w3-certify', version: '1' },
    });
    child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`);
    const response = await send(2, 'tools/call', { name, arguments: args });
    if (response.error || response.result?.isError) throw new Error(`local MCP ${name} returned an error`);
    return response.result.structuredContent;
  } finally {
    child.kill();
  }
}

async function hostedMcpCall(url, key, name, args) {
  const response = await fetch(url, {
    method: 'POST',
    redirect: 'error',
    headers: {
      accept: 'application/json, text/event-stream',
      'content-type': 'application/json',
      authorization: `Bearer ${key}`,
      'mcp-protocol-version': PROTOCOL_VERSION,
      'mcp-method': 'tools/call',
      'mcp-name': name,
    },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 1, method: 'tools/call',
      params: { name, arguments: args, _meta: { protocolVersion: PROTOCOL_VERSION, clientCapabilities: {} } },
    }),
    signal: AbortSignal.timeout(60_000),
  });
  const raw = await response.text();
  if (!response.ok) throw new Error(`hosted MCP ${name} failed (HTTP ${response.status})`);
  const json = response.headers.get('content-type')?.includes('text/event-stream')
    ? JSON.parse(raw.split('\n').filter((l) => l.startsWith('data:')).at(-1).slice(5).trim())
    : JSON.parse(raw);
  if (json.error || json.result?.isError) throw new Error(`hosted MCP ${name} returned an error`);
  return json.result.structuredContent;
}

/**
 * Slot IDs in a frame that expose any data: content, claims or evidence.
 * Used for the cross-tenant check, where every such slot is a leak whatever
 * its state (degraded slots can carry evidenced content).
 */
export function slotsExposingData(frame) {
  return (frame?.slots || []).filter((slot) => (slot.content !== undefined && slot.content !== null)
    || (Array.isArray(slot.claims) && slot.claims.length > 0)
    || (Array.isArray(slot.evidenceRefs) && slot.evidenceRefs.length > 0)
    || (Array.isArray(slot.provenance) && slot.provenance.length > 0)).map((slot) => slot.id);
}

function slotShape(frame) {
  return (frame?.slots || []).map((slot) => `${slot.id}:${slot.state}`).sort();
}

function refs(result) {
  const interaction = result?.interaction || {};
  return {
    request_id: result?.request_id ?? result?.requestId ?? interaction.request_id ?? null,
    audit_event_id: interaction.references?.audit_event_id ?? null,
    usage_event_id: interaction.references?.usage_event_id ?? null,
  };
}

async function expectDenied(promise) {
  try {
    const result = await promise;
    return { denied: false, result };
  } catch (error) {
    if (error instanceof AccessApiError && [401, 403, 404].includes(error.status)) {
      return { denied: true, status: error.status, request_id: error.requestId ?? null };
    }
    throw error;
  }
}

async function certify(config, report) {
  const step = (name, data) => { report.steps.push({ step: name, status: 'passed', ...data }); };
  const clientA = createAccessClient({ apiUrl: config.apiUrl, apiKey: config.keyA });
  const clientB = createAccessClient({ apiUrl: config.apiUrl, apiKey: config.keyB });

  const usageBefore = (await clientA.usage.summary()).data?.access_interaction_count ?? 0;

  const sessionId = `w3-${randomUUID()}`;
  const anonymousId = `w3-anon-${randomUUID()}`;
  const ingest = cli([
    'ingest', 'w3_certification', '--event-id', randomUUID(), '--session-id', sessionId,
    '--anonymous-id', anonymousId, '--sequence', '1',
    '--properties-json', JSON.stringify({ w3_run: report.run_id }),
  ], {
    PATH: process.env.PATH, HOME: process.env.HOME, AETHER_API_URL: config.apiUrl,
    AETHER_PUBLISHABLE_KEY: config.publishableKey, AETHER_SITE_ID: config.siteId,
  });
  step('ingest_observation_cli', { session_id: sessionId, response: ingest.data ?? ingest });

  const deadline = Date.now() + config.resolveTimeoutSeconds * 1000;
  let entityId = null;
  let attempts = 0;
  while (!entityId) {
    attempts += 1;
    try {
      entityId = (await clientA.profile360.search({ session: sessionId })).data.entity_id;
    } catch (error) {
      if (!(error instanceof AccessApiError && error.status === 404) || Date.now() > deadline) throw error;
      await new Promise((resolve) => setTimeout(resolve, 10_000));
    }
  }
  step('resolve_subject_profile360_search', { entity_id: entityId, attempts });

  const viaNode = await clientA.profile360.get(entityId);
  step('profile360_frame_node_client', refs(viaNode));
  const viaCli = cli(['profile360', 'get', entityId], readEnv(config, config.keyA));
  step('profile360_frame_cli', refs(viaCli));
  const viaLocal = await localMcpCall(readEnv(config, config.keyA), 'profile360_get', { entity_id: entityId });
  step('profile360_frame_local_mcp', refs(viaLocal));
  let viaHosted = null;
  if (config.mcpUrl) {
    viaHosted = await hostedMcpCall(config.mcpUrl, config.keyA, 'profile360_get', { entity_id: entityId });
    step('profile360_frame_hosted_mcp', refs(viaHosted));
  } else {
    report.steps.push({ step: 'profile360_frame_hosted_mcp', status: 'skipped', reason: 'AETHER_MCP_URL not set' });
  }

  const shapes = {
    node: slotShape(viaNode.data), cli: slotShape(viaCli.data), local_mcp: slotShape(viaLocal.data),
    ...(viaHosted ? { hosted_mcp: slotShape(viaHosted.data) } : {}),
  };
  const reference = JSON.stringify(shapes.node);
  if (!shapes.node.length || Object.values(shapes).some((shape) => JSON.stringify(shape) !== reference)) {
    throw new Error('Profile360 slot IDs or states differ between surfaces.');
  }
  step('cross_surface_agreement', { surfaces: Object.keys(shapes), slots: shapes.node.length });

  const slots = viaNode.data.slots;
  const missing = slots.filter((slot) => !slot.state || slot.freshness === undefined).map((slot) => slot.id);
  if (missing.length) throw new Error(`Slots without state or freshness: ${missing.join(', ')}`);
  const freshness = Object.fromEntries(slots.map((slot) => [slot.id, slot.freshness?.state ?? 'unknown']));
  step('slot_state_and_freshness', { slot_states: Object.fromEntries(slots.map((s) => [s.id, s.state])), freshness });

  const search = await expectDenied(clientB.profile360.search({ session: sessionId }));
  const read = await expectDenied(clientB.profile360.get(entityId));
  const leaked = read.denied ? [] : slotsExposingData(read.result.data);
  if (!search.denied || leaked.length) {
    throw new Error(`Tenant B reached tenant A's subject (search denied=${search.denied}, slots exposing data=${leaked.join(',')}).`);
  }
  step('cross_tenant_denial', {
    search: { status: search.status }, read: read.denied ? { status: read.status } : { readable_slots: 0 },
  });

  const usageAfter = (await clientA.usage.summary()).data?.access_interaction_count ?? 0;
  const minimum = usageBefore + (viaHosted ? 4 : 3);
  if (usageAfter < minimum) throw new Error(`Usage count ${usageAfter} did not include the reads (expected >= ${minimum}).`);
  const reconciliation = await requestAether('/v1/billing/usage/access-reconciliation', undefined, {
    AETHER_API_URL: config.apiUrl, AETHER_API_KEY: config.adminKeyA,
  });
  step('usage_and_reconciliation', {
    usage_before: usageBefore, usage_after: usageAfter, reconciliation: reconciliation.data,
  });
}

async function main(argv) {
  if (argv.includes('--plan')) {
    process.stdout.write(`${JSON.stringify({ steps: STEPS, required_env: REQUIRED_ENV }, null, 2)}\n`);
    return 0;
  }
  const outIndex = argv.indexOf('--out');
  const outPath = outIndex >= 0 ? argv[outIndex + 1] : null;
  const config = readConfig(process.env);
  const report = {
    run_id: randomUUID(), started_at: new Date().toISOString(), api_origin: config.apiUrl,
    hosted_mcp: Boolean(config.mcpUrl), steps: [], status: 'running',
  };
  try {
    await certify(config, report);
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed';
    report.error = error instanceof Error ? error.message : 'certification failed';
  }
  report.finished_at = new Date().toISOString();
  const text = `${JSON.stringify(report, null, 2)}\n`;
  if (outPath) writeFileSync(outPath, text);
  process.stdout.write(text);
  return report.status === 'passed' ? 0 : 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; }, (error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
