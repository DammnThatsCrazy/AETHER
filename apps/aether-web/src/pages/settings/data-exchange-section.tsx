import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  StatusIndicator,
  Modal,
  ModalBody,
  ModalHeader,
  ModalFooter,
  formatDate,
  useCapabilities,
  useTimeContext,
  useToast,
} from '@aether/ui';
import {
  useDataExchangeArtifacts,
  useDataExchangeCapabilities,
  useDataExchangeDownloadUrl,
  useCreateDataExchangeExport,
  useCreateDataExchangeReport,
  dataExchangeSurfaceEnabled,
  type DataExchangeArtifact,
  type DataExchangeSurface,
  type CreateDataExchangeExportInput,
  type CreateDataExchangeReportInput,
} from '@aether-app/features/data-exchange';

/** Artifact status → status-indicator state for the history table. */
function artifactIndicator(status: DataExchangeArtifact['status']): 'healthy' | 'degraded' | 'unknown' {
  if (status === 'available' || status === 'committed') return 'healthy';
  if (status === 'failed' || status === 'expired' || status === 'deleted' || status === 'revoked') {
    return 'degraded';
  }
  return 'unknown';
}

function artifactKindLabel(artifact: DataExchangeArtifact): string {
  if (artifact.artifact_type === 'report') return 'Report';
  return artifact.direction === 'ingress' ? 'Import' : 'Export';
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function CreatedCell({ iso }: { iso: string }) {
  const timeCtx = useTimeContext();
  return <span className="text-xs text-text-secondary">{formatDate(iso, timeCtx)}</span>;
}

/** Download affordance for a terminal (available/committed) object-store
 * artifact — resolves the M2 signed download URL and opens it. */
function ArtifactDownloadButton({ artifactId }: { artifactId: string }) {
  const { download, loading, error } = useDataExchangeDownloadUrl(artifactId);
  const disabled = loading || download === null;
  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={disabled}
      title={error ?? 'Resolve signed download URL'}
      onClick={() => {
        if (download?.download_url) {
          window.open(download.download_url, '_blank', 'noopener,noreferrer');
        }
      }}
    >
      {loading ? '…' : download ? 'Download' : '—'}
    </Button>
  );
}

const SURFACES: readonly { key: DataExchangeSurface; label: string }[] = [
  { key: 'imports', label: 'Import engine' },
  { key: 'exports', label: 'Exports' },
  { key: 'reports', label: 'Reports' },
  { key: 'transfers', label: 'Signed transfers' },
];

// ── Export creation dialog ───────────────────────────────────────────────────

const EXPORT_FORMATS = ['csv', 'json', 'ndjson', 'parquet'] as const;

interface ExportDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onCreated: (result: { export_id: string }) => void;
}

