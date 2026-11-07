#!/usr/bin/env node

import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import { pathToFileURL } from 'node:url';
import * as z from 'zod/v4';

import {
  AccessApiError,
  ingestTrackObservation,
  projectObservedCapability,
} from '../src/api.mjs';
import { registerEntityTools } from '../src/entity-tools.mjs';
import { registerAccountContextTool } from '../src/account-context-tools.mjs';
import { registerAccessOperationTools } from '../src/access-operation-tools.mjs';
import { registerContinuationTools } from '../src/continuation-tools.mjs';
import { registerAgentBehaviorTools } from '../src/agent-behavior-tools.mjs';
import { invokeAccessOperation } from '../src/access-operations.mjs';
import { interactionSchema } from '../src/interaction-schema.mjs';
import { loadMcpStoredSession } from '../src/mcp-auth.mjs';

const capabilitySchema = z.object({
  capability_id: z.string().regex(/^cap_[a-f0-9]{24}$/),
  capability_kind: z.string().max(64),
  provider: z.string().max(128).nullable(),
  server_name: z.string().max(128).nullable(),
  tool_name: z.string().max(128).nullable(),
  protocol_version: z.string().max(64).nullable(),
  latest_risk_level: z.string().max(64).nullable(),
  discovery_state: z.string().max(64),
  first_seen_at: z.string().max(64).nullable(),
  last_seen_at: z.string().max(64).nullable(),
  observation_count: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
});

const bucketMapSchema = z.record(z.string().max(64),
  z.number().int().min(0).max(Number.MAX_SAFE_INTEGER));
const capabilityOverviewSchema = z.object({
  capability_count: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
  installation_count: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
  by_kind: bucketMapSchema,
  by_provider: bucketMapSchema,
  sampled: z.boolean(),
});

export const observeOutputSchema = z.object({
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
  api_request_id: z.string().optional(),
  usageEventId: z.string().optional(),
  usageEvidenceId: z.string().optional(),
  auditEventId: z.string().optional(),
  interaction: interactionSchema,
});

export function buildObserveOutput(result) {
  return observeOutputSchema.parse({
    ...result.data,
    request_id: result.requestId,
    ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
    interaction: result.interaction,
  });
}

function toolError(error) {
  const requestId = error?.requestId ? ` Request: ${error.requestId}.` : '';
  const apiRequestId = error?.apiRequestId ? ` API request: ${error.apiRequestId}.` : '';
  const message = error instanceof AccessApiError
    ? `${error.message}${requestId}${apiRequestId}`
    : 'The Aether API operation could not be completed.';
  const details = error instanceof AccessApiError
    ? {
      message: error.message,
      ...(Number.isInteger(error.status) ? { status: error.status } : {}),
      ...(error.code ? { code: error.code } : {}),
      ...(error.requestId ? { request_id: error.requestId } : {}),
      ...(error.apiRequestId ? { api_request_id: error.apiRequestId } : {}),
      ...(error.interaction ? { interaction: error.interaction } : {}),
    }
    : { message };
  return { content: [{ type: 'text', text: JSON.stringify({ error: details }) }], isError: true };
}

