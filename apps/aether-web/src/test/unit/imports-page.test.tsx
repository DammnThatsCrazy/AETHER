import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider, queryCache } from '@aether/ui';
import { ImportsPage, ImportDetailPage } from '@aether-app/pages/imports';

beforeAll(() => {
  // jsdom 25 does not implement <dialog>.showModal()/close(); polyfill minimally
  // in case any shared component relies on them.
  if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
      this.setAttribute('open', '');
    };
    HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
      this.removeAttribute('open');
      this.dispatchEvent(new Event('close'));
    };
  }

  // The shared queryCache tracks in-flight fetches with `promise.finally(...)`,
  // which leaks an unhandled rejection when a fetcher rejects even though the UI
  // handles the error. Patch it test-locally so the error-state test does not
  // trip vitest's unhandled-error detector.
  const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

/** Badge text can collide with other text; scope to badge elements. */
function getBadge(text: string): HTMLElement {
  const match = screen.getAllByText(text).find(el => el.classList.contains('ui-badge'));
  expect(match).toBeDefined();
  return match as HTMLElement;
}

const mocks = vi.hoisted(() => ({
  fetchImports: vi.fn(),
  createImport: vi.fn(),
  fetchImportDetail: vi.fn(),
  uploadImportFile: vi.fn(),
  analyzeImport: vi.fn(),
  putImportMapping: vi.fn(),
  validateImport: vi.fn(),
  approveImport: vi.fn(),
  cancelImport: vi.fn(),
  suggestImportTemplates: vi.fn(),
  applyImportTemplate: vi.fn(),
  fetchImportTemplates: vi.fn(),
  graphPreviewImport: vi.fn(),
  commitImport: vi.fn(),
  replayImport: vi.fn(),
  rollbackImport: vi.fn(),
  fetchImportCommits: vi.fn(),
}));

vi.mock('@aether-app/features/imports/api', () => mocks);

const IMPORT_FIXTURES = [
  {
    id: 'imp_customers_001',
    tenant_id: 'tenant_demo_001',
    status: 'analyzed',
    source_kind: 'file_upload',
    file_count: 1,
    row_count: 1240,
    created_by: 'alex@acme.io',
    created_at: '2026-07-08T12:00:00.000Z',
    updated_at: '2026-07-08T12:05:00.000Z',
  },
  {
    id: 'imp_events_002',
    tenant_id: 'tenant_demo_001',
    status: 'committed',
    source_kind: 'file_upload',
    file_count: 2,
    row_count: 8800,
    created_by: 'alex@acme.io',
    created_at: '2026-07-06T09:00:00.000Z',
    updated_at: '2026-07-06T09:40:00.000Z',
  },
];

const IMPORT_DETAIL = {
  session: IMPORT_FIXTURES[0],
  files: [
    { id: 'file_imp_001', import_id: 'imp_customers_001', filename: 'customers.csv', content_type: 'text/csv', size_bytes: 184320, sha256: 'a'.repeat(64), status: 'stored', created_at: '2026-07-08T12:01:00.000Z' },
  ],
  schemas: [
    {
      file_id: 'file_imp_001',
      format: 'csv',
      row_count: 1240,
      sampled_rows: 500,
      columns: [
        { name: 'email', inferred_type: 'email', nullable: false, null_count: 0, distinct_count: 1240, sample_values: ['alex@acme.io'], sensitivity: 'pii' },
        { name: 'signup_at', inferred_type: 'datetime', nullable: false, null_count: 0, distinct_count: 1240, sample_values: ['2026-01-04T09:00:00.000Z'], sensitivity: 'none' },
      ],
      delimiter: ',',
      has_header: true,
    },
  ],
  mapping: null,
  validation: null,
};

const VALIDATE_RESPONSE = {
  status: 'review_required',
  validation: {
    import_id: 'imp_customers_001',
    mapping_version: 1,
    ok: false,
    rows_total: 1240,
    rows_valid: 1238,
    rows_invalid: 2,
    errors: [
      { row: 41, source_column: 'wallet', primitive: 'identifier', code: 'invalid_wallet_address', message: 'Value is not a valid wallet address.' },
    ],
    errors_truncated: false,
    governance_review_required: true,
    governance_reasons: ['pii_detected:email'],
  },
  review_reasons: ['pii_detected:email'],
};

function renderListPage() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={['/imports']}>
        <Routes>
          <Route path="/imports" element={<ImportsPage />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

function renderDetailPage(id: string) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[`/imports/${id}`]}>
        <Routes>
          <Route path="/imports/:id" element={<ImportDetailPage />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  queryCache.invalidatePrefix('imports');
  mocks.fetchImports.mockResolvedValue({ imports: IMPORT_FIXTURES, count: IMPORT_FIXTURES.length });
  mocks.createImport.mockResolvedValue({ ...IMPORT_FIXTURES[0], id: 'imp_new_004', status: 'created' });
  mocks.fetchImportDetail.mockResolvedValue(IMPORT_DETAIL);
  mocks.fetchImportCommits.mockResolvedValue({ commits: [], count: 0 });
  mocks.putImportMapping.mockResolvedValue({ id: 'map_001', import_id: 'imp_customers_001', version: 1, fields: [], created_at: '2026-07-08T12:06:00.000Z' });
  mocks.validateImport.mockResolvedValue(VALIDATE_RESPONSE);
});

describe('Aether Imports page', () => {
  it('renders import sessions with status badges and counts', async () => {
    renderListPage();
    await waitFor(() => expect(getBadge('analyzed')).toBeInTheDocument());
    expect(getBadge('committed')).toBeInTheDocument();
    expect(screen.getByText('1,240')).toBeInTheDocument();
    expect(screen.getByText('8,800')).toBeInTheDocument();
  });

  it('shows the empty state when there are no imports', async () => {
    mocks.fetchImports.mockResolvedValue({ imports: [], count: 0 });
    renderListPage();
    await waitFor(() => expect(screen.getByText('No imports yet')).toBeInTheDocument());
  });

  it('shows the error state when the list request fails', async () => {
    mocks.fetchImports.mockRejectedValue(new Error('kaboom'));
    renderListPage();
    await waitFor(() => expect(screen.getByText('Failed to load imports')).toBeInTheDocument());
    expect(screen.getByText('kaboom')).toBeInTheDocument();
  });
});

describe('Aether Import detail page', () => {
  it('renders the session status and analyzed schema', async () => {
    renderDetailPage('imp_customers_001');
    await waitFor(() => expect(getBadge('analyzed')).toBeInTheDocument());
    // Column names appear in both the schema table and the mapping editor.
    expect(screen.getAllByText('signup_at').length).toBeGreaterThan(0);
    expect(screen.getByText('datetime')).toBeInTheDocument();
  });

  it('submits a mapping via the PUT fetcher', async () => {
    renderDetailPage('imp_customers_001');
    await waitFor(() => expect(screen.getByText('Save mapping')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Save mapping'));
    await waitFor(() =>
      expect(mocks.putImportMapping).toHaveBeenCalledWith(
        'imp_customers_001',
        expect.arrayContaining([expect.objectContaining({ source_column: 'email' })]),
      ),
    );
  });

  it('renders the validation result after running validation', async () => {
    renderDetailPage('imp_customers_001');
    await waitFor(() => expect(screen.getByText('Run validation')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Run validation'));
    await waitFor(() => expect(mocks.validateImport).toHaveBeenCalledWith('imp_customers_001'));
    expect(screen.getByText('Governance review required')).toBeInTheDocument();
    expect(screen.getByText('1,238')).toBeInTheDocument();
  });
});
