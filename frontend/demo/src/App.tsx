import { useCallback, useEffect, useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle } from '@aether/ui';
import { getDemoConfig, type DemoConfig } from '@demo/lib/env';

export interface SeedRunSummary {
  readonly seed_run_id: string;
  readonly dataset_version: string;
  readonly namespace: string;
  readonly tenant_id: string;
  readonly checksum: string;
  readonly status: string;
  readonly started_at: string;
  readonly completed_at: string | null;
  readonly inserted_counts: Readonly<Record<string, number>>;
  readonly updated_counts: Readonly<Record<string, number>>;
  readonly skipped_counts: Readonly<Record<string, number>>;
}

export interface DemoSeedStatus {
  readonly seeded: boolean;
  readonly is_demo_tenant: boolean;
  readonly tenant_id: string;
  readonly tenant_name: string | null;
  readonly data_origin: string | null;
  readonly latest_run: SeedRunSummary | null;
}

type QueryState =
  | { readonly state: 'loading' }
  | { readonly state: 'error'; readonly message: string }
  | { readonly state: 'success'; readonly value: DemoSeedStatus };

function apiUrl(config: DemoConfig): string {
  const query = new URLSearchParams({
    tenant_id: config.tenantId,
    namespace: config.seedNamespace,
  });
  return `${config.apiBaseUrl}/v1/demo-seed/status?${query.toString()}`;
}

async function loadStatus(config: DemoConfig): Promise<DemoSeedStatus> {
  const response = await fetch(apiUrl(config), {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Backend seed status is unavailable (HTTP ${response.status}).`);
  }
  const body = (await response.json()) as { data?: DemoSeedStatus };
  if (!body.data || typeof body.data.seeded !== 'boolean') {
    throw new Error('Backend seed status returned an invalid response.');
  }
  return body.data;
}

function DemoDataBanner({ status }: { readonly status: DemoSeedStatus }) {
  if (!status.is_demo_tenant || !status.seeded || !status.latest_run) return null;
  return (
    <div
      role="status"
      data-testid="synthetic-data-banner"
      className="sticky top-0 z-50 -mx-6 -mt-6 mb-1 border-b border-warning bg-surface-raised px-6 py-2 text-xs font-medium text-warning"
    >
      Demo tenant — synthetic records were seeded into the backend. Dataset{' '}
      <span className="font-mono">{status.latest_run.dataset_version}</span> · namespace{' '}
      <span className="font-mono">{status.latest_run.namespace}</span>.
    </div>
  );
}

function CountList({
  title,
  counts,
}: {
  readonly title: string;
  readonly counts: Readonly<Record<string, number>>;
}) {
  const entries = Object.entries(counts).sort(([left], [right]) => left.localeCompare(right));
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-text-muted">No records reported.</p>
        ) : (
          <dl className="grid gap-2 text-sm">
            {entries.map(([domain, count]) => (
              <div key={domain} className="flex justify-between border-b border-border-default pb-1">
                <dt>{domain}</dt>
                <dd className="font-mono">{count}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

export function App({ config = getDemoConfig() }: { readonly config?: DemoConfig }) {
  const [query, setQuery] = useState<QueryState>({ state: 'loading' });
  const refresh = useCallback(async () => {
    setQuery({ state: 'loading' });
    try {
      setQuery({ state: 'success', value: await loadStatus(config) });
    } catch (error) {
      setQuery({
        state: 'error',
        message: error instanceof Error ? error.message : 'Backend seed status is unavailable.',
      });
    }
  }, [config]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const status = query.state === 'success' ? query.value : null;
  return (
    <div className="min-h-screen p-6 space-y-5">
      {status ? <DemoDataBanner status={status} /> : null}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border-default pb-4">
        <div>
          <h1 className="text-xl font-mono font-bold">Aether — Demo</h1>
          <p className="text-sm text-text-secondary">
            Backend-owned demonstration dataset status and provenance
          </p>
        </div>
        <Badge>{config.environment}</Badge>
      </header>

      {query.state === 'loading' ? (
        <Card>
          <CardContent className="py-8 text-sm" role="status" aria-label="Loading demo seed status">
            Loading backend seed status…
          </CardContent>
        </Card>
      ) : null}

      {query.state === 'error' ? (
        <Card>
          <CardHeader><CardTitle>Backend unavailable</CardTitle></CardHeader>
          <CardContent className="space-y-3" role="alert">
            <p className="text-sm text-text-secondary">{query.message}</p>
            <button className="rounded border border-border-default px-3 py-1 text-sm" onClick={() => void refresh()}>
              Retry
            </button>
          </CardContent>
        </Card>
      ) : null}

      {status && !status.seeded ? (
        <Card>
          <CardHeader><CardTitle>No demonstration dataset is seeded</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm text-text-secondary">
            <p>The backend returned a successful, authoritative empty seed status.</p>
            <p>
              Run <code>make demo-seed</code> explicitly, then retry. Normal development startup never
              inserts demonstration records.
            </p>
            <button className="rounded border border-border-default px-3 py-1 text-sm" onClick={() => void refresh()}>
              Retry
            </button>
          </CardContent>
        </Card>
      ) : null}

      {status?.seeded && status.latest_run ? (
        <>
          <Card>
            <CardHeader><CardTitle>{status.tenant_name ?? 'Demo tenant'}</CardTitle></CardHeader>
            <CardContent className="grid gap-2 text-sm md:grid-cols-2">
              <div>Tenant <span className="font-mono">{status.tenant_id}</span></div>
              <div>Run <span className="font-mono">{status.latest_run.seed_run_id}</span></div>
              <div>Checksum <span className="font-mono">{status.latest_run.checksum}</span></div>
              <div>Status <Badge variant="success">{status.latest_run.status}</Badge></div>
              <div>Started {status.latest_run.started_at}</div>
              <div>Completed {status.latest_run.completed_at ?? 'in progress'}</div>
            </CardContent>
          </Card>
          <div className="grid gap-4 lg:grid-cols-3">
            <CountList title="Inserted" counts={status.latest_run.inserted_counts} />
            <CountList title="Updated" counts={status.latest_run.updated_counts} />
            <CountList title="Idempotent skips" counts={status.latest_run.skipped_counts} />
          </div>
        </>
      ) : null}

      <footer className="flex flex-wrap gap-3 border-t border-border-default pt-4 text-sm">
        <a className="text-accent underline" href={config.aetherUrl}>Open Aether</a>
        <a className="text-accent underline" href={config.kyberUrl}>Open Kyber</a>
      </footer>
    </div>
  );
}
