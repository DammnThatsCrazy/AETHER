#!/usr/bin/env node

import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import * as z from 'zod/v4';

import {
  AccessApiError,
  getCapabilityOverview,
  ingestTrackObservation,
  listCapabilities,
} from '../src/api.mjs';

const capabilitySchema = z.object({
  capability_id: z.string(),
  capability_kind: z.string(),
  provider: z.string().nullable(),
  server_name: z.string().nullable(),
  tool_name: z.string().nullable(),
  protocol_version: z.string().nullable(),
  latest_risk_level: z.string().nullable(),
  discovery_state: z.string(),
  first_seen_at: z.string().nullable(),
  last_seen_at: z.string().nullable(),
  observation_count: z.number().int(),
});

function safeCapability(row) {
  return {
    capability_id: row.capability_id,
    capability_kind: row.capability_kind ?? 'unknown',
    provider: row.provider ?? null,
    server_name: row.server_name ?? null,
    tool_name: row.tool_name ?? null,
    protocol_version: row.protocol_version ?? null,
    latest_risk_level: row.latest_risk_level ?? null,
    discovery_state: row.discovery_state ?? 'observed',
    first_seen_at: row.first_seen_at ?? null,
    last_seen_at: row.last_seen_at ?? null,
    observation_count: Number.isInteger(row.observation_count) ? row.observation_count : 0,
  };
}

function toolError(error) {
  const requestId = error?.requestId ? ` Request: ${error.requestId}.` : '';
  const message = error instanceof AccessApiError
    ? `${error.message}${requestId}`
    : 'The Aether API operation could not be completed.';
  return { content: [{ type: 'text', text: message }], isError: true };
}

function createServer() {
  const server = new McpServer({ name: 'aether-access-kit', version: '0.1.0-alpha.0' });

  server.registerTool(
    'agent_access_capabilities_list',
    {
      title: 'List observed agent access capabilities',
      description: 'Read this tenant’s observed third-party agent access inventory. These records are evidence, not grants or executable Aether tools. Tenant scope comes from AETHER_API_KEY.',
      inputSchema: z.object({
        provider: z.string().optional(),
        server_name: z.string().optional(),
        tool_name: z.string().optional(),
        limit: z.number().int().min(1).max(100).optional(),
        offset: z.number().int().min(0).max(100_000).optional(),
      }),
      outputSchema: z.object({
        items: z.array(capabilitySchema),
        returned_count: z.number().int(),
        request_id: z.string(),
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ provider, server_name, tool_name, limit, offset }) => {
      try {
        const result = await listCapabilities({
          provider,
          serverName: server_name,
          toolName: tool_name,
          limit: limit ?? 100,
          offset: offset ?? 0,
        });
        const items = (Array.isArray(result.data?.items) ? result.data.items : []).map(safeCapability);
        const output = { items, returned_count: items.length, request_id: result.requestId };
        return {
          content: [{ type: 'text', text: JSON.stringify(output) }],
          structuredContent: output,
        };
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    'agent_access_capabilities_overview',
    {
      title: 'Summarize observed capabilities',
      description: 'Read this tenant’s observed third-party agent access inventory summary. This does not grant or invoke any Aether capability.',
      outputSchema: z.object({
        summary: z.record(z.string(), z.unknown()),
        request_id: z.string(),
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      try {
        const result = await getCapabilityOverview();
        const output = { summary: result.data ?? {}, request_id: result.requestId };
        return {
          content: [{ type: 'text', text: JSON.stringify(output) }],
          structuredContent: output,
        };
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    'observe',
    {
      title: 'Send a canonical observation',
      description: 'Send one custom application track event through Aether POST /v1/batch. Configure AETHER_PUBLISHABLE_KEY and its bound AETHER_SITE_ID. Aether validates the event and returns accepted, duplicate, or rejected decisions; no tenant override is accepted.',
      inputSchema: z.object({
        event_name: z.string().trim().min(1).max(128),
        event_id: z.string().trim().min(1).max(128),
        session_id: z.string().trim().min(1).max(256),
        anonymous_id: z.string().trim().min(1).max(256),
        sequence: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
        properties: z.record(z.string(), z.unknown()).optional(),
      }),
      outputSchema: z.object({
        accepted: z.number().int(),
        duplicates: z.number().int(),
        rejected: z.number().int(),
        events: z.array(z.object({
          id: z.string(),
          status: z.enum(['accepted', 'duplicate', 'rejected']),
          reason: z.string().nullable().optional(),
        })),
        batchId: z.string(),
        receivedAt: z.string(),
        request_id: z.string(),
      }),
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
    },
    async ({ event_name, event_id, session_id, anonymous_id, sequence, properties }) => {
      try {
        const result = await ingestTrackObservation({
          eventName: event_name,
          eventId: event_id,
          sessionId: session_id,
          anonymousId: anonymous_id,
          eventSequence: sequence,
          properties,
          surface: 'mcp',
        });
        const output = { ...result.data, request_id: result.requestId };
        return {
          content: [{ type: 'text', text: JSON.stringify(output) }],
          structuredContent: output,
        };
      } catch (error) {
        return toolError(error);
      }
    },
  );

  return server;
}

try {
  await serveStdio(createServer);
} catch (error) {
  process.stderr.write(`Aether MCP bridge could not start: ${error.message}\n`);
  process.exitCode = 1;
}
