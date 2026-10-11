import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const bridgePath = fileURLToPath(new URL('../bin/aether-mcp.js', import.meta.url));

function waitForResponse(child, pending, id) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Timed out waiting for MCP response ${id}.`));
    }, 5_000);
    pending.set(id, (message) => {
      clearTimeout(timer);
      resolve(message);
    });
    child.once('error', (error) => {
      clearTimeout(timer);
      pending.delete(id);
      reject(error);
    });
  });
}

test('pinned MCP stdio SDK initializes and lists tools without making API calls', async (t) => {
  const child = spawn(process.execPath, [bridgePath], {
    env: {
      ...process.env,
      AETHER_API_KEY: '',
      AETHER_API_URL: 'https://api.example.test',
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  t.after(() => {
    if (child.exitCode === null && !child.killed) child.kill('SIGKILL');
  });

  const pending = new Map();
  let buffer = '';
  let stderr = '';
  child.stdout.setEncoding('utf8').on('data', (chunk) => {
    buffer += chunk;
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (!line.trim()) continue;
      const message = JSON.parse(line);
      if (message.id !== undefined) pending.get(message.id)?.(message);
    }
  });
  child.stderr.setEncoding('utf8').on('data', (chunk) => { stderr += chunk; });

  const initializeResponse = waitForResponse(child, pending, 1);
  child.stdin.write(`${JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: {
      protocolVersion: '2025-03-26',
      capabilities: {},
      clientInfo: { name: 'access-kit-smoke', version: '0.0.0' },
    },
  })}\n`);
  const initialized = await initializeResponse;
  assert.equal(initialized.id, 1);
  assert.equal(initialized.error, undefined, JSON.stringify(initialized.error));
  assert.equal(typeof initialized.result.protocolVersion, 'string');

  child.stdin.write(`${JSON.stringify({
    jsonrpc: '2.0', method: 'notifications/initialized',
  })}\n`);
  const listResponse = waitForResponse(child, pending, 2);
  child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list' })}\n`);
  const listed = await listResponse;
  assert.equal(listed.error, undefined, JSON.stringify(listed.error));
  const names = listed.result.tools.map((tool) => tool.name);
  assert.ok(names.includes('entities_list'));
  assert.ok(names.includes('entities_get'));
  assert.ok(names.includes('account_context'));
  assert.ok(names.includes('observe'));
  child.stdin.end();
  const [exitCode] = await once(child, 'exit');
  assert.equal(exitCode, 0, stderr);
});