function NewExportDialog({ open, onClose, onCreated }: ExportDialogProps) {
  const { toast } = useToast();
  const { create, loading } = useCreateDataExchangeExport();
  const [resource, setResource] = useState('');
  const [format, setFormat] = useState<(typeof EXPORT_FORMATS)[number]>('json');
  const [includeIdentifiers, setIncludeIdentifiers] = useState(false);
  const [includeProvenance, setIncludeProvenance] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!resource.trim()) return;
    const input: CreateDataExchangeExportInput = {
      resource: resource.trim(),
      format,
      include_identifiers: includeIdentifiers,
      include_provenance: includeProvenance,
    };
    const result = await create(input);
    if (result) {
      onCreated(result);
      toast.success('Export queued — it will appear in artifact history once ready.');
      setResource('');
      setFormat('json');
      setIncludeIdentifiers(false);
      setIncludeProvenance(false);
    } else {
      toast.error('Export failed — please try again.');
    }
  }

  return (
    <Modal open={open} onClose={onClose}>
      <ModalHeader>
        <h2 className="text-sm font-medium text-text-primary font-mono">New data export</h2>
      </ModalHeader>
      <form onSubmit={(e) => { void handleSubmit(e); }}>
        <ModalBody className="space-y-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="dx-export-resource" className="text-xs text-text-secondary">Resource</label>
            <input
              id="dx-export-resource"
              type="text"
              required
              value={resource}
              onChange={e => setResource(e.target.value)}
              placeholder="e.g. profile360"
              className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="dx-export-format" className="text-xs text-text-secondary">Format</label>
            <select
              id="dx-export-format"
              value={format}
              onChange={e => setFormat(e.target.value as (typeof EXPORT_FORMATS)[number])}
              className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus"
            >
              {EXPORT_FORMATS.map(f => (
                <option key={f} value={f}>{f.toUpperCase()}</option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={includeIdentifiers}
              onChange={e => setIncludeIdentifiers(e.target.checked)}
              className="accent-accent"
            />
            Include identifiers
          </label>
          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={includeProvenance}
              onChange={e => setIncludeProvenance(e.target.checked)}
              className="accent-accent"
            />
            Include provenance
          </label>
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" size="sm" type="button" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={!resource.trim() || loading}
          >
            {loading ? '[···]' : 'Queue export'}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  );
}

// ── Report creation dialog ───────────────────────────────────────────────────

const REPORT_TEMPLATES = ['standard', 'compliance', 'operations', 'full'] as const;

interface ReportDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onCreated: (result: { report_id: string }) => void;
}

function NewReportDialog({ open, onClose, onCreated }: ReportDialogProps) {
  const { toast } = useToast();
  const { create, loading } = useCreateDataExchangeReport();
  const [resource, setResource] = useState('');
  const [template, setTemplate] = useState<(typeof REPORT_TEMPLATES)[number]>('standard');

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!resource.trim()) return;
    const input: CreateDataExchangeReportInput = {
      resource: resource.trim(),
      template,
    };
    const result = await create(input);
    if (result) {
      onCreated(result);
      toast.success('Report queued — it will appear in artifact history once generated.');
      setResource('');
      setTemplate('standard');
    } else {
      toast.error('Report failed — please try again.');
    }
  }

  return (
    <Modal open={open} onClose={onClose}>
      <ModalHeader>
        <h2 className="text-sm font-medium text-text-primary font-mono">New report</h2>
      </ModalHeader>
      <form onSubmit={(e) => { void handleSubmit(e); }}>
        <ModalBody className="space-y-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="dx-report-resource" className="text-xs text-text-secondary">Resource</label>
            <input
              id="dx-report-resource"
              type="text"
              required
              value={resource}
              onChange={e => setResource(e.target.value)}
              placeholder="e.g. profile360"
              className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="dx-report-template" className="text-xs text-text-secondary">Template</label>
            <select
              id="dx-report-template"
              value={template}
              onChange={e => setTemplate(e.target.value as (typeof REPORT_TEMPLATES)[number])}
              className="bg-surface-raised text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus"
            >
              {REPORT_TEMPLATES.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" size="sm" type="button" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={!resource.trim() || loading}
          >
            {loading ? '[···]' : 'Queue report'}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  );
}

// ── Section ──────────────────────────────────────────────────────────────────

