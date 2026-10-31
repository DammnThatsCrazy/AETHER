#!/usr/bin/env node

import {
  ingestTrackObservation,
  listSessions,
  MAX_ENTITY_PAGE_SIZE,
  revokeSession,
} from '../src/api.mjs';
import { credentialStore } from '../src/credential-store.mjs';
import { loginWithAuth0Device, logoutStoredSession, readStoredSession } from '../src/auth.mjs';
import {
  getAccessOperation,
  invokeAccessOperation,
  listAccessOperations,
} from '../src/access-operations.mjs';
import { createContinuation, getContinuation } from '../src/continuation.mjs';

const HELP = `Aether Access Kit — agent access inventory and canonical intake

Usage:
  aether agents capabilities overview [--json]
  aether agents capabilities list [--provider NAME] [--server-name NAME] [--tool-name NAME]
                                  [--limit N] [--offset N] [--json]
  aether agents capabilities show CAPABILITY_ID [--json]
  aether agents behavior show AGENT_REF [--json]
  aether agents decisions show AGENT_REF DECISION_ID [--json]
  aether entities list [--entity-type TYPE] [--limit N] [--offset N] [--json]
  aether entities show ENTITY_ID [--json]
  aether entities neighborhood ENTITY_ID [--limit N] [--json]
  aether access operations list [--json]
  aether access operations show OPERATION_ID [--json]
  aether access invoke OPERATION_ID [--input-json JSON] [--json]
  aether continuations create --title TITLE --entity-id ENTITY_ID --idempotency-key KEY [--json]
  aether continuations show CONTINUATION_ID [--json]
  aether account context [--json]
  aether usage summary [--json]
  aether auth context [--json]
  aether auth login [--no-browser] [--json]
  aether auth logout [--json]
  aether auth sessions list [--limit N] [--offset N] [--json]
  aether auth sessions revoke SESSION_ID [--json]
  aether ingest EVENT_NAME --event-id ID --session-id ID --anonymous-id ID --sequence N
                           [--properties-json JSON] [--json]

Authentication:
  AETHER_API_KEY           Tenant-scoped API key for authorized reads and
                           continuation writes (which require write permission)
  AETHER_SESSION_TOKEN     Existing revocable human session for the same calls;
                           sent through the server's X-Session-Token contract
  AETHER_AUTH0_DOMAIN      Auth0 HTTPS tenant domain for the auth login command
  AETHER_AUTH0_CLIENT_ID   Public Native CLI client ID from Aether Terraform output
  AETHER_AUTH0_AUDIENCE    Aether API resource-server audience
  AETHER_PUBLISHABLE_KEY   Site-bound pk_ key, for ingest only
  AETHER_SITE_ID           Site ID bound to AETHER_PUBLISHABLE_KEY, for ingest only
  AETHER_API_URL           API origin (default: https://api.aether.io)

Set exactly one API credential: AETHER_API_KEY or AETHER_SESSION_TOKEN. The CLI
uses a saved human session from the OS credential store when neither is supplied.
The auth login command saves only an Aether revocable session; auth logout revokes it.
Read and ingestion credentials are separate. Ingestion sends one generic track event to POST /v1/batch with X-Aether-Site. Aether
resolves tenant and site binding; no tenant ID override is accepted. The API's per-event
accepted/duplicate/rejected decisions are returned.
`;

function parseArgs(args) {
  const parsed = { positionals: [], json: false, options: {} };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--json') {
      parsed.json = true;
      continue;
    }
    if (arg === '--no-browser') {
      parsed.options['no-browser'] = true;
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

function terminalText(value) {
  return String(value).replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/gu, (character) => {
    return `\\u{${character.codePointAt(0).toString(16)}}`;
  });
}

