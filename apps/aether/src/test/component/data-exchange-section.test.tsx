import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { DataExchangeSection } from '@aether-app/pages/settings/data-exchange-section';
import type {
  DataExchangeArtifact,
  DataExchangeCapabilities,
  DataExchangeDownloadUrl,
} from '@aether-app/features/data-exchange';

/**
 * M6 Data Exchange — Settings-section state coverage.
 *
 * The section is mocked at the feature-barrel seam so each capability /
 * artifact-history branch is exercised deterministically without a backend:
 *   disabled → EmptyState, no export/report affordances;
 *   enabled+populated → capability summary + artifact table rows;
 *   enabled+empty  → empty artifact history;
 *   capability fetch error → section ErrorState;
 *   artifact fetch error → table ErrorState;
 *   surface-flag gating → disabled export/report buttons;
 *   export/report creation flows resolve through the dialog.
 * The pure `dataExchangeSurfaceEnabled` helper is kept REAL (spread from
 * importOriginal) so the surface-gating assertions exercise production logic.
 */

beforeAll(() => {
  // jsdom 25 does not implement <dialog>.showModal()/close(); polyfill minimally
  // so the Modal-backed export/report dialogs behave like the real DOM.
  if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
      this.setAttribute('open', '');
    };
    HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
      this.removeAttribute('open');
      this.dispatchEvent(new Event('close'));
    };
  }
});

const state = vi.hoisted(() => ({
  capabilities: null as unknown,
  capsLoading: false,
  capsError: null as string | null,
  artifacts: [] as unknown[],
  artifactsCount: 0,
  artifactsLoading: false,
  artifactsError: null as string | null,
  downloadUrl: null as unknown,
  createExport: vi.fn(),
  createReport: vi.fn(),
}));

vi.mock('@aether-app/features/data-exchange', async (importOriginal) => {
  const original =
    await importOriginal<typeof import('@aether-app/features/data-exchange')>();
  return {
    ...original,
    useDataExchangeCapabilities: () => ({
      capabilities: state.capabilities as DataExchangeCapabilities | null,
      loading: state.capsLoading,
      error: state.capsError,
      refresh: vi.fn(),
    }),
    useDataExchangeArtifacts: () => ({
      artifacts: state.artifacts as DataExchangeArtifact[],
      count: state.artifactsCount,
      loading: state.artifactsLoading,
      error: state.artifactsError,
      refresh: vi.fn(),
    }),
    useDataExchangeDownloadUrl: () => ({
      download: state.downloadUrl as DataExchangeDownloadUrl | null,
      loading: false,
      error: null,
      refresh: vi.fn(),
    }),
    useCreateDataExchangeExport: () => ({
      create: state.createExport,
      loading: false,
      error: null,
    }),
    useCreateDataExchangeReport: () => ({
      create: state.createReport,
      loading: false,
      error: null,
    }),
  };
});

// ── Fixtures ─────────────────────────────────────────────────────────────────

function caps(enabled: boolean, flags?: Record<string, boolean>): DataExchangeCapabilities {
  return { data_exchange: { enabled, flags: flags ?? {} } } as DataExchangeCapabilities;
}

const ENABLED = caps(true);

const EXPORT_ARTIFACT: DataExchangeArtifact = {
  artifact_id: 'art_export_1',
  direction: 'egress',
  artifact_type: 'export',
  filename: 'customers_export.ndjson',
  format: 'ndjson',
  classification: 'pii',
  status: 'available',
  size_bytes: 4096,
  created_at: '2026-08-01T00:00:00Z',
};

const IMPORT_ARTIFACT: DataExchangeArtifact = {
  artifact_id: 'art_import_1',
  direction: 'ingress',
  artifact_type: 'import_source',
  filename: 'customers.csv',
  format: 'csv',
  classification: 'identifier',
  status: 'committed',
  size_bytes: 184320,
  created_at: '2026-07-30T12:00:00Z',
};

const REPORT_ARTIFACT: DataExchangeArtifact = {
  artifact_id: 'art_report_1',
  direction: 'egress',
  artifact_type: 'report',
  filename: 'monthly-overview.pdf',
  format: 'pdf',
  classification: 'governance',
  status: 'generating',
  size_bytes: 8192,
  created_at: '2026-08-01T09:00:00Z',
};

const ARTIFACTS = [EXPORT_ARTIFACT, IMPORT_ARTIFACT, REPORT_ARTIFACT];

