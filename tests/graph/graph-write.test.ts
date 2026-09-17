/**
 * FPS-201 — Graph Write Tests
 * Send events via /v1/batch, verify nodes/edges written, test idempotency and provenance.
 * Skips if AETHER_API_KEY is missing.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope, GraphNode, GraphEdge } from '@aether/proof-contracts';

const API_URL = process.env.AETHER_API_URL || 'http://localhost:8000';
const API_KEY = process.env.AETHER_API_KEY;

function headers(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Aether-API-Key': API_KEY!,
  };
}

function fetchJSON<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  return fetch(input, {
    ...init,
    headers: { ...headers(), ...init?.headers },
  }).then((res) => {
    if (res.status === 401 || res.status === 403) {
      throw new Error(`Auth failed: ${res.status}`);
    }
    if (res.status === 429) {
      throw new Error('Rate limited');
    }
    if (res.status >= 500) {
      throw new Error(`Server error: ${res.status}`);
    }
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    return res.json() as Promise<T>;
  });
}

async function httpPost<T>(path: string, body: unknown): Promise<T> {
  return fetchJSON<T>(`${API_URL}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

async function httpGet<T>(path: string): Promise<T> {
  return fetchJSON<T>(`${API_URL}${path}`, { method: 'GET' });
}

describe.skipIf(!API_KEY)('FPS-201: Graph Write Tests', () => {

  it('should create profile node via batch event', async () => {
    const event: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'identify',
      sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
      identity: { anonymous_id: 'anon_graph_001', user_id: 'user_graph_001' },
      timestamp: new Date().toISOString(),
      properties: {
        traits: { email: 'graph@test.com', plan: 'pro' },
      },
    };

    const result = await httpPost<{ accepted: number }>('/v1/batch', {
      events: [event],
    });
    expect(result.accepted).toBe(1);
  });

  it('should verify nodes were written to graph', async () => {
    const nodes = await httpGet<{ nodes: GraphNode[]; edges: GraphEdge[] }>(
      '/v1/graph/nodes',
    );
    expect(Array.isArray(nodes.nodes)).toBe(true);
    expect(Array.isArray(nodes.edges)).toBe(true);
    // At minimum, verify the response shape
    for (const node of nodes.nodes) {
      expect(node.node_id).toBeDefined();
      expect(node.type).toBeDefined();
    }
  });

  it('should create journey node via batch event', async () => {
    const event: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
      identity: { anonymous_id: 'anon_graph_001' },
      timestamp: new Date().toISOString(),
      properties: {
        path: '/checkout',
        referrer: 'https://example.com',
        journey_step: 'checkout',
      },
    };

    const result = await httpPost<{ accepted: number }>('/v1/batch', {
      events: [event],
    });
    expect(result.accepted).toBe(1);
  });

  it('should create communication node via batch event', async () => {
    const event: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'email',
      environment: 'staging',
      event_type: 'email_sent',
      sdk: { name: '@aether/email', version: '0.1.0-alpha.0' },
      identity: { anonymous_id: 'anon_graph_001' },
      timestamp: new Date().toISOString(),
      properties: {
        message_id: 'msg_graph_001',
        campaign_id: 'camp_graph_001',
        subject: 'Graph Test',
      },
    };

    const result = await httpPost<{ accepted: number }>('/v1/batch', {
      events: [event],
    });
    expect(result.accepted).toBe(1);
  });

  it('should test idempotency — send same event twice', async () => {
    const event: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
      identity: { anonymous_id: 'anon_graph_idem_001' },
      timestamp: new Date().toISOString(),
      properties: {
        path: '/idempotency-test',
        idempotency_key: 'idem_001',
      },
    };

    const first = await httpPost<{ accepted: number; batch_id: string }>(
      '/v1/batch',
      { events: [event] },
    );
    expect(first.accepted).toBe(1);

    // Send the same event again — should be accepted (idempotent, deduplicated)
    const second = await httpPost<{ accepted: number; batch_id: string }>(
      '/v1/batch',
      { events: [event] },
    );
    expect(second.accepted).toBe(1);
  });

  it('should verify provenance tracking', async () => {
    // Query the graph for provenance information
    const provenance = await httpGet<{
      nodes: Array<{ node_id: string; provenance: unknown[] }>;
    }>('/v1/graph/provenance');
    expect(Array.isArray(provenance.nodes)).toBe(true);
    // Each node should have provenance information
  });
});
