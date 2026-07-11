// HTTP batch transport with retry on 429 / 5xx.

export interface TransportConfig {
  endpoint: string;
  writeKey: string;
  timeoutMs?: number;
  userAgent?: string;
}

export interface TransportResult {
  ok: boolean;
  status: number;
  retryAfterMs?: number;
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

    return { ok: res.ok, status: res.status, retryAfterMs };
  } catch {
    return { ok: false, status: 0 };
  } finally {
    clearTimeout(tid);
  }
}
