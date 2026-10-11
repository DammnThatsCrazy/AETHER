import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const cliPath = fileURLToPath(new URL('../bin/aether.js', import.meta.url));
const preloadPath = fileURLToPath(new URL('./mock-fetch.mjs', import.meta.url));

function runCli(args, extraEnv = {}) {
  return spawnSync(process.execPath, ['--import', preloadPath, cliPath, ...args], {
    encoding: 'utf8',
    env: {
      ...process.env,
      AETHER_API_KEY: 'cli-test-secret',
      AETHER_API_URL: 'https://api.example.test',
      ACCESS_KIT_MOCK_TRACE: '1',
      ...extraEnv,
    },
  });
}

test('CLI entities list emits the fixed projection, request IDs, and bounded existing route call', () => {
  const result = runCli([
    'entities', 'list', '--entity-type', 'organization', '--limit', '25', '--json',
  ]);
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.deepEqual(Object.keys(output.entities[0]), [
    'entity_id', 'entity_type', 'display_name', 'parent_entity_id', 'created_at', 'updated_at',
  ]);
  assert.equal(output.entities[0].entity_id, 'entity-cli');
  assert.equal(output.request_id, 'cli-request-id');
  assert.equal(output.api_request_id, 'api-envelope-id');
  assert.equal(output.interaction.status_class, 'successful');
  assert.equal(JSON.stringify(output).includes('tenant-private'), false);
  assert.equal(JSON.stringify(output).includes('private-metadata'), false);
  assert.equal(JSON.stringify(output).includes('private-field'), false);
  assert.match(result.stderr, /MOCK_FETCH GET \/v1\/entities\?entity_type=organization&limit=25 redirect=error/);
  assert.equal(`${result.stdout}${result.stderr}`.includes('cli-test-secret'), false);
});

test('CLI entities show returns only the selected fields', () => {
  const result = runCli(['entities', 'show', 'entity-cli', '--json']);
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.deepEqual(Object.keys(output), [
    'entity_id', 'entity_type', 'display_name', 'parent_entity_id', 'created_at', 'updated_at',
    'request_id', 'api_request_id', 'interaction',
  ]);
  assert.equal(output.display_name, 'CLI test entity');
  assert.equal(output.interaction.operation, 'query');
  assert.equal(JSON.stringify(output).includes('tenant-private'), false);
  assert.match(result.stderr, /MOCK_FETCH GET \/v1\/entities\/entity-cli redirect=error/);
});

test('CLI rejects entity pages over 50 before making an API request', () => {
  const result = runCli(['entities', 'list', '--limit', '51', '--json']);
  assert.equal(result.status, 1);
  assert.match(JSON.parse(result.stderr).error.message, /--limit must be an integer from 1 through 50/);
  assert.doesNotMatch(result.stderr, /MOCK_FETCH/);
});

test('CLI preserves API status, code, and both request IDs on failure', () => {
  const result = runCli(['entities', 'show', 'entity-cli', '--json'], {
    ACCESS_KIT_MOCK_MODE: 'entities-denied',
    ACCESS_KIT_MOCK_TRACE: '0',
  });
  assert.equal(result.status, 1);
  const failure = JSON.parse(result.stderr).error;
  assert.equal(failure.status, 403);
  assert.equal(failure.code, 'permission_denied');
  assert.equal(failure.request_id, 'cli-denial-id');
  assert.equal(failure.api_request_id, 'api-denied-id');
  assert.equal(failure.interaction.status_class, 'denied');
  assert.match(failure.message, /HTTP 403, permission_denied/);
  assert.equal(result.stdout, '');
});

test('CLI escapes terminal controls in observed capability labels and kinds', () => {
  const result = runCli(['agents', 'capabilities', 'list'], {
    ACCESS_KIT_MOCK_MODE: 'capabilities-terminal',
    ACCESS_KIT_MOCK_TRACE: '0',
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.includes('\u001b'), false);
  assert.equal(result.stdout.includes('\u202e'), false);
  assert.equal(result.stdout.split('\n').length, 6);
  assert.doesNotMatch(result.stdout, /^forged/m);
  assert.match(result.stdout, /safe\\u\{a\}forged\\u\{1b\}\[31mred\\u\{1b\}\[0m/);
  assert.match(result.stdout, /\[tool\\u\{1b\}\[2J\\u\{202e\}hidden\]/);
});

test('CLI account context returns a minimal account projection with normalized request outcome', () => {
  const result = runCli(['account', 'context', '--json']);
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.deepEqual(output.account, {
    name: 'CLI account',
    plan: { plan_id: 'starter', display_name: 'Starter', monthly_quota: 100, burst_rpm: 10 },
    billing: { subscription_status: 'active', current_period_end: '2026-11-01' },
    api_key_count: 2,
    is_admin: false,
  });
  assert.equal(output.interaction.status_class, 'successful');
  assert.equal(output.interaction.request_id, 'cli-request-id');
  assert.equal(JSON.stringify(output).includes('tenant-private'), false);
  assert.equal(JSON.stringify(output).includes('private-graph'), false);
  assert.equal(JSON.stringify(output).includes('private@example.test'), false);
  assert.equal(JSON.stringify(output).includes('cus_private'), false);
  assert.match(result.stderr, /MOCK_FETCH GET \/v1\/me redirect=error/);
});

test('CLI observe returns server decisions, reference fields, and the shared interaction envelope', () => {
  const result = runCli([
    'ingest', 'onboarding_step_completed', '--event-id', 'evt-cli', '--session-id', 'sess-cli',
    '--anonymous-id', 'anon-cli', '--sequence', '0', '--json',
  ], {
    AETHER_API_KEY: '',
    AETHER_PUBLISHABLE_KEY: 'pk_cli-test',
    AETHER_SITE_ID: 'site-cli',
  });
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.accepted, 1);
  assert.equal(output.events[0].status, 'accepted');
  assert.equal(output.batchId, 'batch-cli');
  assert.equal(output.interaction.operation, 'observe');
  assert.equal(output.interaction.status_class, 'successful');
  assert.equal(output.interaction.references.batchId, 'batch-cli');
  assert.match(result.stderr, /MOCK_FETCH POST \/v1\/batch redirect=error/);
});
