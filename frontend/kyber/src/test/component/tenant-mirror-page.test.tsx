/**
 * Kyber — Tenant Mirror operator page.
 *
 * The load-bearing assertions here are the ones that keep the page from lying:
 *
 *  · an **unavailable / not-run** parity result must render as undetermined and must
 *    NOT render as matched. This is the most important assertion in the file — an
 *    operator who reads "parity holds" because the comparison never ran will close an
 *    investigation that should have stayed open.
 *  · a **diverged** result must show the located JSON path and BOTH values, and must
 *    not render a matched state.
 *  · a tenant-visible `null` must render as Unknown and never as `0`. Coercing a
 *    tenant-visible null to zero would make the page misdescribe what the tenant sees.
 *  · `operatorDiagnostics` must appear in the operator region and nowhere inside the
 *    tenant-visible region.
 *
 * Only `restClient` is mocked, and the mock runs the caller-supplied zod schema exactly
 * as the real client does — so the feature module's schemas are genuinely exercised and
 * a schema that coerced a null to 0 would fail these tests.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { z } from 'zod';
import { queryCache } from '@aether/ui';
import {
  MIRROR_ERROR_TITLE,
  PARITY_DIVERGED_LABEL,
  PARITY_EXEMPT_LABEL,
  PARITY_MATCHED_LABEL,
  PARITY_SCOPE_REQUIRED_LABEL,
  PARITY_UNDETERMINED_LABEL,
  TenantMirrorPage,
} from '@kyber/pages/tenant-mirror';

const restGet = vi.fn();

vi.mock('@kyber/lib/api', () => ({
  restClient: {
    get: (...args: unknown[]) => restGet(...args),
  },
}));

const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };

beforeAll(() => {
  // The shared queryCache tracks in-flight fetches with `promise.finally(...)`, which
  // leaks an unhandled rejection when a fetcher rejects even though the UI renders an
  // ErrorState. Patch it test-locally (same fix as agent-access-page.test.tsx).
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

// ── Fixtures ─────────────────────────────────────────────────────────────────
//
// Named for what they are, not `MOCK_*`: `scripts/validate_frontend_data_truth.py`
// fails on that token, and these are response shapes copied from
// `services/kyber/mirror/contracts.py`, not stand-ins for missing data.

const TENANT = 'tenant_alpha';
const SURFACE = 'users';

const DIAGNOSTICS = {
  quality: {
    value_state: 'observed',
    complete: true,
    truncated: false,
    missing_inputs: [],
    reads_issued: 1,
    exposure_known: true,
  },
  lineage: {
    source: 'services.kyber.graph.scoped_gateway',
    vertex_types: ['User'],
    scope_id: 'scope_77',
    purpose: 'tenant_investigation',
    evidence_reference_count: 3,
    evidence_disclosure_gated: false,
  },
  policy: {
    mirror_capability: 'kyber.tenant.mirror.read',
    gateway_capability: 'kyber.graph.tenant.read',
    manifest_minimum_disclosure: 'D3',
    granted_disclosure: 'D3',
    identifiers_masked: false,
    tenant_scope: 'required',
    tenant_parity_required: true,
  },
  health: { state: 'healthy', surface: SURFACE, reads: {}, computed_at: '2026-07-25T00:00:00Z' },
  recomputeOptions: [
    {
      option_id: 'recompute_surface',
      label: 'Recompute users for this tenant',
      capability: 'kyber.command.recompute',
      offered_by: 'kyber command plane',
      available_here: false,
      reason: 'the Tenant Mirror is a read surface; recompute is a class-3 action',
    },
  ],
};

const MIRROR_ENVELOPE = {
  surface_id: SURFACE,
  aether_route: '/users',
  tenant_id: TENANT,
  contract_version: '1.0.0',
  generated_at: '2026-07-25T00:00:00Z',
  disclosure: 'D3',
  parity_comparable: true,
  tenantVisible: {
    surface: SURFACE,
    aether_route: '/users',
    tenant_id: TENANT,
    vertex_types: ['User'],
    entities: { User: [] },
    entity_counts: { User: 41 },
    entity_count: 41,
    truncated: false,
  },
  operatorDiagnostics: DIAGNOSTICS,
};

/**
 * The tenant's own counts came back null — the gateway could not read them. The page
 * must say "Unknown", never "0".
 */
