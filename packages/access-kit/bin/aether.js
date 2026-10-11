#!/usr/bin/env node

import {
  ingestTrackObservation,
  getAccountContext,
  getCapability,
  getCapabilityOverview,
  listCapabilities,
  getEntity,
  listEntities,
  MAX_ENTITY_PAGE_SIZE,
} from '../src/api.mjs';

const HELP = `Aether Access Kit — agent access inventory and canonical intake

Usage:
  aether agents capabilities overview [--json]
  aether agents capabilities list [--provider NAME] [--server-name NAME] [--tool-name NAME]
                                  [--limit N] [--offset N] [--json]
  aether agents capabilities show CAPABILITY_ID [--json]
  aether entities list [--entity-type TYPE] [--limit N] [--json]
  aether entities show ENTITY_ID [--json]
  aether account context [--json]
  aether ingest EVENT_NAME --event-id ID --session-id ID --anonymous-id ID --sequence N
                           [--properties-json JSON] [--json]

Authentication:
  AETHER_API_KEY           Tenant-scoped API key with read permission, for agents,
                           entity, and account-context queries
  AETHER_PUBLISHABLE_KEY   Site-bound pk_ key, for ingest only
  AETHER_SITE_ID           Site ID bound to AETHER_PUBLISHABLE_KEY, for ingest only
  AETHER_API_URL           API origin (default: https://api.aether.io)

Read and ingestion credentials are separate. Ingestion sends one generic track event to
POST /v1/batch with X-Aether-Site. Aether resolves tenant and site binding; no tenant ID
override is accepted. The API's per-event accepted/duplicate/rejected decisions are returned.
`;

function parseArgs(args) {
  const parsed = { positionals: [], json: false, options: {} };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--json') {
      parsed.json = true;
      continue;
    }
    if (arg === '--help' || arg === '-h') continue;
    if (arg.startsWith('--')) {
      const value = args[index + 1];
      if (!value || value.startsWith('--')) throw new Error(`${arg} requires a value.`);
      parsed.options[arg.slice(2)] = value;
      index += 1;
      continue;
    }
    parsed.positionals.push(arg);
  }
  return parsed;
}

function positiveInteger(raw, label, { min = 0, max = 100_000 } = {}) {
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw new Error(`${label} must be an integer from ${min} through ${max}.`);
  }
  return value;
}

