/**
 * Kyber model-runtime usage admin surface (ADR-008 D8).
 *
 * Read-only operator view of aggregate and per-model call/token/cost totals
 * for a period. Costs are display-only currency. Credentials are NEVER
 * rendered — the usage contract (`./types`, C14-F) carries only ids, counts,
 * and USD cost.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import type { ModelRuntimeAdminApi, UsageByModel, UsageResponse } from './types';
import { defaultModelRuntimeAdminApi } from './types';

/** Locale-explicit, deterministic USD rendering — display-only currency. */
function formatUsd(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  }).format(value);
}

interface UsagePageProps {
  /** Injectable typed client — defaults to the real model-runtime admin client. */
  readonly api?: ModelRuntimeAdminApi;
}

export function UsagePage({ api = defaultModelRuntimeAdminApi }: UsagePageProps) {
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const result = await api.fetchUsage();
      setUsage(result);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const period = usage?.period ?? '';
  const totals = usage?.totals ?? { calls: 0, inputTokens: 0, outputTokens: 0, costUsd: 0 };
  const byModel: UsageByModel[] = usage?.byModel ?? [];

  return (
    <PageWrapper
      title="Model Runtime Usage"
      subtitle="Aggregate and per-model call, token, and cost totals. Read-only — costs are display-only currency and credentials are never exposed."
    >
      {loading && (
        <div role="status" aria-label="Loading usage">
          <LoadingState lines={5} />
        </div>
      )}

      {!loading && error && (
        <ErrorState
          title="Unable to load usage"
          message="The model-runtime usage endpoint could not be reached. Retry to load it again."
          onRetry={() => void load()}
        />
      )}

      {!loading && !error && usage !== null && (
        <>
          <div className="flex items-center gap-2 text-xs text-text-muted font-mono">
            <span>Usage period</span>
            <span className="text-text-primary font-semibold">{period}</span>
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <SummaryCard label="Calls" value={totals.calls} />
            <SummaryCard label="Input tokens" value={totals.inputTokens} />
            <SummaryCard label="Output tokens" value={totals.outputTokens} />
            <SummaryCard label="Cost in USD" value={formatUsd(totals.costUsd)} />
          </div>

          <Card aria-label="Model usage">
            <CardHeader>
              <CardTitle>Per-model usage</CardTitle>
            </CardHeader>
            <CardContent>
              {byModel.length === 0 ? (
                <EmptyState
                  title="No model usage recorded"
                  description="Per-model usage appears here once the model-runtime control plane records invocations."
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono border-collapse" aria-label="Model usage table">
                    <thead>
                      <tr className="border-b border-border-default text-text-muted">
                        <th className="py-2 px-2 text-left">Model</th>
                        <th className="py-2 px-2 text-right">Calls</th>
                        <th className="py-2 px-2 text-right">Input</th>
                        <th className="py-2 px-2 text-right">Output</th>
                        <th className="py-2 px-2 text-right">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {byModel.map((row) => (
                        <tr key={row.modelId} className="border-b border-border-subtle hover:bg-surface-hover">
                          <td className="py-2 px-2 font-medium text-text-primary">{row.modelId}</td>
                          <td className="py-2 px-2 text-right">{row.calls}</td>
                          <td className="py-2 px-2 text-right">{row.inputTokens}</td>
                          <td className="py-2 px-2 text-right">{row.outputTokens}</td>
                          <td className="py-2 px-2 text-right whitespace-nowrap">{formatUsd(row.costUsd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-2 text-[10px] text-text-muted font-mono">
                    Costs are display-only currency. Provider API keys and credentials are never stored or rendered in Kyber.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </PageWrapper>
  );
}

function SummaryCard({ label, value }: { readonly label: string; readonly value: unknown }) {
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold text-text-primary">{String(value ?? 0)}</div>
      </CardContent>
    </Card>
  );
}
