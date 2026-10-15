// HTTP batch transport with retry on 429 / 5xx.

export interface TransportConfig {
  endpoint: string;
  writeKey: string;
  timeoutMs?: number;
  userAgent?: string;
}

/** Acceptance counters parsed from the backend BatchResponse. */
export interface IngestCounters {
  accepted: number;
  duplicate: number;
  rejected: number;
}

export interface TransportResult {
  ok: boolean;
  status: number;
  retryAfterMs?: number;
  /** Present on a 2xx response whose body carried acceptance counters. */
  counters?: IngestCounters;
}

/**
 * Parse per-batch acceptance counters from a /v1/batch response body.
 * The backend BatchResponse uses `accepted` / `duplicates` / `rejected`
 * (packages/shared/ingestion-contract.ts); the singular `duplicate` is also
 * accepted. Returns undefined when the body carries none of them.
 */
export function parseIngestCounters(body: unknown): IngestCounters | undefined {
  if (!body || typeof body !== 'object') return undefined;
  const rec = body as Record<string, unknown>;
  const num = (v: unknown): number | undefined =>
    typeof v === 'number' && Number.isFinite(v) ? v : undefined;
  const accepted = num(rec['accepted']);
  const duplicate = num(rec['duplicate']) ?? num(rec['duplicates']);
  const rejected = num(rec['rejected']);
  if (accepted === undefined && duplicate === undefined && rejected === undefined) {
    return undefined;
  }
  return { accepted: accepted ?? 0, duplicate: duplicate ?? 0, rejected: rejected ?? 0 };
}

export async function sendBatch(
  config: TransportConfig,
  events: unknown[],
  consents: string[],
): Promise<TransportResult> {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), config.timeoutMs ?? 10_000);

  try {
    const res = await fetch(config.endpoint, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${config.writeKey}`,
        'User-Agent': config.userAgent ?? '@aether/server',
        'X-Aether-Source': 'server-sdk',
      },
      // Canonical ingestion envelope — the backend BatchRequest requires
      // `batch` (not `events`) plus `sentAt`. `consents` is an optional hint.
      body: JSON.stringify({
        batch: events,
        sentAt: new Date().toISOString(),
        consents,
      }),
    });

    const retryAfterMs = res.status === 429
      ? (parseInt(res.headers.get('Retry-After') ?? '60', 10) * 1000)
      : undefined;

    let counters: IngestCounters | undefined;
    if (res.ok && typeof res.json === 'function') {
      try {
        counters = parseIngestCounters(await res.json());
      } catch {
        // Body missing / non-JSON — leave counters undefined.
      }
    }

    return { ok: res.ok, status: res.status, retryAfterMs, counters };
  } catch {
    return { ok: false, status: 0 };
  } finally {
    clearTimeout(tid);
  }
}
