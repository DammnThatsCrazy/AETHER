#!/usr/bin/env node

import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const cliPath = path.join(packageRoot, 'bin', 'aether.js');
const protocolVersion = '2026-07-28';

function requiredCredential(env) {
  const apiKey = env.AETHER_API_KEY?.trim();
  const sessionToken = env.AETHER_SESSION_TOKEN?.trim();
  if (Boolean(apiKey) === Boolean(sessionToken)) {
    throw new Error('Set exactly one explicit AETHER_API_KEY or AETHER_SESSION_TOKEN.');
  }
  return apiKey || sessionToken;
}

function cliJson(args, env) {
  const result = spawnSync(process.execPath, [cliPath, ...args, '--json'], {
    encoding: 'utf8',
    env: { ...env, AETHER_ACCESS_SURFACE: 'cli' },
    timeout: 30_000,
    maxBuffer: 1024 * 1024,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`CLI ${args.join(' ')} failed${result.status ? ` (exit ${result.status})` : ''}.`);
  }
  try {
    return JSON.parse(result.stdout);
  } catch {
    throw new Error(`CLI ${args.join(' ')} returned invalid JSON.`);
  }
}

function assertReferences(result, surface) {
  const refs = result?.interaction?.references;
  if (!refs?.audit_event_id || !refs?.usage_event_id) {
    throw new Error(`${surface} read did not return durable audit and usage references.`);
  }
  return {
    request_id: result.request_id,
    audit_event_id: refs.audit_event_id,
    usage_event_id: refs.usage_event_id,
  };
}

function readUsage(result, surface) {
  const count = result?.usage?.access_interaction_count;
  if (typeof count !== 'number' || !Number.isFinite(count) || count < 0) {
    throw new Error(`${surface} returned an invalid Access Kit usage summary.`);
  }
  return count;
}

async function postMcp(url, credential, method, params, id) {
  const headers = {
    accept: 'application/json, text/event-stream',
    'content-type': 'application/json',
    authorization: `Bearer ${credential}`,
    'mcp-protocol-version': protocolVersion,
    'mcp-method': method,
  };
  if (method === 'tools/call') headers['mcp-name'] = params.name;
  const response = await fetch(url, {
    method: 'POST',
    redirect: 'error',
    headers,
    body: JSON.stringify({
      jsonrpc: '2.0',
      id,
      method,
      params: {
        ...params,
        _meta: { protocolVersion, clientCapabilities: {} },
      },
    }),
    signal: AbortSignal.timeout(30_000),
  });
  const raw = await response.text();
  if (!response.ok) throw new Error(`Remote MCP ${method} failed (HTTP ${response.status}).`);
  let payload;
  if (response.headers.get('content-type')?.includes('text/event-stream')) {
    const dataLines = raw.split('\n').filter((line) => line.startsWith('data:'));
    if (!dataLines.length) throw new Error(`Remote MCP ${method} returned no JSON-RPC result.`);
    payload = JSON.parse(dataLines.at(-1).slice(5).trim());
  } else {
    payload = JSON.parse(raw);
  }
  if (payload.error) throw new Error(`Remote MCP ${method} returned a JSON-RPC error.`);
  if (payload.id !== id || !payload.result) throw new Error(`Remote MCP ${method} returned an invalid JSON-RPC response.`);
  return payload.result;
}

async function remoteMcpAcceptance(env, credential, minimumCount) {
  const rawUrl = env.AETHER_MCP_URL?.trim();
  if (!rawUrl) return null;
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error('AETHER_MCP_URL must be a valid hosted MCP endpoint URL.');
  }
  const isLoopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (!['https:', 'http:'].includes(url.protocol) || (url.protocol !== 'https:' && !isLoopback)
      || url.username || url.password || url.search || url.hash) {
    throw new Error('AETHER_MCP_URL must use HTTPS (HTTP is limited to loopback) and contain no credentials, query, or fragment.');
  }

  const listed = await postMcp(url, credential, 'tools/list', {}, 1);
  const names = new Set((listed.tools || []).map((tool) => tool.name));
  for (const name of ['entities_list', 'usage_summary']) {
    if (!names.has(name)) throw new Error(`Remote MCP does not expose the V1 ${name} tool.`);
  }
  const entityCall = await postMcp(url, credential, 'tools/call', {
    name: 'entities_list', arguments: { limit: 1 },
  }, 2);
  const interaction = entityCall.structuredContent?.interaction;
  const refs = assertReferences({
    interaction,
    request_id: interaction?.request_id,
  }, 'Remote MCP');
  const usageCall = await postMcp(url, credential, 'tools/call', {
    name: 'usage_summary', arguments: {},
  }, 3);
  const count = readUsage(usageCall.structuredContent, 'Remote MCP');
  if (count < minimumCount) {
    throw new Error('Remote MCP usage summary did not include the preceding CLI interaction.');
  }
  return { ...refs, access_interaction_count: count, available_tools: names.size };
}

async function main() {
  const credential = requiredCredential(process.env);
  if (!process.env.AETHER_API_URL?.trim()) {
    throw new Error('Set AETHER_API_URL explicitly to the API environment selected for live acceptance.');
  }

  const baseline = cliJson(['usage', 'summary'], process.env);
  const baselineCount = readUsage(baseline, 'CLI');
  const cliRead = cliJson(['entities', 'list', '--limit', '1'], process.env);
  const cliReferences = assertReferences(cliRead, 'CLI');
  const afterCli = cliJson(['usage', 'summary'], process.env);
  const cliCount = readUsage(afterCli, 'CLI');
  if (cliCount < baselineCount + 1) {
    throw new Error('CLI usage summary did not include the preceding CLI interaction.');
  }

  const remote = await remoteMcpAcceptance(process.env, credential, cliCount + 1);
  process.stdout.write(`${JSON.stringify({
    status: 'passed',
    target_api_origin: new URL(process.env.AETHER_API_URL).origin,
    cli: { ...cliReferences, access_interaction_count: cliCount },
    remote_mcp: remote ? { status: 'passed', ...remote } : { status: 'skipped', reason: 'AETHER_MCP_URL was not provided' },
    side_effects: 'read-only tenant queries; no deployment or staging lifecycle operation',
  }, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.message || 'Access Kit V1 acceptance failed.'}\n`);
  process.exitCode = 1;
});
