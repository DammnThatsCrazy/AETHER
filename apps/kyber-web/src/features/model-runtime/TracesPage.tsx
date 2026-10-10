/**
 * Kyber — model-runtime routing decision traces (ADR-008 D8/D9).
 *
 * Read-only control-plane surface: recent model-routing decision traces
 * (`GET /v1/model-runtime/traces`). Each row shows how one routing decision
 * resolved — the requested → selected model, the routing mode, the entitlement
 * decision, whether a fallback fired, the terminal status and the latency.
 *
 * Trace fields are identifiers, statuses and latencies — never credentials and
 * never request bodies. This surface renders exactly those columns and nothing
 * else; the sibling test asserts the rendered text contains no `sk-` / `AKIA` /
 * `Bearer` substrings, guarding against a regression that ever puts request or
 * credential material on screen.
 *
 * The typed contract (`ModelRuntimeAdminApi`, `RoutingTrace`,
 * `TracesResponse`) lives in `./types` (C14-F). Tests inject a stub via the
 * `api` prop; the default is the real-endpoint typed client.
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
import { defaultModelRuntimeAdminApi } from './types';
import type { ModelRuntimeAdminApi, RoutingTrace } from './types';

const EMPTY_CORRELATION = '—';
const NO_REQUESTED_MODEL = '—';

export interface TracesPageProps {
  /** Injectable typed client — defaults to the real-endpoint client. */
  readonly api?: Pick<ModelRuntimeAdminApi, 'fetchTraces'>;
}

export function TracesPage({ api = defaultModelRuntimeAdminApi }: TracesPageProps) {
  const [traces, setTraces] = useState<RoutingTrace[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.fetchTraces();
      setTraces(result.traces);
    } catch (err) {
      setTraces(null);
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PageWrapper
      title="Model routing traces"
      subtitle="Recent model-routing decision traces — how each routing decision resolved. Read-only; credentials and request bodies are never rendered."
    >
      {loading && (
        <div
          role="status"
          aria-label="Loading traces"
          className="rounded border border-border-subtle p-2"
        >
          <LoadingState lines={4} />
        </div>
      )}

      {!loading && error !== null && (
        <ErrorState title="Unable to load traces" message={error} onRetry={load} />
      )}

      {!loading && error === null && traces !== null && traces.length === 0 && (
        <EmptyState
          title="No routing traces"
          description="Routing decisions appear here once the model-runtime control plane records one."
        />
      )}

      {!loading && error === null && traces !== null && traces.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Recent decisions</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-xs font-mono border-collapse">
              <caption className="sr-only">Model routing decision traces</caption>
              <thead>
                <tr className="border-b border-border-default text-text-muted">
                  <th className="py-2 px-2 text-left">Trace</th>
                  <th className="py-2 px-2 text-left">Correlation</th>
                  <th className="py-2 px-2 text-left">Tenant</th>
                  <th className="py-2 px-2 text-left">Profile</th>
                  <th className="py-2 px-2 text-left">Requested → Selected</th>
                  <th className="py-2 px-2 text-left">Mode</th>
                  <th className="py-2 px-2 text-left">Entitled</th>
                  <th className="py-2 px-2 text-left">Fallback</th>
                  <th className="py-2 px-2 text-left">Status</th>
                  <th className="py-2 px-2 text-right">Latency</th>
                </tr>
              </thead>
              <tbody>
                {traces.map(trace => (
                  <tr
                    key={trace.traceId}
                    className="border-b border-border-default text-text-secondary align-top"
                  >
                    <td className="py-2 px-2 text-text-primary">{trace.traceId}</td>
                    <td className="py-2 px-2">{trace.correlationId ?? EMPTY_CORRELATION}</td>
                    <td className="py-2 px-2">{trace.tenantId}</td>
                    <td className="py-2 px-2">{trace.profileId}</td>
                    <td className="py-2 px-2 text-text-primary">
                      {`${trace.requestedModel ?? NO_REQUESTED_MODEL} → ${trace.selectedModel}`}
                    </td>
                    <td className="py-2 px-2">{trace.mode}</td>
                    <td className="py-2 px-2">{trace.entitled ? 'Yes' : 'No'}</td>
                    <td className="py-2 px-2">{trace.fallback ? 'Yes' : 'No'}</td>
                    <td className="py-2 px-2">{trace.status}</td>
                    <td className="py-2 px-2 text-right">{`${trace.latencyMs} ms`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </PageWrapper>
  );
}