export function DataExchangeSection() {
  const { capabilities, loading: capsLoading, error: capsError, refresh: refreshCaps } =
    useDataExchangeCapabilities();
  const {
    artifacts,
    count,
    loading: artifactsLoading,
    error: artifactsError,
    refresh: refreshArtifacts,
  } = useDataExchangeArtifacts({ limit: 25 });
  const [exportOpen, setExportOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);

  const enabled = capabilities?.data_exchange?.enabled === true;
  const exportsEnabled = dataExchangeSurfaceEnabled(capabilities, 'exports');
  const reportsEnabled = dataExchangeSurfaceEnabled(capabilities, 'reports');

  function renderArtifactTable() {
    const columns = [
      {
        key: 'kind',
        header: 'Kind',
        render: (row: DataExchangeArtifact) => (
          <span className="flex items-center gap-1.5 text-xs">
            <span className="font-mono text-[10px] text-text-muted">
              {row.direction === 'ingress' ? 'in' : 'out'}
            </span>
            <span className="text-text-primary font-medium">{artifactKindLabel(row)}</span>
          </span>
        ),
      },
      {
        key: 'name',
        header: 'Artifact',
        render: (row: DataExchangeArtifact) => (
          <span className="text-xs font-mono text-text-secondary truncate max-w-[18rem] block">
            {row.filename ?? row.artifact_id}
          </span>
        ),
      },
      {
        key: 'format',
        header: 'Format',
        render: (row: DataExchangeArtifact) =>
          row.format ? (
            <Badge variant="default" size="sm" className="font-mono">{row.format.toUpperCase()}</Badge>
          ) : (
            <span className="text-xs text-text-muted">—</span>
          ),
      },
      {
        key: 'status',
        header: 'Status',
        render: (row: DataExchangeArtifact) => (
          <span className="flex items-center gap-1.5 text-xs">
            <StatusIndicator status={artifactIndicator(row.status)} />
            <span className="text-text-secondary capitalize">{row.status.replace(/_/g, ' ')}</span>
          </span>
        ),
      },
      {
        key: 'created_at',
        header: 'Created',
        render: (row: DataExchangeArtifact) => <CreatedCell iso={row.created_at} />,
      },
      {
        key: 'size_bytes',
        header: 'Size',
        render: (row: DataExchangeArtifact) => (
          <span className="text-xs text-text-muted">{formatBytes(row.size_bytes)}</span>
        ),
      },
      {
        key: 'actions',
        header: '',
        render: (row: DataExchangeArtifact) =>
          row.status === 'available' || row.status === 'committed' ? (
            <ArtifactDownloadButton artifactId={row.artifact_id} />
          ) : (
            <span className="text-xs text-text-muted">—</span>
          ),
      },
    ];

    if (artifactsLoading) return <LoadingState lines={3} />;
    if (artifactsError) {
      return (
        <ErrorState
          message="Failed to load artifact history"
          onRetry={refreshArtifacts}
        />
      );
    }
    if (artifacts.length === 0) {
      return (
        <EmptyState
          title="No data exchange artifacts yet"
          description="Imports, exports, and reports you create will appear here."
        />
      );
    }
    return (
      <DataTable
        caption="Data exchange artifact history"
        columns={columns}
        data={artifacts}
        keyExtractor={(row: DataExchangeArtifact) => row.artifact_id}
      />
    );
  }

  return (
    <Card id="data-exchange" data-testid="data-exchange-section">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-mono text-text-muted">Data Exchange</CardTitle>
          {enabled && (
            <div className="flex items-center gap-2">
              <Button variant="primary" size="sm" disabled={!exportsEnabled} onClick={() => setExportOpen(true)}>
                New export
              </Button>
              <Button variant="primary" size="sm" disabled={!reportsEnabled} onClick={() => setReportOpen(true)}>
                New report
              </Button>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {capsLoading && <LoadingState lines={2} />}
        {capsError && (
          <ErrorState
            message="Failed to load Data Exchange state"
            onRetry={refreshCaps}
          />
        )}
        {!capsLoading && !capsError && capabilities === null && (
          <p className="text-xs text-danger font-mono">Data Exchange is unavailable.</p>
        )}
        {!capsLoading && !capsError && capabilities !== null && !enabled && (
          <EmptyState
            title="Data Exchange is not enabled for this workspace"
            description="Enable the Data Exchange capability to import, export, and report on governed data."
          />
        )}
        {!capsLoading && !capsError && enabled && (
          <>
            <div className="flex flex-wrap items-center gap-2" data-testid="dx-capability-summary">
              <span className="text-[10px] font-mono text-text-muted uppercase tracking-wide">
                Capability surface
              </span>
              {SURFACES.map(s => {
                const on = dataExchangeSurfaceEnabled(capabilities, s.key);
                return (
                  <Badge key={s.key} variant={on ? 'success' : 'default'} size="sm">
                    <span className="flex items-center gap-1">
                      <StatusIndicator status={on ? 'healthy' : 'unknown'} />
                      {s.label}
                    </span>
                  </Badge>
                );
              })}
            </div>
            <div className="pt-1 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-mono text-text-secondary">
                  Artifact history{count > 0 ? ` · ${count}` : ''}
                </p>
              </div>
              {renderArtifactTable()}
            </div>
          </>
        )}
      </CardContent>

      <NewExportDialog
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        onCreated={() => setExportOpen(false)}
      />
      <NewReportDialog
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        onCreated={() => setReportOpen(false)}
      />
    </Card>
  );
}

/**
 * Settings-page gate for the Data Exchange surface.
 *
 * The backend mounts /v1/data-exchange/* only while the plane is enabled, so a
 * disabled plane must not trigger the surface's fetches (they would 404 and
 * render an ErrorState).  This wrapper consults the CANONICAL capability
 * contract (GET /v1/capabilities → feature_flags.data_exchange_enabled) — the
 * same setting that gates the router mount — and only mounts the DX-hook
 * surface component when the plane is on.  While canonical capabilities are
 * still resolving we render an honest loading state so neither a failing DX
 * request nor the not-enabled EmptyState flashes; when the plane is off we show
 * the same not-enabled EmptyState the surface itself renders.
 */
export function DataExchangeGate() {
  const { capabilities, loading } = useCapabilities();
  const enabled = capabilities?.feature_flags?.data_exchange_enabled === true;

  if (enabled) {
    return <DataExchangeSection />;
  }
  if (loading && capabilities === null) {
    return (
      <Card id="data-exchange" data-testid="data-exchange-section">
        <CardHeader>
          <CardTitle className="text-sm font-mono text-text-muted">Data Exchange</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <LoadingState lines={2} />
        </CardContent>
      </Card>
    );
  }
  return (
    <Card id="data-exchange" data-testid="data-exchange-section">
      <CardHeader>
        <CardTitle className="text-sm font-mono text-text-muted">Data Exchange</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <EmptyState
          title="Data Exchange is not enabled for this workspace"
          description="Enable the Data Exchange capability to import, export, and report on governed data."
        />
      </CardContent>
    </Card>
  );
}