function formatList(data, requestId, interaction) {
  const items = Array.isArray(data?.items) ? data.items : [];
  process.stdout.write(`Observed agent access capabilities (${items.length} returned)\n`);
  process.stdout.write(`Request: ${terminalText(requestId)}\n`);
  if (interaction) process.stdout.write(`Outcome: ${interaction.status_class}\n`);
  if (!items.length) {
    process.stdout.write('No observed capabilities in this page.\n');
    return;
  }
  for (const item of items) {
    const label = item.tool_name || item.server_name || item.provider || 'unnamed';
    process.stdout.write(`- ${terminalText(label)}  ${terminalText(item.capability_id)}  [${terminalText(item.capability_kind || 'unknown')}]\n`);
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
  const suffix = error.requestId ? `\nRequest: ${terminalText(error.requestId)}` : '';
  const apiRequest = error.apiRequestId ? `\nAPI request: ${terminalText(error.apiRequestId)}` : '';
  process.stderr.write(`${terminalText(error.message)}${suffix}${apiRequest}\n`);
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

function formatEntities(entities, requestId, apiRequestId, interaction, nextOffset) {
  process.stdout.write(`Entities (${entities.length} returned)\n`);
  for (const entity of entities) {
    process.stdout.write(`- ${terminalText(entity.display_name || '(unnamed)')}  ${terminalText(entity.entity_id)}  [${terminalText(entity.entity_type)}]\n`);
  }
  process.stdout.write(`Request: ${terminalText(requestId)}\n`);
  if (apiRequestId) process.stdout.write(`API request: ${terminalText(apiRequestId)}\n`);
  if (interaction) process.stdout.write(`Outcome: ${interaction.status_class}\n`);
  if (nextOffset != null) process.stdout.write(`Next offset: ${nextOffset}\n`);
}

function formatSessions(sessions, requestId, apiRequestId, interaction) {
  process.stdout.write(`Human sessions (${sessions.length} returned)\n`);
  for (const session of sessions) {
    process.stdout.write(`- ${session.session_id}  [${session.status ?? 'unknown'}]`);
    if (session.absolute_expires_at) process.stdout.write(`  expires ${session.absolute_expires_at}`);
    process.stdout.write('\n');
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
  const isLogin = area === 'auth' && command === 'login';
  const isLogout = area === 'auth' && command === 'logout';
  const needsTenantRead = area === 'account'
    || area === 'entities'
    || area === 'continuations'
    || (area === 'access' && command === 'invoke')
    || (area === 'usage' && command === 'summary')
    || area === 'agents'
    || (area === 'auth' && command !== 'login' && command !== 'logout');
  let storedSession = null;
  if (needsTenantRead && !process.env.AETHER_API_KEY?.trim()
      && !process.env.AETHER_SESSION_TOKEN?.trim()) {
    storedSession = await readStoredSession(process.env);
    if (storedSession) process.env.AETHER_SESSION_TOKEN = storedSession.token;
  }
  if (needsTenantRead) process.env.AETHER_ACCESS_SURFACE = 'cli';

  if (isLogin) {
    if (positionals.length !== 2 || Object.keys(options).some(key => key !== 'no-browser')) {
      throw new Error(`Unexpected arguments for auth login.\n\n${HELP}`);
    }
    const result = await loginWithAuth0Device({
      env: process.env,
      store: credentialStore,
      ...(options['no-browser'] ? { openBrowser: async () => {} } : {}),
      onInstructions: ({ verificationUri, activationUri, userCode }) => {
        process.stderr.write('Authorize this Aether CLI session in Auth0:\n');
        process.stderr.write(`  Open: ${activationUri || verificationUri}\n`);
        process.stderr.write(`  Code: ${userCode}\n`);
        if (activationUri && activationUri !== verificationUri) {
          process.stderr.write(`  Manual entry: ${verificationUri}\n`);
        }
      },
    });
    const output = {
      session_id: result.session_id,
      credential_class: result.credential_class,
      idle_expires_at: result.idle_expires_at,
      absolute_expires_at: result.absolute_expires_at,
      request_id: result.requestId,
      ...(result.apiRequestId ? { api_request_id: result.apiRequestId } : {}),
      preflight_request_id: result.preflightRequestId,
      interaction: result.interaction,
    };
    if (json) writeJson(output);
    else {
      process.stdout.write(`Signed in with revocable session ${result.session_id}.\n`);
      process.stdout.write('Session saved in the OS credential store.\n');
      if (result.absolute_expires_at) process.stdout.write(`Expires: ${result.absolute_expires_at}\n`);
      process.stdout.write(`Request: ${result.requestId}\n`);
    }
    return;
  }

  if (isLogout) {
    if (positionals.length !== 2 || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for auth logout.\n\n${HELP}`);
    }
    const result = await logoutStoredSession({ env: process.env, store: credentialStore });
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`Session ${result.data.session_id}: ${result.data.revoked ? 'revoked' : 'not revoked'}\n`);
      process.stdout.write('Removed the local session from the OS credential store.\n');
      process.stdout.write(`Request: ${result.requestId}\n`);
    }
    return;
  }

  if (area === 'access' && command === 'operations' && subcommand === 'list') {
    if (positionals.length !== 3 || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for access operations list.\n\n${HELP}`);
    }
    const operations = listAccessOperations();
    if (json) writeJson({ catalog_kind: 'adapter_supported_operations', operations });
    else {
      process.stdout.write('Access Kit supported operations (server authorization required per call)\n');
      for (const operation of operations) {
        process.stdout.write(`- ${terminalText(operation.id)}  ${terminalText(operation.description)}\n`);
      }
    }
    return;
  }

  if (area === 'access' && command === 'operations' && subcommand === 'show') {
    if (positionals.length !== 4 || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for access operations show.\n\n${HELP}`);
    }
    const operation = getAccessOperation(arg);
    if (!operation) throw new Error('Unsupported Access Kit operation ID.');
    if (json) writeJson({ catalog_kind: 'adapter_supported_operations', operation });
    else process.stdout.write(`${JSON.stringify(operation, null, 2)}\n`);
    return;
  }

  if (area === 'access' && command === 'invoke') {
    if (positionals.length !== 3 || Object.keys(options).some((key) => key !== 'input-json')) {
      throw new Error(`Unexpected arguments for access invoke.\n\n${HELP}`);
    }
    let input = {};
    if (options['input-json']) {
      try {
        input = JSON.parse(options['input-json']);
      } catch {
        throw new Error('--input-json must contain valid JSON.');
      }
    }
    const result = await invokeAccessOperation(subcommand, input, process.env);
    const output = { operation_id: subcommand, data: result.data,
      ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`${terminalText(JSON.stringify(result.data, null, 2))}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${terminalText(result.responseRequestId)}\n`);
    }
    return;
  }

  if (area === 'continuations' && command === 'create') {
    if (positionals.length !== 2
        || Object.keys(options).some((key) => !['title', 'entity-id', 'idempotency-key'].includes(key))
        || !options.title || !options['entity-id'] || !options['idempotency-key']) {
      throw new Error(`Usage: aether continuations create --title TITLE --entity-id ENTITY_ID --idempotency-key KEY [--json]\n\n${HELP}`);
    }
    const result = await createContinuation({
      title: options.title,
      entityId: options['entity-id'],
      idempotencyKey: options['idempotency-key'],
    }, process.env, { sourceClient: 'desktop' });
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`Continuation ${terminalText(result.data.continuation_id)} ${result.data.replayed ? 'replayed' : 'created'}.\n`);
      process.stdout.write(`Title: ${terminalText(result.data.title)}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
    }
    return;
  }

  if (area === 'continuations' && command === 'show') {
    if (positionals.length !== 3 || Object.keys(options).length > 0) {
      throw new Error(`Usage: aether continuations show CONTINUATION_ID [--json]\n\n${HELP}`);
    }
    const result = await getContinuation(subcommand);
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`${terminalText(JSON.stringify(result.data, null, 2))}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
    }
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
        process.stdout.write(`- ${terminalText(event.id)}: ${terminalText(event.status)}${event.reason ? ` (${terminalText(event.reason)})` : ''}\n`);
      }
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${terminalText(result.responseRequestId)}\n`);
    }
    if (result.data?.rejected > 0) process.exitCode = 2;
    return;
  }

  if (area === 'account' && command === 'context') {
    if (positionals.length !== 2 || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for account context.\n\n${HELP}`);
    }
    const result = await invokeAccessOperation('account.context');
    const output = { account: result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`${JSON.stringify(result.data, null, 2)}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${terminalText(result.responseRequestId)}\n`);
    }
    return;
  }

  if (area === 'usage' && command === 'summary') {
    if (positionals.length !== 2 || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for usage summary.\n\n${HELP}`);
    }
    const result = await invokeAccessOperation('usage.summary');
    const output = { usage: result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`Access Kit interactions: ${result.data.access_interaction_count}\n`);
      if (result.data.billing_period_start && result.data.billing_period_end) {
        process.stdout.write(`Period: ${result.data.billing_period_start} to ${result.data.billing_period_end}\n`);
      }
      process.stdout.write(`Usage status: ${result.data.status}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
    }
    return;
  }

  if (area === 'auth' && command === 'context') {
    if (positionals.length !== 2 || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for auth context.\n\n${HELP}`);
    }
    const result = await invokeAccessOperation('account.context');
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

  if (area === 'auth' && command === 'sessions' && subcommand === 'list') {
    if (positionals.length !== 3) throw new Error(`Unexpected argument for auth sessions list.\n\n${HELP}`);
    const supportedOptions = new Set(['limit', 'offset']);
    for (const key of Object.keys(options)) {
      if (!supportedOptions.has(key)) throw new Error(`Unknown option: --${key}`);
    }
    const result = await listSessions({
      limit: options.limit ? positiveInteger(options.limit, '--limit', { min: 1, max: 100 }) : 20,
      offset: options.offset ? positiveInteger(options.offset, '--offset', { max: 10_000 }) : 0,
    });
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else formatSessions(
      result.data.sessions, result.requestId, result.responseRequestId, result.interaction,
    );
    return;
  }

  if (area === 'auth' && command === 'sessions' && subcommand === 'revoke' && arg) {
    if (positionals.length !== 4 || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for auth sessions revoke.\n\n${HELP}`);
    }
    const result = await revokeSession(arg);
    if (storedSession?.session_id === arg) {
      const { readApiOrigin } = await import('../src/api.mjs');
      await credentialStore.remove(readApiOrigin(process.env));
    }
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`Session ${result.data.session_id}: ${result.data.revoked ? 'revoked' : 'not revoked'}\n`);
      process.stdout.write(`Request: ${result.requestId}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${result.responseRequestId}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
    }
    return;
  }

  if (area === 'entities' && command === 'list') {
    if (positionals.length !== 2) throw new Error(`Unexpected argument for entities list.\n\n${HELP}`);
    const supportedOptions = new Set(['entity-type', 'limit', 'offset']);
    for (const key of Object.keys(options)) {
      if (!supportedOptions.has(key)) throw new Error(`Unknown option: --${key}`);
    }
    const result = await invokeAccessOperation('entities.list', {
      entity_type: options['entity-type'],
      limit: options.limit
        ? positiveInteger(options.limit, '--limit', { min: 1, max: MAX_ENTITY_PAGE_SIZE })
        : 25,
      ...(options.offset !== undefined ? {
        offset: positiveInteger(options.offset, '--offset', { max: 100_000 }),
      } : {}),
    });
    const ids = writeRequestIds(result);
    const output = { ...result.data, ...ids, ...writeInteraction(result) };
    if (json) writeJson(output);
    else formatEntities(
      result.data.entities, result.requestId, result.responseRequestId,
      result.interaction, result.data.next_offset,
    );
    return;
  }

  if (area === 'entities' && command === 'show' && subcommand && positionals.length === 3) {
    if (Object.keys(options).length > 0) throw new Error(`Unexpected option for entities show.\n\n${HELP}`);
    const result = await invokeAccessOperation('entities.get', { entity_id: subcommand });
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`${JSON.stringify(result.data, null, 2)}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${terminalText(result.responseRequestId)}\n`);
    }
    return;
  }

  if (area === 'entities' && command === 'neighborhood' && subcommand && positionals.length === 3) {
    if (Object.keys(options).some((key) => key !== 'limit')) {
      throw new Error(`Unexpected option for entities neighborhood.\n\n${HELP}`);
    }
    const result = await invokeAccessOperation('entities.neighborhood', {
      entity_id: subcommand,
      limit: options.limit
        ? positiveInteger(options.limit, '--limit', { min: 1, max: 50 })
        : 25,
    });
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`${terminalText(JSON.stringify(result.data, null, 2))}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${terminalText(result.responseRequestId)}\n`);
    }
    return;
  }

  if (area === 'agents' && ['behavior', 'decisions'].includes(command) && subcommand === 'show') {
    const decision = command === 'decisions';
    if (positionals.length !== (decision ? 5 : 4) || Object.keys(options).length > 0) {
      throw new Error(`Unexpected arguments for agents ${command} show.\n\n${HELP}`);
    }
    const result = decision
      ? await invokeAccessOperation('agents.decision', { agent_ref: arg, decision_id: positionals[4] })
      : await invokeAccessOperation('agents.behavior', { agent_ref: arg });
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else {
      process.stdout.write(`${terminalText(JSON.stringify(result.data, null, 2))}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
      if (result.responseRequestId) process.stdout.write(`API request: ${terminalText(result.responseRequestId)}\n`);
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
    const result = await invokeAccessOperation('agent_access.observed.overview');
    if (json) writeJson({ ...result.data, ...writeRequestIds(result), ...writeInteraction(result) });
    else {
      process.stdout.write('Observed agent access inventory overview\n');
      process.stdout.write(`${JSON.stringify(result.data, null, 2)}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
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
    const result = await invokeAccessOperation('agent_access.observed.list', {
      provider: options.provider,
      server_name: options['server-name'],
      tool_name: options['tool-name'],
      limit: options.limit ? positiveInteger(options.limit, '--limit', { min: 1, max: 100 }) : 100,
      offset: options.offset ? positiveInteger(options.offset, '--offset') : 0,
    });
    const output = { ...result.data, ...writeRequestIds(result), ...writeInteraction(result) };
    if (json) writeJson(output);
    else formatList(result.data, result.requestId, result.interaction);
    return;
  }

  if (subcommand === 'show' && arg && positionals.length === 4 && Object.keys(options).length === 0) {
    const result = await invokeAccessOperation('agent_access.observed.get', { capability_id: arg });
    if (json) writeJson({ ...result.data, ...writeRequestIds(result), ...writeInteraction(result) });
    else {
      process.stdout.write(`${JSON.stringify(result.data, null, 2)}\n`);
      process.stdout.write(`Request: ${terminalText(result.requestId)}\n`);
      process.stdout.write(`Outcome: ${result.interaction.status_class}\n`);
    }
    return;
  }

  throw new Error(`Unsupported agents capabilities command.\n\n${HELP}`);
}

main().catch((error) => {
  printError(error);
});
