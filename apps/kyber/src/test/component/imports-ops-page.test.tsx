import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';
import { ImportsOpsPage } from '@kyber/pages/imports-ops/imports-ops-page';
import { ImportOpsDetailPage } from '@kyber/pages/imports-ops/import-detail-page';

beforeAll(() => {
  // The shared queryCache tracks in-flight fetches with `promise.finally(...)`,
  // which leaks an unhandled rejection when a fetcher rejects even though the UI
  // handles the error via ErrorState. Patch it test-locally so the error-state
  // test does not trip vitest's unhandled-error detector.
  const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

// Mock the feature api module so the real useQuery/useMutation hooks run against
// controllable fetchers (the hooks import these same fns via a relative './api').
const fetchImportsTimeline = vi.fn();
const fetchImportOpsDetail = vi.fn();
const requeueImport = vi.fn();

vi.mock('@kyber/features/imports-ops/api', () => ({
  fetchImportsTimeline: (...args: unknown[]) => fetchImportsTimeline(...args),
  fetchImportOpsDetail: (...args: unknown[]) => fetchImportOpsDetail(...args),
  requeueImport: (...args: unknown[]) => requeueImport(...args),
}));

const FAILED_SESSION = {
  id: 'imp_test_failed_01', tenant_id: 'tenant_003', status: 'failed', source_kind: 'file_upload',
  file_count: 2, row_count: 100, created_by: 'ingest@t3.io',
  created_at: '2026-07-11T09:12:00.000Z', updated_at: '2026-07-11T09:18:44.000Z',
};

const OK_SESSION = {
  id: 'imp_test_ok_02', tenant_id: 'tenant_001', status: 'committed', source_kind: 'file_upload',
  file_count: 1, row_count: 42, created_by: 'ops@t1.io',
  created_at: '2026-07-11T08:40:00.000Z', updated_at: '2026-07-11T08:52:10.000Z',
};

const COMMIT = {
  id: 'cmt_test_1', commit_id: 'cmt_test_1', import_id: 'imp_test_failed_01', status: 'failed',
  row_count: 100, vertices_count: 0, edges_count: 0, rolled_back: true,
  created_at: '2026-07-11T09:18:40.000Z', created_by: 'ingest@t3.io',
};

function renderDetail(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/imports/${id}`]}>
      <Routes>
        <Route path="/imports/:importId" element={<ImportOpsDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  queryCache.invalidatePrefix('');
  fetchImportsTimeline.mockReset();
  fetchImportOpsDetail.mockReset();
  requeueImport.mockReset();
});

describe('ImportsOpsPage (list)', () => {
  it('renders cross-tenant import rows', async () => {
    fetchImportsTimeline.mockResolvedValue({ sessions: [FAILED_SESSION, OK_SESSION], count: 2 });
    render(<MemoryRouter><ImportsOpsPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText('tenant_003')).toBeInTheDocument());
    expect(screen.getByText('tenant_001')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('committed')).toBeInTheDocument();
    expect(screen.getByText(/2 sessions across all tenants/)).toBeInTheDocument();
  });

  it('renders the error state when the timeline fetch fails', async () => {
    fetchImportsTimeline.mockRejectedValue(new Error('boom'));
    render(<MemoryRouter><ImportsOpsPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText('Failed to load import timeline')).toBeInTheDocument());
    expect(screen.getByText('boom')).toBeInTheDocument();
  });

  it('renders the empty state when there are no sessions', async () => {
    fetchImportsTimeline.mockResolvedValue({ sessions: [], count: 0 });
    render(<MemoryRouter><ImportsOpsPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getByText('No imports yet')).toBeInTheDocument());
  });
});

describe('ImportOpsDetailPage (detail)', () => {
  it('renders the session fields and commit history', async () => {
    fetchImportOpsDetail.mockResolvedValue({ session: FAILED_SESSION, commits: [COMMIT], commit_count: 1 });
    renderDetail('imp_test_failed_01');

    await waitFor(() => expect(screen.getByText('imp_test_failed_01')).toBeInTheDocument());
    // tenant appears in the subtitle and the session field
    expect(screen.getAllByText('tenant_003').length).toBeGreaterThan(0);
    expect(screen.getByText('cmt_test_1')).toBeInTheDocument();
    expect(screen.getByText('Commit history')).toBeInTheDocument();
  });

  it('shows a Requeue button for a failed import and calls the mutation', async () => {
    fetchImportOpsDetail.mockResolvedValue({ session: FAILED_SESSION, commits: [COMMIT], commit_count: 1 });
    requeueImport.mockResolvedValue({ import_id: 'imp_test_failed_01', job: { id: 'job_1', status: 'queued' } });
    renderDetail('imp_test_failed_01');

    const button = await screen.findByRole('button', { name: /Requeue import/ });
    fireEvent.click(button);

    await waitFor(() => expect(requeueImport).toHaveBeenCalledWith('imp_test_failed_01'));
    await waitFor(() => expect(screen.getByText(/Requeue accepted/)).toBeInTheDocument());
  });

  it('does not show a Requeue button for a non-failed import', async () => {
    fetchImportOpsDetail.mockResolvedValue({ session: OK_SESSION, commits: [], commit_count: 0 });
    renderDetail('imp_test_ok_02');

    await waitFor(() => expect(screen.getByText('imp_test_ok_02')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Requeue import/ })).not.toBeInTheDocument();
    expect(screen.getByText('No commits yet')).toBeInTheDocument();
  });
});
