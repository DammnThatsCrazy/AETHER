import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { dataExchangeArtifactSchema } from '@aether-app/features/data-exchange';
import { dataExchangeSurfaceEnabled } from '@aether-app/features/data-exchange';
import type { DataExchangeCapabilities } from '@aether-app/features/data-exchange';
import {
  useDataExchangeCapabilities,
  useCreateDataExchangeExport,
} from '@aether-app/features/data-exchange/use-data-exchange';

/**
 * M6 Data Exchange — feature-module trust boundary.
 *
 * The Data Exchange settings surface is built against the frozen
 * `/v1/data-exchange/*` shapes in `docs/plans/data-exchange-api.md`. These
 * tests pin three properties on the wire contract:
 *   1. frozen payloads parse (field names + M0 status/direction/classification
 *      vocabulary are enforced);
 *   2. malformed payloads FAIL CLOSED (safeParse → rejection), never surfacing
 *      garbage to the UI;
 *   3. the capability gate helper resolves surface availability from
 *      `data_exchange.enabled` + flags.
 *
 * The REST client is mocked at the transport seam, mirroring the real client's
 * envelope ({ data, status, timestamp }) + zod validation.
 */

interface ParseableSchema {
  readonly parse: (value: unknown) => unknown;
}

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock('@aether-app/lib/api/rest/client', () => ({
  restClient: {
    get: mocks.get,
    post: mocks.post,
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

/** Mirror the backend `@api_response` envelope the REST client parses. */
const envelope = (data: unknown) => ({
  data,
  status: 'success',
  timestamp: '2026-08-01T00:00:00Z',
});

/** Emulate the real REST client: validate the full envelope, return parsed.data. */
function serveGet(routes: Record<string, unknown>): void {
  mocks.get.mockReset();
  mocks.get.mockImplementation(async (path: string, schema: ParseableSchema) => {
    const prefix = Object.keys(routes).find(p => path.startsWith(p));
    if (prefix === undefined) throw new Error(`unrouted GET path in test: ${path}`);
    return schema.parse(envelope(routes[prefix]));
  });
}

function servePost(path: string, payload: unknown): void {
  mocks.post.mockReset();
  mocks.post.mockImplementation(async (p: string, schema: ParseableSchema) => {
    if (p !== path) throw new Error(`unexpected POST path ${p}`);
    return schema.parse(envelope(payload));
  });
}

// ── Fixtures (frozen response shapes) ────────────────────────────────────────

const ENABLED_CAPABILITIES: DataExchangeCapabilities = {
  data_exchange: {
    enabled: true,
    flags: {
      imports_enabled: true,
      exports_enabled: true,
      reports_enabled: false,
      object_store_enabled: true,
    },
  },
  available_formats: ['csv', 'json', 'ndjson', 'parquet'],
  available_sources: ['file', 's3'],
  blocked_classifications: ['secret', 'credential'],
};

const EXPORT_ARTIFACT = {
  artifact_id: 'art_export_1',
  tenant_id: 't_1',
  direction: 'egress',
  artifact_type: 'export',
  filename: 'customers_export.ndjson',
  format: 'ndjson',
  content_type: 'application/x-ndjson',
  size_bytes: 4096,
  classification: 'pii',
  status: 'available',
  created_at: '2026-08-01T00:00:00Z',
};

const IMPORT_ARTIFACT = {
  artifact_id: 'art_import_1',
  tenant_id: 't_1',
  direction: 'ingress',
  artifact_type: 'import_source',
  filename: 'customers.csv',
  format: 'csv',
  content_type: 'text/csv',
  size_bytes: 184320,
  classification: 'identifier',
  status: 'committed',
  created_at: '2026-07-30T12:00:00Z',
};

const REPORT_ARTIFACT = {
  artifact_id: 'art_report_1',
  tenant_id: 't_1',
  direction: 'egress',
  artifact_type: 'report',
  filename: 'monthly-overview.pdf',
  format: 'pdf',
  content_type: 'application/pdf',
  size_bytes: 8192,
  classification: 'governance',
  status: 'generating',
  created_at: '2026-08-01T09:00:00Z',
};

describe('data exchange artifact schema (M0 vocabulary enforcement)', () => {
  it('parses a fully-populated frozen artifact row', () => {
    expect(dataExchangeArtifactSchema.safeParse(EXPORT_ARTIFACT).success).toBe(true);
    expect(dataExchangeArtifactSchema.safeParse(IMPORT_ARTIFACT).success).toBe(true);
    expect(dataExchangeArtifactSchema.safeParse(REPORT_ARTIFACT).success).toBe(true);
  });

  it('omitted optional fields resolve to undefined, not a parse failure', () => {
    const minimal = {
      artifact_id: 'art_min_1',
      direction: 'egress',
      artifact_type: 'export',
      classification: 'none',
      status: 'generating',
      created_at: '2026-08-01T00:00:00Z',
    };
    const parsed = dataExchangeArtifactSchema.safeParse(minimal);
    expect(parsed.success).toBe(true);
  });

  it('rejects a status outside the M0 dataArtifactStatuses tuple', () => {
    const bad = { ...EXPORT_ARTIFACT, status: 'flapping' };
    expect(dataExchangeArtifactSchema.safeParse(bad).success).toBe(false);
  });

  it('rejects a direction outside the M0 direction tuple', () => {
    const bad = { ...EXPORT_ARTIFACT, direction: 'sideways' };
    expect(dataExchangeArtifactSchema.safeParse(bad).success).toBe(false);
  });

  it('rejects a classification outside the M0 classification tuple', () => {
    const bad = { ...EXPORT_ARTIFACT, classification: 'cosmic' };
    expect(dataExchangeArtifactSchema.safeParse(bad).success).toBe(false);
  });
});

describe('capability surface gating helper', () => {
  it('is off when capabilities are absent (fails closed)', () => {
    expect(dataExchangeSurfaceEnabled(null, 'exports')).toBe(false);
    expect(dataExchangeSurfaceEnabled(undefined, 'imports')).toBe(false);
  });

  it('is off when the whole data-exchange capability is disabled', () => {
    const caps: DataExchangeCapabilities = { data_exchange: { enabled: false, flags: {} } };
    expect(dataExchangeSurfaceEnabled(caps, 'exports')).toBe(false);
    expect(dataExchangeSurfaceEnabled(caps, 'imports')).toBe(false);
    expect(dataExchangeSurfaceEnabled(caps, 'reports')).toBe(false);
    expect(dataExchangeSurfaceEnabled(caps, 'transfers')).toBe(false);
  });

  it('honors explicit surface flags', () => {
    expect(dataExchangeSurfaceEnabled(ENABLED_CAPABILITIES, 'imports')).toBe(true);
    expect(dataExchangeSurfaceEnabled(ENABLED_CAPABILITIES, 'exports')).toBe(true);
    expect(dataExchangeSurfaceEnabled(ENABLED_CAPABILITIES, 'reports')).toBe(false);
    expect(dataExchangeSurfaceEnabled(ENABLED_CAPABILITIES, 'transfers')).toBe(true);
  });

  it('defaults an unlisted surface ON once data_exchange.enabled is true', () => {
    const caps: DataExchangeCapabilities = { data_exchange: { enabled: true, flags: {} } };
    expect(dataExchangeSurfaceEnabled(caps, 'reports')).toBe(true);
    expect(dataExchangeSurfaceEnabled(caps, 'transfers')).toBe(true);
  });
});

describe('data-exchange API client (frozen endpoint shapes)', () => {
  it('fetches capabilities from GET /v1/data-exchange/capabilities', async () => {
    serveGet({ '/v1/data-exchange/capabilities': ENABLED_CAPABILITIES });
    const { fetchDataExchangeCapabilities } = await import('@aether-app/features/data-exchange');
    await expect(fetchDataExchangeCapabilities()).resolves.toEqual(ENABLED_CAPABILITIES);
    expect(mocks.get).toHaveBeenCalledWith(
      '/v1/data-exchange/capabilities',
      expect.anything(),
    );
  });

  it('lists unified artifact history from GET /v1/data-exchange/artifacts', async () => {
    serveGet({
      '/v1/data-exchange/artifacts': { artifacts: [EXPORT_ARTIFACT, IMPORT_ARTIFACT, REPORT_ARTIFACT], count: 3 },
    });
    const { fetchDataExchangeArtifacts } = await import('@aether-app/features/data-exchange');
    const result = await fetchDataExchangeArtifacts({ limit: 25, status_filter: 'available' });
    expect(result.count).toBe(3);
    expect(result.artifacts.map(a => a.artifact_id)).toEqual([
      'art_export_1',
      'art_import_1',
      'art_report_1',
    ]);
    expect(mocks.get).toHaveBeenCalledWith(
      '/v1/data-exchange/artifacts?limit=25&status_filter=available',
      expect.anything(),
    );
  });

  it('fails closed when an artifact row carries a bad status', async () => {
    serveGet({
      '/v1/data-exchange/artifacts': {
        artifacts: [{ ...EXPORT_ARTIFACT, status: 'flapping' }],
        count: 1,
      },
    });
    const { fetchDataExchangeArtifacts } = await import('@aether-app/features/data-exchange');
    await expect(fetchDataExchangeArtifacts()).rejects.toThrow();
  });

  it('creates an export via POST /v1/data-exchange/exports returning export_id/status generating', async () => {
    servePost('/v1/data-exchange/exports', {
      export_id: 'exp_1',
      artifact_id: 'art_export_1',
      job_id: 'job_1',
      status: 'generating',
    });
    const { createDataExchangeExport } = await import('@aether-app/features/data-exchange');
    const result = await createDataExchangeExport({ resource: 'profile360', format: 'ndjson' });
    expect(result.export_id).toBe('exp_1');
    expect(result.status).toBe('generating');
    expect(mocks.post).toHaveBeenCalledWith(
      '/v1/data-exchange/exports',
      expect.anything(),
      { resource: 'profile360', format: 'ndjson' },
    );
  });

  it('creates a report via POST /v1/data-exchange/reports returning report_id/status generating', async () => {
    servePost('/v1/data-exchange/reports', {
      report_id: 'rep_1',
      artifact_id: 'art_report_1',
      job_id: 'job_2',
      status: 'generating',
    });
    const { createDataExchangeReport } = await import('@aether-app/features/data-exchange');
    const result = await createDataExchangeReport({ resource: 'profile360', template: 'standard' });
    expect(result.report_id).toBe('rep_1');
    expect(result.status).toBe('generating');
  });

  it('resolves the signed download URL for an artifact', async () => {
    serveGet({
      '/v1/data-exchange/transfers/art_export_1/download-url': {
        artifact_id: 'art_export_1',
        download_url: 'https://store.example/export.ndjson?sig=abc',
        download_headers: { 'X-Amz-Algorithm': 'AWS4-HMAC-SHA256' },
        expires_at: '2026-08-01T00:05:00Z',
        checksum_sha256: 'a'.repeat(64),
      },
    });
    const { fetchDataExchangeDownloadUrl } = await import('@aether-app/features/data-exchange');
    const result = await fetchDataExchangeDownloadUrl('art_export_1');
    expect(result.download_url).toContain('sig=abc');
    expect(mocks.get).toHaveBeenCalledWith(
      '/v1/data-exchange/transfers/art_export_1/download-url',
      expect.anything(),
    );
  });
});

describe('data-exchange hooks', () => {
  it('useDataExchangeCapabilities fetches through the typed client and surfaces data', async () => {
    serveGet({ '/v1/data-exchange/capabilities': ENABLED_CAPABILITIES });
    const { result } = renderHook(() => useDataExchangeCapabilities());
    await waitFor(() => {
      expect(result.current.capabilities?.data_exchange.enabled).toBe(true);
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('useCreateDataExchangeExport resolves a successful mutation result', async () => {
    servePost('/v1/data-exchange/exports', {
      export_id: 'exp_1',
      artifact_id: 'art_export_1',
      job_id: 'job_1',
      status: 'generating',
    });
    const { result } = renderHook(() => useCreateDataExchangeExport());
    let outcome: string | null = null;
    await act(async () => {
      outcome = (await result.current.create({ resource: 'profile360', format: 'ndjson' }))?.export_id ?? null;
    });
    expect(outcome).toBe('exp_1');
    expect(result.current.error).toBeNull();
  });
});