function renderSection() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={['/settings/data-exchange']}>
          <Routes>
            <Route path="/settings/data-exchange" element={<DataExchangeSection />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

function idleSection(): void {
  state.capabilities = ENABLED;
  state.capsLoading = false;
  state.capsError = null;
  state.artifacts = [];
  state.artifactsCount = 0;
  state.artifactsLoading = false;
  state.artifactsError = null;
  state.downloadUrl = null;
}

beforeEach(() => {
  idleSection();
  state.createExport.mockReset();
  state.createExport.mockResolvedValue({
    export_id: 'exp_1',
    artifact_id: 'art_export_1',
    job_id: 'job_1',
    status: 'generating',
  });
  state.createReport.mockReset();
  state.createReport.mockResolvedValue({
    report_id: 'rep_1',
    artifact_id: 'art_report_1',
    job_id: 'job_2',
    status: 'generating',
  });
});

describe('DataExchangeSection capability surface', () => {
  it('shows a failure state when the capabilities fetch errors', () => {
    state.capsLoading = false;
    state.capsError = 'backend unavailable';
    renderSection();
    expect(screen.getByText('Failed to load Data Exchange state')).toBeInTheDocument();
    expect(screen.queryByText(/Data Exchange is not enabled/)).not.toBeInTheDocument();
  });

  it('fails closed (no enabled affordances) when capabilities are missing entirely', () => {
    state.capabilities = null;
    state.capsLoading = false;
    state.capsError = null;
    renderSection();
    expect(screen.getByText('Data Exchange is unavailable.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New export' })).not.toBeInTheDocument();
  });

  it('shows the not-enabled EmptyState and hides creation controls when disabled', () => {
    state.capabilities = caps(false);
    state.capsLoading = false;
    state.capsError = null;
    renderSection();
    expect(
      screen.getByText('Data Exchange is not enabled for this workspace'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New export' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New report' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('dx-capability-summary')).not.toBeInTheDocument();
  });
});

describe('DataExchangeSection artifact history', () => {
  it('renders the capability summary and artifact rows when enabled and populated', () => {
    state.capabilities = ENABLED;
    state.capsLoading = false;
    state.artifacts = ARTIFACTS;
    state.artifactsCount = ARTIFACTS.length;
    state.artifactsLoading = false;
    renderSection();

    const summary = within(screen.getByTestId('dx-capability-summary'));
    expect(summary.getByText('Import engine')).toBeInTheDocument();
    expect(summary.getByText('Exports')).toBeInTheDocument();
    expect(summary.getByText('Reports')).toBeInTheDocument();
    expect(summary.getByText('Signed transfers')).toBeInTheDocument();

    expect(screen.getByText('customers_export.ndjson')).toBeInTheDocument();
    expect(screen.getByText('customers.csv')).toBeInTheDocument();
    expect(screen.getByText('monthly-overview.pdf')).toBeInTheDocument();
    expect(screen.getByText('Artifact history · 3')).toBeInTheDocument();
  });

  it('renders an empty history when enabled with no artifacts', () => {
    state.capabilities = ENABLED;
    state.capsLoading = false;
    state.artifacts = [];
    state.artifactsCount = 0;
    state.artifactsLoading = false;
    renderSection();
    expect(screen.getByText('No data exchange artifacts yet')).toBeInTheDocument();
    expect(screen.getByText('Artifact history')).toBeInTheDocument();
  });

  it('shows an artifact-history ErrorState when the history fetch fails', () => {
    state.capabilities = ENABLED;
    state.capsLoading = false;
    state.artifacts = [];
    state.artifactsLoading = false;
    state.artifactsError = 'history offline';
    renderSection();
    expect(screen.getByText('Failed to load artifact history')).toBeInTheDocument();
    expect(screen.queryByText('No data exchange artifacts yet')).not.toBeInTheDocument();
  });
});

describe('DataExchangeSection surface-flag gating', () => {
  it('disables New export when exports_enabled is false but keeps New report enabled', () => {
    state.capabilities = caps(true, { exports_enabled: false });
    state.capsLoading = false;
    renderSection();

    const newExport = screen.getByRole('button', { name: 'New export' });
    const newReport = screen.getByRole('button', { name: 'New report' });
    expect(newExport).toBeDisabled();
    expect(newReport).toBeEnabled();
  });

  it('disables New report when reports_enabled is false but keeps New export enabled', () => {
    state.capabilities = caps(true, { reports_enabled: false });
    state.capsLoading = false;
    renderSection();

    expect(screen.getByRole('button', { name: 'New export' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'New report' })).toBeDisabled();
  });
});

describe('DataExchangeSection creation dialogs', () => {
  it('queues an export through the dialog and posts the frozen request body', async () => {
    const user = userEvent.setup();
    state.capabilities = ENABLED;
    state.capsLoading = false;
    renderSection();

    await user.click(screen.getByRole('button', { name: 'New export' }));
    await user.type(await screen.findByLabelText('Resource'), 'profile360');
    await user.click(screen.getByRole('button', { name: 'Queue export' }));

    await waitFor(() => {
      expect(state.createExport).toHaveBeenCalledWith({
        resource: 'profile360',
        format: 'json',
        include_identifiers: false,
        include_provenance: false,
      });
    });
    await waitFor(() => {
      expect(
        screen.queryByRole('heading', { name: 'New data export' }),
      ).not.toBeInTheDocument();
    });
  });

  it('queues a report through the dialog with the chosen template', async () => {
    const user = userEvent.setup();
    state.capabilities = ENABLED;
    state.capsLoading = false;
    renderSection();

    await user.click(screen.getByRole('button', { name: 'New report' }));
    await user.selectOptions(await screen.findByLabelText('Template'), 'compliance');
    await user.type(screen.getByLabelText('Resource'), 'profile360');
    await user.click(screen.getByRole('button', { name: 'Queue report' }));

    await waitFor(() => {
      expect(state.createReport).toHaveBeenCalledWith({
        resource: 'profile360',
        template: 'compliance',
      });
    });
  });
});
