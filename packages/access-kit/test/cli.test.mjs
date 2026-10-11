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
    'request_id', 'api_request_id',
  ]);
  assert.equal(output.display_name, 'CLI test entity');
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
  assert.match(failure.message, /HTTP 403, permission_denied/);
  assert.equal(result.stdout, '');
});
