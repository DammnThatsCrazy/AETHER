/**
 * Tenant model-routing preference panel (ADR-008 D4/D9).
 *
 * Lets an authorized tenant view and change their model routing preference.
 * The server is authoritative:
 *  - The panel NEVER stores or sends API keys / credentials, and never renders
 *    them. Model costs are display-only currency.
 *  - The panel NEVER lets a tenant override tenant scope — `tenantId` is
 *    informational context only (used in the surface label), never sent or
 *    mutated by the client.
 *
 * Surfaces are capability-gated (D8): renders nothing and fires no requests
 * while `enableModelHarness` is OFF. Data is mocked today; wiring to the real
 * model-runtime endpoints (GET /v1/model-runtime/models,
 * PUT /v1/model-runtime/tenant-default) is a later integration step. The typed
 * API contract (TenantModelSelectionApi + ModelRegistryModel) and the shared
 * typed client (defaultModelSelectionApi) live in `./types` (C13-F).
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
  formatCurrency,
  useTimeContext,
  type TimeContext,
} from '@aether/ui';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';
import type { ModelRegistryModel, TenantModelSelectionApi } from './types';
import { defaultModelSelectionApi } from './types';

interface ModelSelectionPanelProps {
  /** Informational tenant scope label — never sent to the server. */
  readonly tenantId?: string;
  /** Injectable typed client (defaults to the shared typed client from ./types). */
  readonly api?: TenantModelSelectionApi;
}

type BadgeVariant = 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

const STATUS_VARIANT: Record<ModelRegistryModel['status'], BadgeVariant> = {
  recommended: 'success',
  stable: 'info',
  beta: 'accent',
  deprecated: 'danger',
  experimental: 'warning',
};

function formatModelCost(model: ModelRegistryModel, timeCtx: TimeContext): string {
  return `${formatCurrency(model.inputCostPerMTok, 'USD', timeCtx)} in · ${formatCurrency(
    model.outputCostPerMTok,
    'USD',
    timeCtx,
  )} out / 1M tokens`;
}

export function ModelSelectionPanel({
  tenantId,
  api = defaultModelSelectionApi,
}: ModelSelectionPanelProps) {
  const enabled = isFeatureEnabled('enableModelHarness');
  const timeCtx = useTimeContext();

  const [models, setModels] = useState<ModelRegistryModel[] | null>(null);
  const [tenantDefaultModel, setTenantDefaultModel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    setSaveError(false);
    try {
      const result = await api.getModels();
      setModels(result.models);
      setTenantDefaultModel(result.tenantDefaultModel);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);

  async function handleSetDefault(modelId: string) {
    if (saving) return;
    setSaving(true);
    setSaveError(false);
    try {
      await api.setTenantDefault(modelId);
      // Server is authoritative — reflect the accepted default locally.
      setTenantDefaultModel(modelId);
    } catch {
      setSaveError(true);
    } finally {
      setSaving(false);
    }
  }

  if (!enabled) return null;

  return (
    <Card
      aria-label={tenantId ? `Model routing preference for ${tenantId}` : 'Model routing preference'}
    >
      <CardHeader>
        <CardTitle>Model routing preference</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-3 text-xs text-text-muted">
          Pick the model the platform routes routine tenant workloads to. Costs are display-only;
          the server never exposes credentials here.
        </p>

        {loading && (
          <div role="status" aria-label="Loading models" className="rounded border border-border-subtle p-2">
            <LoadingState lines={3} />
          </div>
        )}

        {!loading && loadError && (
          <ErrorState message="Unable to load models" onRetry={load} />
        )}

        {!loading && !loadError && models !== null && models.length === 0 && (
          <EmptyState
            title="No models available"
            description="The model catalog is empty for this tenant. Routing preferences will appear here once models are provisioned."
          />
        )}

        {!loading && !loadError && models !== null && models.length > 0 && (
          <ul className="space-y-2">
            {models.map(m => {
              const isDefault = m.modelId === tenantDefaultModel;
              return (
                <li
                  key={m.modelId}
                  className={`rounded border px-3 py-2 ${
                    isDefault
                      ? 'border-accent/50 bg-accent/5 ring-1 ring-accent/40'
                      : 'border-border-subtle bg-surface-raised/40'
                  }`}
                  aria-current={isDefault ? 'true' : undefined}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-medium text-text-primary">{m.modelId}</span>
                    <Badge variant="default" size="sm">{m.provider}</Badge>
                    <Badge variant={STATUS_VARIANT[m.status]} size="sm">{m.status}</Badge>
                    {isDefault && (
                      <Badge variant="accent" size="sm">Default</Badge>
                    )}
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1">
                    {m.capabilities.map(cap => (
                      <span
                        key={cap}
                        className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-text-secondary"
                      >
                        {cap}
                      </span>
                    ))}
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[10px] font-mono text-text-muted">
                      {formatModelCost(m, timeCtx)}
                    </span>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={saving}
                      onClick={() => void handleSetDefault(m.modelId)}
                    >
                      Set as default
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {saveError && (
          <p role="alert" className="mt-2 text-xs text-danger">
            Could not update the tenant default. Please try again.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