const MIRROR_ENVELOPE_UNKNOWN_COUNTS = {
  ...MIRROR_ENVELOPE,
  tenantVisible: {
    ...MIRROR_ENVELOPE.tenantVisible,
    entity_counts: { User: null },
    entity_count: null,
    truncated: null,
  },
};

const MIRROR_DIGEST = {
  algorithm: 'sha256',
  digest: 'aaaa1111bbbb2222',
  canonical_bytes: 184,
  contract_version: '1.0.0',
  computed_at: '2026-07-25T00:00:00Z',
};

const AETHER_DIGEST = {
  algorithm: 'sha256',
  digest: 'cccc3333dddd4444',
  canonical_bytes: 184,
  contract_version: '1.0.0',
  computed_at: '2026-07-25T00:00:00Z',
};

/** No `compare` was supplied, so the backend answered with its digest and no comparison. */
const PARITY_NOT_RUN = {
  surface: SURFACE,
  tenant_id: TENANT,
  contract_version: '1.0.0',
  parity_comparable: true,
  mirror_digest: MIRROR_DIGEST,
  comparison: null,
};

const PARITY_MATCHED = {
  ...PARITY_NOT_RUN,
  comparison: {
    matched: true,
    contract_version: '1.0.0',
    aether_digest: MIRROR_DIGEST,
    mirror_digest: MIRROR_DIGEST,
    divergences: [],
    divergence_count: 0,
    truncated: false,
    compared_at: '2026-07-25T00:00:00Z',
  },
};

const PARITY_DIVERGED = {
  ...PARITY_NOT_RUN,
  comparison: {
    matched: false,
    contract_version: '1.0.0',
    aether_digest: AETHER_DIGEST,
    mirror_digest: MIRROR_DIGEST,
    divergences: [
      {
        path: '$.entity_counts.User',
        aether: 41,
        mirror: 37,
        reason: 'value_differs',
      },
    ],
    divergence_count: 1,
    truncated: false,
    compared_at: '2026-07-25T00:00:00Z',
  },
};

const PARITY_DIVERGED_TRUNCATED = {
  ...PARITY_NOT_RUN,
  comparison: {
    ...PARITY_DIVERGED.comparison,
    divergence_count: 812,
    truncated: true,
  },
};

// ── Wiring ───────────────────────────────────────────────────────────────────

class HttpFailure extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly problem?: { detail?: string; title?: string },
  ) {
    super(message);
    this.name = 'HttpFailure';
  }
}

type Responses = {
  mirror?: unknown;
  parity?: unknown;
  mirrorError?: HttpFailure | Error;
  parityError?: HttpFailure | Error;
};

/**
 * The mock applies the caller's schema, exactly as `restClient` does, so the real zod
 * schemas in the feature module run inside these tests.
 */
