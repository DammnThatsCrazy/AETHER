/**
 * Kyber Model Registry page (ADR-008 D8/D9).
 *
 * Read-only control-plane surface: every registered harness model, its
 * provider, lifecycle status, capability flags, and cost basis. There is no
 * mutation here and no credential material is ever rendered — costs are
 * display-only currency. Provider API keys / BYOK secrets never cross this
 * surface.
 *
 * The typed contract (`ModelRuntimeAdminApi`, `RegistryModel`,
 * `RegistryResponse`) lives in `./types` (C14-F). Tests inject a stub via the
 * `api` prop; the default is the real-endpoint typed client.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
  formatCurrency,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import {
  defaultModelRuntimeAdminApi,
  type ModelRuntimeAdminApi,
  type RegistryModel,
} from './types';

type BadgeVariant = 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

const STATUS_VARIANT: Record<RegistryModel['status'], BadgeVariant> = {
  recommended: 'success',
  stable: 'info',
  beta: 'accent',
  deprecated: 'danger',
  experimental: 'warning',
};

/** Display-only currency — never derived from or near credential material. */
function formatCost(model: RegistryModel): string {
  return `${formatCurrency(model.inputCostPerMTok, 'USD', { locale: 'en-US' })} in · ${formatCurrency(
    model.outputCostPerMTok,
    'USD',
    { locale: 'en-US' },
  )} out / 1M tokens`;
}

export interface ModelRegistryPageProps {
  /** Injectable typed client — defaults to the real-endpoint client. */
  readonly api?: ModelRuntimeAdminApi;
}

export function ModelRegistryPage({ api = defaultModelRuntimeAdminApi }: ModelRegistryPageProps) {
  const [models, setModels] = useState<RegistryModel[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const result = await api.fetchRegistry();
      setModels(result.models);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  // Group by provider — providers are only ever labels here; no credentials.
  const grouped = new Map<string, RegistryModel[]>();
  for (const model of models ?? []) {
    const existing = grouped.get(model.provider) ?? [];
    existing.push(model);
    grouped.set(model.provider, existing);
  }
  const groups = [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0]));

  return (
    <PageWrapper
      title="Model Registry"
      subtitle="Every registered harness model — provider, capability, status, and cost basis. Read-only; credentials are never exposed."
    >
      {loading && (
        <div role="status" aria-label="Loading registry" className="rounded border border-border-subtle p-2">
          <LoadingState lines={4} />
        </div>
      )}

      {!loading && error && (
        <ErrorState title="Unable to load registry" message="The model registry could not be reached. Retry to load it again." onRetry={load} />
      )}

      {!loading && !error && models !== null && models.length === 0 && (
        <EmptyState
          title="No models registered"
          description="Models appear here once they are registered with the harness control plane."
        />
      )}

      {!loading && !error && models !== null && models.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Registered models</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-xs font-mono border-collapse">
              <thead>
                <tr className="border-b border-border-default text-text-muted">
                  <th className="py-2 px-2 text-left">Provider</th>
                  <th className="py-2 px-2 text-left">Model</th>
                  <th className="py-2 px-2 text-left">Status</th>
                  <th className="py-2 px-2 text-left">Capabilities</th>
                  <th className="py-2 px-2 text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {groups.flatMap(([provider, rows]) =>
                  rows
                    .slice()
                    .sort((a, b) => a.modelId.localeCompare(b.modelId))
                    .map((model) => (
                      <tr key={model.modelId} className="border-b border-border-subtle">
                        <td className="py-2 px-2 text-text-secondary">{provider}</td>
                        <td className="py-2 px-2 font-semibold text-text-primary">{model.modelId}</td>
                        <td className="py-2 px-2">
                          <Badge variant={STATUS_VARIANT[model.status]} size="sm">
                            {model.status}
                          </Badge>
                        </td>
                        <td className="py-2 px-2">
                          <div className="flex flex-wrap gap-1">
                            {model.capabilities.map((cap) => (
                              <span
                                key={cap}
                                className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-text-secondary"
                              >
                                {cap}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-2 px-2 text-right text-text-secondary whitespace-nowrap">
                          {formatCost(model)}
                        </td>
                      </tr>
                    )),
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </PageWrapper>
  );
}
