import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { readConfig, slotsExposingData, STEPS } from '../scripts/w3-certify.mjs';

const script = fileURLToPath(new URL('../scripts/w3-certify.mjs', import.meta.url));
const good = {
  AETHER_API_URL: 'https://api.staging.example.test',
  AETHER_W3_TENANT_A_KEY: 'key-a',
  AETHER_W3_TENANT_A_ADMIN_KEY: 'admin-a',
  AETHER_W3_TENANT_B_KEY: 'key-b',
  AETHER_W3_PUBLISHABLE_KEY: 'pk_test',
  AETHER_W3_SITE_ID: 'site-1',
};

test('plan lists every certification step without network access', () => {
  const result = spawnSync(process.execPath, [script, '--plan'], { encoding: 'utf8', env: {} });
  assert.equal(result.status, 0, result.stderr);
  const plan = JSON.parse(result.stdout);
  assert.deepEqual(plan.steps, [...STEPS]);
  assert.ok(plan.steps.includes('cross_tenant_denial'));
  assert.ok(plan.steps.includes('profile360_frame_hosted_mcp'));
});

test('configuration fails closed', () => {
  assert.throws(() => readConfig({}), /Missing required environment/);
  assert.throws(() => readConfig({ ...good, AETHER_W3_TENANT_B_KEY: 'key-a' }), /must differ/);
  assert.throws(() => readConfig({ ...good, AETHER_API_URL: 'http://api.example.test' }), /HTTPS/);
  assert.throws(() => readConfig({ ...good, AETHER_W3_RESOLVE_TIMEOUT_S: '5' }), /10 to 3600/);
  const config = readConfig({ ...good, AETHER_MCP_URL: 'https://api.staging.example.test/v1/access/mcp' });
  assert.equal(config.apiUrl, 'https://api.staging.example.test');
  assert.equal(config.mcpUrl, 'https://api.staging.example.test/v1/access/mcp');
  assert.equal(config.resolveTimeoutSeconds, 300);
});

test('a run without credentials exits non-zero before any request', () => {
  const result = spawnSync(process.execPath, [script], { encoding: 'utf8', env: { PATH: process.env.PATH } });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Missing required environment/);
});

test('reconciliation uses the separate admin key; access checks keep the read key', () => {
  const config = readConfig(good);
  assert.equal(config.keyA, 'key-a');
  assert.equal(config.adminKeyA, 'admin-a');
  const { AETHER_W3_TENANT_A_ADMIN_KEY: _omit, ...withoutAdmin } = good;
  assert.throws(() => readConfig(withoutAdmin), /AETHER_W3_TENANT_A_ADMIN_KEY/);
});

test('cross-tenant leak check flags data in any slot state, including degraded', () => {
  const frame = {
    slots: [
      { id: 'identity_spine', state: 'suppressed' },
      { id: 'risk_summary', state: 'degraded', content: { level: 'high' } },
      { id: 'relationships', state: 'unknown', evidenceRefs: ['ev-1'] },
      { id: 'value_summary', state: 'partial', claims: [{ id: 'c1' }] },
      { id: 'communications', state: 'unknown', content: null, evidenceRefs: [], claims: [] },
    ],
  };
  assert.deepEqual(slotsExposingData(frame), ['risk_summary', 'relationships', 'value_summary']);
  assert.deepEqual(slotsExposingData({ slots: [{ id: 'a', state: 'suppressed' }] }), []);
});