function writeJson(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

function formatList(data, requestId, interaction) {
  const items = Array.isArray(data?.items) ? data.items : [];
  process.stdout.write(`Observed agent access capabilities (${items.length} returned)\n`);
  process.stdout.write(`Request: ${requestId}\n`);
  if (interaction) process.stdout.write(`Outcome: ${interaction.status_class}\n`);
  if (!items.length) {
    process.stdout.write('No observed capabilities in this page.\n');
    return;
  }
  for (const item of items) {
    const label = item.tool_name || item.server_name || item.provider || 'unnamed';
    process.stdout.write(`- ${label}  ${item.capability_id}  [${item.capability_kind || 'unknown'}]\n`);
  }
  process.stdout.write('Use --json for the complete response page.\n');
}

function printError(error) {
  if (process.argv.includes('--json')) {
    const details = {
      message: error.message,
      ...(Number.isInteger(error.status) ? { status: error.status } : {}),
      ...(error.code ? { code: error.code } : {}),
      ...(error.requestId ? { request_id: error.requestId } : {}),
      ...(error.apiRequestId ? { api_request_id: error.apiRequestId } : {}),
      ...(error.interaction ? { interaction: error.interaction } : {}),
    };
    process.stderr.write(`${JSON.stringify({ error: details })}\n`);
    process.exitCode = 1;
    return;
  }
  const suffix = error.requestId ? `\nRequest: ${error.requestId}` : '';
  const apiRequest = error.apiRequestId ? `\nAPI request: ${error.apiRequestId}` : '';
  process.stderr.write(`${error.message}${suffix}${apiRequest}\n`);
  process.exitCode = 1;
}

function writeRequestIds(result) {
  return {
    request_id: result.requestId,
    ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
  };
}

function writeInteraction(result) {
  return result.interaction ? { interaction: result.interaction } : {};
}

function formatEntities(entities, requestId, apiRequestId, interaction) {
  process.stdout.write(`Entities (${entities.length} returned)\n`);
  for (const entity of entities) {
    process.stdout.write(`- ${entity.display_name || '(unnamed)'}  ${entity.entity_id}  [${entity.entity_type}]\n`);
  }
  process.stdout.write(`Request: ${requestId}\n`);
  if (apiRequestId) process.stdout.write(`API request: ${apiRequestId}\n`);
  if (interaction) process.stdout.write(`Outcome: ${interaction.status_class}\n`);
}

async function main() {
  const { positionals, options, json } = parseArgs(process.argv.slice(2));
  const [area, command, subcommand, arg] = positionals;

  if (!area || area === 'help' || area === '--help' || area === '-h'
      || process.argv.includes('--help') || process.argv.includes('-h')) {
    process.stdout.write(HELP);
    return;
  }
  if (area === 'ingest') {
    if (!command || positionals.length !== 2) throw new Error(`Usage: aether ingest EVENT_NAME ...\n\n${HELP}`);
    const supportedOptions = new Set([
      'event-id', 'session-id', 'anonymous-id', 'sequence', 'properties-json',
    ]);
    for (const key of Object.keys(options)) {
      if (!supportedOptions.has(key)) throw new Error(`Unknown option: --${key}`);
    }
    for (const key of ['event-id', 'session-id', 'anonymous-id', 'sequence']) {
      if (!options[key]) throw new Error(`--${key} is required for retry-safe ingestion.`);
    }
    let properties = {};
    if (options['properties-json']) {
      try {
        properties = JSON.parse(options['properties-json']);
      } catch {
        throw new Error('--properties-json must contain valid JSON.');
      }
      if (!properties || typeof properties !== 'object' || Array.isArray(properties)) {
        throw new Error('--properties-json must contain a JSON object.');
      }
    }
    const result = await ingestTrackObservation({
      eventName: command,
      eventId: options['event-id'],
      sessionId: options['session-id'],
      anonymousId: options['anonymous-id'],
      eventSequence: positiveInteger(options.sequence, '--sequence', { max: Number.MAX_SAFE_INTEGER }),
      properties,
      surface: 'cli',
    });
    if (json) writeJson({ ...result.data, ...writeRequestIds(result), ...writeInteraction(result) });
    else {
      const data = result.data;
      process.stdout.write(`Aether ingestion: ${data.accepted ?? 0} accepted, ${data.duplicates ?? 0} duplicate, ${data.rejected ?? 0} rejected\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
      for (const event of data.events ?? []) {
        process.stdout.write(`- ${event.id}: ${event.status}${event.reason ? ` (${event.reason})` : ''}\n`);
      }
      process.stdout.write(`Request: ${result.requestId}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${result.responseRequestId}\n`);
    }
    if (result.data?.rejected > 0) process.exitCode = 2;
    return;
  }

  if (area === 'account' && command === 'context') {
    if (positionals.length !== 2 || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for account context.\n\n${HELP}`);
    }
    const result = await getAccountContext();
    const output = { account: result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`${JSON.stringify(result.data, null, 2)}\n`);
      process.stdout.write(`Request: ${result.requestId}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${result.responseRequestId}\n`);
    }
    return;
  }

  if (area === 'entities' && command === 'list') {
    if (positionals.length !== 2) throw new Error(`Unexpected argument for entities list.\n\n${HELP}`);
    const supportedOptions = new Set(['entity-type', 'limit']);
    for (const key of Object.keys(options)) {
      if (!supportedOptions.has(key)) throw new Error(`Unknown option: --${key}`);
    }
    const result = await listEntities({
      entityType: options['entity-type'],
      limit: options.limit
        ? positiveInteger(options.limit, '--limit', { min: 1, max: MAX_ENTITY_PAGE_SIZE })
        : 25,
    });
    const ids = writeRequestIds(result);
    const output = { ...result.data, ...ids, ...writeInteraction(result) };
    if (json) writeJson(output);
    else formatEntities(result.data.entities, result.requestId, result.responseRequestId, result.interaction);
    return;
  }

  if (area === 'entities' && command === 'show' && subcommand && positionals.length === 3) {
    if (Object.keys(options).length > 0) throw new Error(`Unexpected option for entities show.\n\n${HELP}`);
    const result = await getEntity(subcommand);
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`${JSON.stringify(result.data, null, 2)}\n`);
      process.stdout.write(`Request: ${result.requestId}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${result.responseRequestId}\n`);
    }
    return;
  }

  if (area !== 'agents' || command !== 'capabilities') {
    throw new Error(`Unknown command: ${area} ${command ?? ''}.\n\n${HELP}`);
  }

  if (subcommand === 'overview') {
    if (positionals.length !== 3 || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for agents capabilities overview.\n\n${HELP}`);
    }
    const result = await getCapabilityOverview();
    if (json) writeJson({ ...result.data, ...writeRequestIds(result), ...writeInteraction(result) });
    else {
      process.stdout.write('Observed agent access inventory overview\n');
      process.stdout.write(`${JSON.stringify(result.data, null, 2)}\n`);
      process.stdout.write(`Request: ${result.requestId}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
    }
    return;
  }

  if (subcommand === 'list') {
    if (positionals.length !== 3) throw new Error(`Unexpected argument for agents capabilities list.\n\n${HELP}`);
    const supportedOptions = new Set(['provider', 'server-name', 'tool-name', 'limit', 'offset']);
    for (const key of Object.keys(options)) {
      if (!supportedOptions.has(key)) throw new Error(`Unknown option: --${key}`);
    }
    const result = await listCapabilities({
      provider: options.provider,
      serverName: options['server-name'],
      toolName: options['tool-name'],
      limit: options.limit ? positiveInteger(options.limit, '--limit', { min: 1, max: 100 }) : 100,
      offset: options.offset ? positiveInteger(options.offset, '--offset') : 0,
    });
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else formatList(result.data, result.requestId, result.interaction);
    return;
  }

  if (subcommand === 'show' && arg && positionals.length === 4 && Object.keys(options).length === 0) {
    const result = await getCapability(arg);
    if (json) writeJson({ ...result.data, ...writeRequestIds(result), ...writeInteraction(result) });
    else {
      process.stdout.write(`${JSON.stringify(result.data, null, 2)}\n`);
      process.stdout.write(`Request: ${result.requestId}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
    }
    return;
  }

  throw new Error(`Unsupported agents capabilities command.\n\n${HELP}`);
}

main().catch((error) => {
  printError(error);
});