function mockApi(responses: Responses): void {
  restGet.mockImplementation((path: string, schema: z.ZodTypeAny) => {
    if (path.includes('/parity')) {
      if (responses.parityError) return Promise.reject(responses.parityError);
      return Promise.resolve(schema.parse({ data: responses.parity ?? PARITY_NOT_RUN, meta: {} }));
    }
    if (path.includes('/mirror/')) {
      if (responses.mirrorError) return Promise.reject(responses.mirrorError);
      return Promise.resolve(
        schema.parse({
          data: responses.mirror ?? MIRROR_ENVELOPE,
          meta: { granted_disclosure: 'D3', contract_version: '1.0.0', parity_comparable: true },
        }),
      );
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <TenantMirrorPage />
    </MemoryRouter>,
  );
}

async function openMirror(tenant: string = TENANT, surface: string = SURFACE): Promise<void> {
  await userEvent.selectOptions(screen.getByLabelText('Surface'), surface);
  await userEvent.type(screen.getByLabelText('Tenant ID'), tenant);
  await userEvent.click(screen.getByRole('button', { name: 'Open mirror' }));
}

function tenantRegion(): HTMLElement {
  return screen.getByTestId('tenant-visible-region');
}

function operatorRegion(): HTMLElement {
  return screen.getByTestId('operator-diagnostics-region');
}

beforeEach(() => {
  queryCache.invalidatePrefix('');
  cache.inFlight.clear();
  restGet.mockReset();
});

// ── Surface ──────────────────────────────────────────────────────────────────

describe('TenantMirrorPage — surface', () => {
  it('renders the tenant-visible and operator-only regions as separate labelled regions', async () => {
    mockApi({ parity: PARITY_MATCHED });
    renderPage();
    await openMirror();

    await waitFor(() => expect(screen.getByTestId('tenant-visible-region')).toBeInTheDocument());
    expect(operatorRegion()).toBeInTheDocument();
    expect(within(tenantRegion()).getByText('TENANT-VISIBLE')).toBeInTheDocument();
    expect(within(operatorRegion()).getByText('OPERATOR-ONLY')).toBeInTheDocument();
    // The two regions are distinct elements — neither contains the other.
    expect(tenantRegion().contains(operatorRegion())).toBe(false);
    expect(operatorRegion().contains(tenantRegion())).toBe(false);
  });

  it('requests the mirror and the parity digest for the tenant and surface named', async () => {
    mockApi({});
    renderPage();
    await openMirror();

    await waitFor(() =>
      expect(
        restGet.mock.calls.some(
          ([path]) => path === `/v1/kyber/tenants/${TENANT}/mirror/${SURFACE}`,
        ),
      ).toBe(true),
    );
    expect(
      restGet.mock.calls.some(
        ([path]) =>
          typeof path === 'string' &&
          path.startsWith(`/v1/kyber/tenants/${TENANT}/mirror/${SURFACE}/parity`),
      ),
    ).toBe(true);
  });

  it('reads the masked variant when the operator switches to the masked view', async () => {
    mockApi({});
    renderPage();
    await openMirror();
    await waitFor(() => expect(screen.getByTestId('tenant-visible-region')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: 'Switch to masked view' }));

    await waitFor(() =>
      expect(
        restGet.mock.calls.some(
          ([path]) => path === `/v1/kyber/tenants/${TENANT}/mirror/${SURFACE}/masked`,
        ),
      ).toBe(true),
    );
    // The operator is told, in the tenant region itself, that these are not the
    // tenant's real values.
    expect(within(tenantRegion()).getByText(/MASKED VIEW \(D2\)/)).toBeInTheDocument();
    // A masked rendering is never presented as parity.
    expect(screen.queryByText(PARITY_MATCHED_LABEL)).not.toBeInTheDocument();
  });
});

// ── Parity: matched ──────────────────────────────────────────────────────────

describe('TenantMirrorPage — parity states', () => {
  it('renders a matched parity result as matched, with the digest', async () => {
    mockApi({ parity: PARITY_MATCHED });
    renderPage();
    await openMirror();

    await waitFor(() => expect(screen.getByText(PARITY_MATCHED_LABEL)).toBeInTheDocument());
    expect(screen.getAllByText(new RegExp(MIRROR_DIGEST.digest)).length).toBeGreaterThan(0);
    expect(screen.queryByText(PARITY_DIVERGED_LABEL)).not.toBeInTheDocument();
    expect(screen.queryByText(PARITY_UNDETERMINED_LABEL)).not.toBeInTheDocument();
  });

  it('renders a diverged result with the JSON path and BOTH values, and never as matched', async () => {
    mockApi({ parity: PARITY_DIVERGED });
    renderPage();
    await openMirror();

    await waitFor(() => expect(screen.getByText(PARITY_DIVERGED_LABEL)).toBeInTheDocument());

    // Located, not just "different": the path and both canonicalised values, all
    // inside the banner itself rather than incidentally elsewhere on the page.
    const banner = screen.getByTestId('parity-banner');
    expect(within(banner).getByText('$.entity_counts.User')).toBeInTheDocument();
    expect(within(banner).getByText('41')).toBeInTheDocument();
    expect(within(banner).getByText('37')).toBeInTheDocument();
    expect(within(banner).getByText('Value differs')).toBeInTheDocument();

    // Negative: nothing on screen says parity held.
    expect(screen.queryByText(PARITY_MATCHED_LABEL)).not.toBeInTheDocument();
  });

  it('says so when the backend reports the divergence list was truncated', async () => {
    mockApi({ parity: PARITY_DIVERGED_TRUNCATED });
    renderPage();
    await openMirror();

    await waitFor(() => expect(screen.getByText(PARITY_DIVERGED_LABEL)).toBeInTheDocument());
    expect(screen.getByText(/The backend capped this list/)).toBeInTheDocument();
    expect(screen.getByText(/812 divergence\(s\) located/)).toBeInTheDocument();
  });

  /**
   * THE assertion. `comparison: null` means the comparison never ran. Rendering that
   * as "matched" would tell an operator the tenant is fine on the strength of a check
   * that was never performed.
   */
  it('renders an unavailable / not-run parity result as undetermined, NEVER as matched', async () => {
    mockApi({ parity: PARITY_NOT_RUN });
    renderPage();
    await openMirror();

    await waitFor(() => expect(screen.getByText(PARITY_UNDETERMINED_LABEL)).toBeInTheDocument());
    expect(screen.getByText(/the comparison never ran/)).toBeInTheDocument();
    expect(screen.getByText(/Undetermined is not a pass/)).toBeInTheDocument();

    expect(screen.queryByText(PARITY_MATCHED_LABEL)).not.toBeInTheDocument();
    expect(screen.queryByText(PARITY_DIVERGED_LABEL)).not.toBeInTheDocument();
  });

  it('renders a failed parity read as undetermined, never as matched', async () => {
    mockApi({ parityError: new Error('parity route unavailable') });
    renderPage();
    await openMirror();

    await waitFor(() => expect(screen.getByText(PARITY_UNDETERMINED_LABEL)).toBeInTheDocument());
    expect(screen.getByText('parity route unavailable')).toBeInTheDocument();
    expect(screen.queryByText(PARITY_MATCHED_LABEL)).not.toBeInTheDocument();
  });

  it('shows the manifest exception reason for a parity-exempt surface', async () => {
    mockApi({});
    renderPage();

    await userEvent.selectOptions(screen.getByLabelText('Surface'), 'settings');

    expect(screen.getByText(PARITY_EXEMPT_LABEL)).toBeInTheDocument();
    expect(
      screen.getByText(
        'tenant self-configuration; operators must not mutate it from a mirror',
      ),
    ).toBeInTheDocument();
    // Exempt is not a pass, and it is not a silent absence either.
    expect(screen.queryByText(PARITY_MATCHED_LABEL)).not.toBeInTheDocument();
  });
});

// ── THE RULE: a tenant-visible null is Unknown, never 0 ──────────────────────

describe('TenantMirrorPage — a tenant-visible null is never rendered as zero', () => {
  it('renders null tenant-visible counts as Unknown and never as 0', async () => {
    mockApi({ mirror: MIRROR_ENVELOPE_UNKNOWN_COUNTS, parity: PARITY_NOT_RUN });
    renderPage();
    await openMirror();

    await waitFor(() => expect(screen.getByTestId('tenant-visible-region')).toBeInTheDocument());

    const region = tenantRegion();
    expect(within(region).getAllByText('Unknown').length).toBeGreaterThanOrEqual(3);
    expect(within(region).queryByText('0')).not.toBeInTheDocument();
    expect(within(region).getAllByText(/Unknown — not zero/).length).toBeGreaterThan(0);
    // A tri-state flag the backend did not answer is not rendered as "No".
    expect(within(region).queryByText('No')).not.toBeInTheDocument();
  });
});

// ── Region separation ────────────────────────────────────────────────────────

describe('TenantMirrorPage — diagnostics stay out of the tenant-visible region', () => {
  it('renders operatorDiagnostics only inside the operator region', async () => {
    mockApi({ parity: PARITY_MATCHED });
    renderPage();
    await openMirror();

    await waitFor(() =>
      expect(screen.getByTestId('operator-diagnostics-region')).toBeInTheDocument(),
    );

    const operator = operatorRegion();
    const tenant = tenantRegion();

    // The default diagnostics tab is `quality`.
    expect(within(operator).getByText('value_state')).toBeInTheDocument();
    expect(within(operator).getByText('observed')).toBeInTheDocument();
    expect(within(tenant).queryByText('value_state')).not.toBeInTheDocument();
    expect(within(tenant).queryByText('observed')).not.toBeInTheDocument();

    // And the region says out loud that the tenant sees none of it.
    expect(within(operator).getByText(/never quote them to a customer/)).toBeInTheDocument();

    // Lineage lives behind its own tab, still inside the operator region.
    await userEvent.click(within(operator).getByRole('tab', { name: 'Lineage' }));
    expect(
      within(operatorRegion()).getByText('services.kyber.graph.scoped_gateway'),
    ).toBeInTheDocument();
    expect(
      within(tenantRegion()).queryByText('services.kyber.graph.scoped_gateway'),
    ).not.toBeInTheDocument();
  });

  it('labels an uncomputed diagnostic section as not computed, not as healthy', async () => {
    mockApi({
      mirror: {
        ...MIRROR_ENVELOPE,
        operatorDiagnostics: { ...DIAGNOSTICS, quality: {} },
      },
      parity: PARITY_MATCHED,
    });
    renderPage();
    await openMirror();

    await waitFor(() =>
      expect(screen.getByText('Quality was not computed')).toBeInTheDocument(),
    );
    expect(screen.getByText(/Empty means not computed/)).toBeInTheDocument();
  });
});

// ── Authorization ────────────────────────────────────────────────────────────

describe('TenantMirrorPage — the D3 read requires an active tenant scope', () => {
  it('renders a 403 as the scope-required state with the backend reason, not a generic error', async () => {
    mockApi({
      mirrorError: new HttpFailure('forbidden', 403, {
        detail: 'No active tenant access scope for tenant_alpha',
      }),
      parityError: new HttpFailure('forbidden', 403, {
        detail: 'No active tenant access scope for tenant_alpha',
      }),
    });
    renderPage();
    await openMirror();

    await waitFor(() =>
      expect(screen.getByText(PARITY_SCOPE_REQUIRED_LABEL)).toBeInTheDocument(),
    );
    expect(
      screen.getByText('No active tenant access scope for tenant_alpha'),
    ).toBeInTheDocument();

    // Not a generic failure, and no payload is implied to exist.
    expect(screen.queryByText(MIRROR_ERROR_TITLE)).not.toBeInTheDocument();
    expect(screen.queryByTestId('tenant-visible-region')).not.toBeInTheDocument();
    expect(screen.queryByTestId('operator-diagnostics-region')).not.toBeInTheDocument();
  });

  it('still reports a non-403 failure as an error rather than as an authorization state', async () => {
    mockApi({ mirrorError: new HttpFailure('upstream exploded', 502) });
    renderPage();
    await openMirror();

    await waitFor(() => expect(screen.getByText(MIRROR_ERROR_TITLE)).toBeInTheDocument());
    expect(screen.queryByText(PARITY_SCOPE_REQUIRED_LABEL)).not.toBeInTheDocument();
  });
});