export function createAccessMcpServer(
  env = process.env,
  { includeObserve = true, surface = 'mcp_stdio' } = {},
) {
  const accessEnv = { ...env, AETHER_ACCESS_SURFACE: surface };
  const server = new McpServer({ name: 'aether-access-kit', version: '0.1.0-alpha.0' });
  registerEntityTools(server, {
    list: (args) => invokeAccessOperation('entities.list', {
      entity_type: args.entityType,
      limit: args.limit,
      offset: args.offset,
    }, accessEnv),
    get: (entityId) => invokeAccessOperation('entities.get', { entity_id: entityId }, accessEnv),
    neighborhood: (entityId, args) => invokeAccessOperation('entities.neighborhood', {
      entity_id: entityId, limit: args.limit,
    }, accessEnv),
  });
  registerAccountContextTool(server, {
    get: () => invokeAccessOperation('account.context', {}, accessEnv),
  });
  registerAccessOperationTools(server, accessEnv);
  // The delegated MCP OAuth token carries a read-only scope. Do not even
  // advertise continuation state tools to that caller; API key and human
  // session callers still receive server-side read/write permission checks.
  if (!accessEnv.AETHER_MCP_OAUTH_TOKEN) registerContinuationTools(server, accessEnv);
  // Agent behavior reads require agent:manage, which the read-only delegated
  // OAuth scope never carries; advertise them only to API key and session callers.
  if (!accessEnv.AETHER_MCP_OAUTH_TOKEN) registerAgentBehaviorTools(server, {
    behavior: (agentRef) => invokeAccessOperation('agents.behavior', { agent_ref: agentRef }, accessEnv),
    decision: (agentRef, decisionId) => invokeAccessOperation('agents.decision', {
      agent_ref: agentRef, decision_id: decisionId,
    }, accessEnv),
  });

  server.registerTool(
    'agent_access_capabilities_list',
    {
      title: 'List observed agent access capabilities',
      description: 'Read this tenant’s observed third-party agent access inventory. These records are evidence, not grants or executable Aether tools. Tenant scope comes from one explicit AETHER_API_KEY or AETHER_SESSION_TOKEN, or from the local OS credential store after aether auth login.',
      inputSchema: z.object({
        provider: z.string().optional(),
        server_name: z.string().optional(),
        tool_name: z.string().optional(),
        limit: z.number().int().min(1).max(100).optional(),
        offset: z.number().int().min(0).max(100_000).optional(),
      }),
      outputSchema: z.object({
        items: z.array(capabilitySchema).max(100),
        returned_count: z.number().int().min(0).max(100),
        request_id: z.string(),
        api_request_id: z.string().optional(),
        interaction: interactionSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ provider, server_name, tool_name, limit, offset }) => {
      try {
        const result = await invokeAccessOperation('agent_access.observed.list', {
          provider,
          server_name,
          tool_name,
          limit: limit ?? 100,
          offset: offset ?? 0,
        }, accessEnv);
        const items = (Array.isArray(result.data?.items) ? result.data.items : [])
          .map(projectObservedCapability)
          .filter(Boolean)
          .slice(0, 100);
        const output = {
          items,
          returned_count: items.length,
          request_id: result.requestId,
          ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
          interaction: result.interaction,
        };
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
        summary: capabilityOverviewSchema,
        request_id: z.string(),
        api_request_id: z.string().optional(),
        interaction: interactionSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      try {
        const result = await invokeAccessOperation('agent_access.observed.overview', {}, accessEnv);
        const output = {
          summary: result.data ?? {},
          request_id: result.requestId,
          ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
          interaction: result.interaction,
        };
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
    'usage_summary',
    {
      title: 'Read Access Kit usage summary',
      description: 'Read the authenticated tenant’s non-billable Access Kit interaction count for the current billing period. This is a read-only projection of Aether billing usage and does not expose other usage dimensions or tenant identifiers.',
      inputSchema: z.object({}).strict(),
      outputSchema: z.object({
        usage: z.object({
          access_interaction_count: z.number().nonnegative(),
          billing_period_start: z.string().nullable(),
          billing_period_end: z.string().nullable(),
          status: z.enum(['available', 'truncated', 'unavailable']),
        }),
        request_id: z.string(),
        api_request_id: z.string().optional(),
        interaction: interactionSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async () => {
      try {
        const result = await invokeAccessOperation('usage.summary', {}, accessEnv);
        const output = {
          usage: result.data,
          request_id: result.requestId,
          ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
          interaction: result.interaction,
        };
        return {
          content: [{ type: 'text', text: JSON.stringify(output) }],
          structuredContent: output,
        };
      } catch (error) {
        return toolError(error);
      }
    },
  );

  if (includeObserve) server.registerTool(
    'observe',
    {
      title: 'Send a canonical observation',
      description: 'Send one custom application track event through Aether POST /v1/batch. For local stdio, configure AETHER_PUBLISHABLE_KEY and its bound AETHER_SITE_ID. For hosted MCP, provide request-scoped X-Aether-Observe-Key and X-Aether-Site-ID headers on each MCP request. Aether validates the key/site binding and returns accepted, duplicate, or rejected decisions; no tenant override is accepted.',
      inputSchema: z.object({
        event_name: z.string().trim().min(1).max(128),
        event_id: z.string().trim().min(1).max(128),
        session_id: z.string().trim().min(1).max(256),
        anonymous_id: z.string().trim().min(1).max(256),
        sequence: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
        properties: z.record(z.string(), z.unknown()).optional(),
      }),
      outputSchema: observeOutputSchema,
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
        }, accessEnv);
        const output = buildObserveOutput(result);
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

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    await loadMcpStoredSession(process.env);
    await serveStdio(() => createAccessMcpServer(process.env));
  } catch (error) {
    process.stderr.write(`Aether MCP bridge could not start: ${error.message}\n`);
    process.exitCode = 1;
  }
}
