import { createHash, createHmac } from 'node:crypto';

export function mcpServiceAssertionHeaders({ method, url, token, secret, now = Date.now() }) {
  if (typeof secret !== 'string' || !/^[a-f0-9]{64}$/.test(secret)) {
    throw new Error('AETHER_MCP_SERVICE_ASSERTION_KEY must be a 32-byte hex key for delegated MCP calls.');
  }
  const target = `${url.pathname}${url.search}`;
  const timestamp = String(Math.floor(now / 1000));
  const tokenHash = createHash('sha256').update(token).digest('hex');
  const message = `${method.toUpperCase()}\n${target}\n${tokenHash}\n${timestamp}`;
  const signature = createHmac('sha256', Buffer.from(secret, 'hex')).update(message).digest('hex');
  return {
    'x-aether-mcp-service-timestamp': timestamp,
    'x-aether-mcp-service-signature': signature,
  };
}
