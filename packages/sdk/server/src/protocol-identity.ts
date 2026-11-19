/**
 * Agent identity from agent protocols (MCP, A2A), for events your MCP server or
 * A2A agent sends to Aether.
 *
 *   // MCP (TypeScript SDK): inside a tool handler, `extra.authInfo` is set only
 *   // after your auth middleware verified the bearer token.
 *   aether.track({
 *     type: 'agent_tool_called',
 *     context: { agentProtocol: captureMcpClientIdentity({
 *       clientInfo: server.getClientVersion(),
 *       authInfo: extra.authInfo,
 *     }) },
 *   });
 *
 *   // A2A: after your server authenticated the caller.
 *   aether.track({
 *     type: 'agent_task_received',
 *     context: { agentProtocol: captureA2aCallerIdentity({
 *       agentCard: callerCard, authenticated: true, authScheme: 'oauth2',
 *     }) },
 *   });
 *
 * Tokens are never sent. The OAuth subject (the user who authorized the
 * client) is SHA-256-hashed here, before it leaves your server. Only identity
 * fields of an Agent Card are kept. Aether grades the result as observed by your
 * server.
 */

import { createHash } from 'node:crypto';

import type { AgentProtocolEvidence } from '@olympuslabs/aether-shared';

export type { AgentProtocolEvidence };

const MAX = 256;

function s(value: unknown, limit = MAX): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, limit) : undefined;
}

function prune<T extends Record<string, unknown>>(obj: T): T {
  for (const key of Object.keys(obj)) {
    const value = obj[key];
    if (value === undefined || (typeof value === 'object' && value !== null && !Array.isArray(value) && Object.keys(value).length === 0)) {
      delete obj[key];
    }
  }
  return obj;
}

export function sha256Hex(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

/** Shape of the MCP TypeScript SDK's `AuthInfo` (only the fields read here). */
export interface McpAuthInfoLike {
  clientId?: string;
  scopes?: string[];
  /** Never read or sent. */
  token?: string;
  extra?: Record<string, unknown>;
}

export interface CaptureMcpClientIdentityInput {
  /** `clientInfo` from the MCP `initialize` request (e.g. `server.getClientVersion()`). */
  clientInfo?: { name?: string; version?: string } | null;
  protocolVersion?: string;
  /**
   * Pass only when your auth middleware verified the bearer token (the MCP SDK
   * sets `extra.authInfo` only then). Its presence marks the client verified.
   */
  authInfo?: McpAuthInfoLike | null;
  /** Token issuer, if known (e.g. from the validated JWT `iss`). */
  issuer?: string;
  /** Token subject (validated JWT `sub`). Hashed before sending. */
  subject?: string;
}

export function captureMcpClientIdentity(input: CaptureMcpClientIdentityInput): AgentProtocolEvidence {
  const auth = input.authInfo ?? undefined;
  const extra = (auth?.extra ?? {}) as Record<string, unknown>;
  const subject = s(input.subject) ?? s(extra.sub) ?? s(extra.subject);
  const issuer = s(input.issuer, 2048) ?? s(extra.iss, 2048) ?? s(extra.issuer, 2048);
  const clientId = s(auth?.clientId);
  const mcp = prune({
    clientInfo: prune({ name: s(input.clientInfo?.name), version: s(input.clientInfo?.version, 64) }),
    protocolVersion: s(input.protocolVersion, 32),
    oauth: auth
      ? prune({
          verified: clientId !== undefined,
          clientId,
          issuer,
          scopes: Array.isArray(auth.scopes) ? auth.scopes.filter((x) => typeof x === 'string').slice(0, 32) : undefined,
          subjectHash: subject ? sha256Hex(subject) : undefined,
        })
      : undefined,
  });
  return { protocol: 'mcp', mcp };
}

export interface CaptureA2aCallerIdentityInput {
  /** The caller's Agent Card (only identity fields are kept). */
  agentCard?: Record<string, unknown> | null;
  /** Where the card was fetched from, if you fetched it. */
  agentCardUrl?: string;
  /** True when the caller satisfied the security scheme your Agent Card declares. */
  authenticated?: boolean;
  /** True when your server verified the caller's Agent Card JWS signature. */
  cardSignatureVerified?: boolean;
  authScheme?: string;
}

export function captureA2aCallerIdentity(input: CaptureA2aCallerIdentityInput): AgentProtocolEvidence {
  const card = (input.agentCard ?? {}) as Record<string, unknown>;
  const provider = (card.provider ?? {}) as Record<string, unknown>;
  const a2a = prune({
    agentCard: prune({
      name: s(card.name),
      url: s(card.url, 2048),
      version: s(card.version, 64),
      protocolVersion: s(card.protocolVersion, 32),
      provider: prune({ organization: s(provider.organization), url: s(provider.url, 2048) }),
    }),
    agentCardUrl: s(input.agentCardUrl, 2048),
    authenticated: input.authenticated === true ? true : undefined,
    cardSignatureVerified: input.cardSignatureVerified === true ? true : undefined,
    authScheme: s(input.authScheme, 64),
  });
  return { protocol: 'a2a', a2a };
}
