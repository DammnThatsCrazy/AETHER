import {
  Card, CardHeader, CardTitle, CardContent,
  Badge, StatusIndicator,
  DataTable,
  ScrollArea,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { useMLModels, useMLOverview } from '@kyber/features/ml';

type MLModelRow = {
  name: string;
  version: string;
  type: string;
  status: string;
};

function fleetStatusToIndicator(status: string): 'healthy' | 'degraded' | 'unhealthy' | 'unknown' {
  if (status === 'healthy') return 'healthy';
  if (status === 'degraded' || status === 'partial') return 'degraded';
  if (status === 'unhealthy' || status === 'error') return 'unhealthy';
  return 'unknown';
}

function modelStatusToIndicator(status: string): 'healthy' | 'degraded' | 'unhealthy' | 'unknown' {
  if (status === 'loaded') return 'healthy';
  if (status === 'degraded') return 'degraded';
  if (status === 'error') return 'unhealthy';
  return 'unknown';
}

const MODEL_COLUMNS = [
  {
    key: 'name',
    header: 'Model',
    render: (row: MLModelRow) => <span className="font-mono text-sm">{row.name}</span>,
  },
  {
    key: 'version',
    header: 'Version',
    render: (row: MLModelRow) => (
      <span className="font-mono text-xs text-text-secondary">{row.version || '—'}</span>
    ),
  },
  {
    key: 'type',
    header: 'Type',
    render: (row: MLModelRow) => <Badge variant="info">{row.type}</Badge>,
  },
  {
    key: 'status',
    header: 'Status',
    render: (row: MLModelRow) => (
      <div className="flex items-center gap-2">
        <StatusIndicator status={modelStatusToIndicator(row.status)} />
        <span className="text-sm capitalize">{row.status}</span>
      </div>
    ),
  },
] as const;

export function MLAdminPage() {
  const models = useMLModels();
  const overview = useMLOverview();

  const overviewData = overview.data as Record<string, unknown> | null;
  const fleetStatus: string =
    ((overviewData?.overview as Record<string, unknown> | undefined)?.fleet_status as string) ?? 'unknown';
  const modelsLoaded: number =
    ((overviewData?.overview as Record<string, unknown> | undefined)?.models_loaded as number) ?? 0;
  const modelsTotal: number =
    ((overviewData?.overview as Record<string, unknown> | undefined)?.models_total as number) ?? 0;
  const extractionEnabled: boolean = !!(
    (overviewData?.security as Record<string, unknown> | undefined)?.extraction_defense_enabled
  );

  const modelRows: MLModelRow[] = ((models.data as unknown[]) ?? []).map((m) => {
    const row = m as Record<string, unknown>;
    return {
      name: String(row.name ?? ''),
      version: String(row.version ?? ''),
      type: String(row.type ?? ''),
      status: String(row.status ?? 'unknown'),
    };
  });

  return (
    <PageWrapper title="ML Operations" subtitle="Model fleet health, artifacts, and extraction defense">
      <div className="flex flex-col gap-6">

        <Card>
          <CardHeader>
            <CardTitle>Fleet Overview</CardTitle>
          </CardHeader>
          <CardContent>
            {overview.isLoading ? (
              <p className="text-sm text-text-secondary">Loading…</p>
            ) : overview.error ? (
              <p className="text-sm text-danger">Failed to load overview.</p>
            ) : (
              <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
                <div>
                  <p className="text-xs text-text-secondary uppercase tracking-wide">Fleet status</p>
                  <div className="mt-1 flex items-center gap-2">
                    <StatusIndicator status={fleetStatusToIndicator(fleetStatus)} />
                    <span className="font-semibold capitalize">{fleetStatus}</span>
                  </div>
                </div>
                <div>
                  <p className="text-xs text-text-secondary uppercase tracking-wide">Models loaded</p>
                  <p className="mt-1 text-2xl font-mono font-bold">
                    {modelsLoaded}
                    <span className="text-base text-text-secondary">/{modelsTotal}</span>
                  </p>
                </div>
                <div>
                  <p className="text-xs text-text-secondary uppercase tracking-wide">Extraction defense</p>
                  <div className="mt-1">
                    <Badge variant={extractionEnabled ? 'success' : 'warning'}>
                      {extractionEnabled ? 'Enabled' : 'Disabled'}
                    </Badge>
                  </div>
                </div>
                <div>
                  <p className="text-xs text-text-secondary uppercase tracking-wide">Readiness</p>
                  <div className="mt-1">
                    <Badge variant={fleetStatus === 'healthy' ? 'success' : 'warning'}>
                      {fleetStatus === 'healthy' ? 'Production ready' : 'Needs attention'}
                    </Badge>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Model Fleet</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ScrollArea className="max-h-[480px]">
              {models.isLoading ? (
                <p className="p-6 text-sm text-text-secondary">Loading models…</p>
              ) : models.error ? (
                <p className="p-6 text-sm text-danger">Failed to load model list.</p>
              ) : (
                <DataTable
                  columns={MODEL_COLUMNS}
                  data={modelRows}
                  keyExtractor={(row) => row.name}
                />
              )}
            </ScrollArea>
          </CardContent>
        </Card>

      </div>
    </PageWrapper>
  );
}
