/**
 * Capture evidence about an incoming request so Aether can tell whether an AI
 * agent or crawler sent it — including agents that never run JavaScript, which
 * the browser SDK cannot see.
 *
 *   aether.track({
 *     type: 'page',
 *     properties: { path: req.url },
 *     context: { requestEvidence: captureRequestEvidence(req) },
 *   });
 *
 * Aether verifies the evidence at ingestion (provider-published IP ranges, Web
 * Bot Auth / RFC 9421 signatures) and then discards the raw values: the client
 * IP and signature headers are never stored. Results are labelled as observed
 * by your server, one step below what Aether observes directly.
 *
 * Only presence-level request metadata is read: user-agent, client IP, method,
 * host, path, query and the three HTTP Message Signature headers. No bodies,
 * cookies or authorization headers.
 */

import type { RequestEvidence } from '@olympuslabs/aether-shared';

export type { RequestEvidence };

/** Minimal shape of a Node `http.IncomingMessage` (Express, Fastify raw, Next pages API). */
interface NodeLikeRequest {
  method?: string;
  url?: string;
  headers: Record<string, string | string[] | undefined>;
  socket?: { remoteAddress?: string; encrypted?: boolean };
}

/** Minimal shape of a Fetch API `Request` (Next route handlers, Workers, Deno, Bun). */
interface FetchLikeRequest {
  method: string;
  url: string;
  headers: { get(name: string): string | null };
}

export interface CaptureRequestEvidenceOptions {
  /**
   * Client IP you have already resolved (for example Express `req.ip` with
   * `trust proxy` configured). Takes precedence over everything else.
   */
  clientIp?: string;
  /**
   * Read the client IP from the left-most `X-Forwarded-For` entry. Enable this
   * only when your server sits behind a proxy you control that sets the header;
   * otherwise any client can choose the IP Aether checks.
   */
  trustForwardedFor?: boolean;
  /** Override the receive time (defaults to now). */
  receivedAt?: Date;
}

const MAX_FIELD = 4096;

function clip(value: string | null | undefined): string | undefined {
  if (value === null || value === undefined) return undefined;
  const trimmed = String(value).trim();
  return trimmed ? trimmed.slice(0, MAX_FIELD) : undefined;
}

function isFetchRequest(req: NodeLikeRequest | FetchLikeRequest): req is FetchLikeRequest {
  return typeof (req.headers as { get?: unknown }).get === 'function';
}

function nodeHeader(req: NodeLikeRequest, name: string): string | undefined {
  const value = req.headers[name.toLowerCase()];
  if (Array.isArray(value)) return clip(value.join(', '));
  return clip(value);
}

function stripIpv6Mapped(ip: string | undefined): string | undefined {
  if (!ip) return undefined;
  return ip.startsWith('::ffff:') ? ip.slice(7) : ip;
}

/**
 * Build `context.requestEvidence` for one incoming request. Never throws; a
 * request it cannot read yields evidence with only `receivedAt`.
 */
export function captureRequestEvidence(
  req: NodeLikeRequest | FetchLikeRequest,
  options: CaptureRequestEvidenceOptions = {},
): RequestEvidence {
  const evidence: RequestEvidence = {
    receivedAt: (options.receivedAt ?? new Date()).toISOString(),
  };
  try {
    const header = isFetchRequest(req)
      ? (name: string) => clip(req.headers.get(name))
      : (name: string) => nodeHeader(req, name);

    let authority = header('host');
    let path: string | undefined;
    let query: string | undefined;
    let scheme: string | undefined;
    if (isFetchRequest(req)) {
      const url = new URL(req.url);
      authority = authority ?? url.host;
      path = url.pathname;
      query = url.search ? url.search.slice(1) : undefined;
      scheme = url.protocol.replace(':', '');
    } else {
      const raw = req.url ?? '/';
      const q = raw.indexOf('?');
      path = q >= 0 ? raw.slice(0, q) : raw;
      query = q >= 0 ? raw.slice(q + 1) || undefined : undefined;
      scheme = req.socket?.encrypted ? 'https' : undefined;
    }
    if (options.trustForwardedFor) {
      scheme = header('x-forwarded-proto')?.split(',')[0]?.trim() ?? scheme;
    }

    let clientIp = clip(options.clientIp);
    if (!clientIp && options.trustForwardedFor) {
      clientIp = header('x-forwarded-for')?.split(',')[0]?.trim();
    }
    if (!clientIp && !isFetchRequest(req)) {
      clientIp = stripIpv6Mapped(req.socket?.remoteAddress);
    }

    const fields: Partial<RequestEvidence> = {
      userAgent: header('user-agent'),
      clientIp,
      method: clip(req.method)?.toUpperCase(),
      authority,
      path: clip(path),
      query: clip(query),
      scheme: clip(scheme ?? 'https'),
      signature: header('signature'),
      signatureInput: header('signature-input'),
      signatureAgent: header('signature-agent'),
    };
    for (const [key, value] of Object.entries(fields)) {
      if (value !== undefined) (evidence as unknown as Record<string, string>)[key] = value;
    }
  } catch {
    // Evidence capture must never break the host application.
  }
  return evidence;
}
