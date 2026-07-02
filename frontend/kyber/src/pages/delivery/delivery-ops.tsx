import { useEffect, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { api } from '@kyber/lib/api';

type AnyRecord = Record<string, unknown>;

const STATE_VARIANT: Record<string, 'success' | 'warning' | 'danger' | 'default'> = {
  succeeded: 'success',
  queued: 'default',
  running: 'warning',
  leased: 'warning',
  failed: 'warning',
  dead_letter: 'danger',
  cancelled: 'default',
};

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—';
  try { return new Date(ts as string).toLocaleString(); } catch { return String(ts); }
}

function truncate(s: unknown, n = 12): string {
  const str = String(s ?? '');
  return str.length > n ? str.slice(0, n) + '…' : str;
}

type TabId = 'all' | 'dead_letter';

interface ReplayDialogProps {
  readonly job: AnyRecord;
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
}

function ReplayDialog({ job, onConfirm, onCancel }: ReplayDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-surface-default rounded-lg shadow-xl p-6 w-full max-w-sm space-y-4">
        <h2 className="text-base font-semibold">Replay dead-letter job?</h2>
        <p className="text-sm text-text-secondary">
          This will re-queue job <span className="font-mono">{truncate(job.id)}</span> for
          tenant <span className="font-mono">{String(job.tenant_id ?? '—')}</span> via{' '}
          <span className="font-mono">{String(job.provider_adapter ?? '—')}</span>.
          The job will start from attempt 1 with fresh leasing.
        </p>
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button variant="danger" onClick={onConfirm}>Replay</Button>
        </div>
      </div>
    </div>
  );
}

export function DeliveryOpsPage() {
  const [tab, setTab] = useState<TabId>('all');
  const [jobs, setJobs] = useState<AnyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tenantFilter, setTenantFilter] = useState('');
  const [providerFilter, setProviderFilter] = useState('');
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [replayTarget, setReplayTarget] = useState<AnyRecord | null>(null);
  const [replayMsg, setReplayMsg] = useState<string | null>(null);
  const PAGE_SIZE = 20;

  function load(p: number) {
    setLoading(true);
    const params: Record<string, string | number | undefined> = { page: p, per_page: PAGE_SIZE };
    if (tab === 'dead_letter') params.state = 'dead_letter';
    if (tenantFilter) params.tenant_id = tenantFilter;
    if (providerFilter) params.provider_adapter = providerFilter;

    (api.admin.kyber.listDeliveryJobs(params) as Promise<AnyRecord>)
      .then((d) => {
        const items = (((d).items) ?? []) as AnyRecord[];
        setJobs(items);
        setHasMore(items.length === PAGE_SIZE);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(page); }, [tab, page, tenantFilter, providerFilter]);

  function handleReplay(job: AnyRecord) {
    (api.admin.kyber.replayDeliveryJob(String(job.id)) as Promise<AnyRecord>)
      .then(() => {
        setReplayTarget(null);
        setReplayMsg(`Job ${truncate(job.id)} re-queued successfully.`);
        setTimeout(() => setReplayMsg(null), 4000);
        load(page);
      })
      .catch((e: unknown) => {
        setReplayTarget(null);
        setReplayMsg(`Replay failed: ${e instanceof Error ? e.message : String(e)}`);
        setTimeout(() => setReplayMsg(null), 6000);
      });
  }

  return (
    <PageWrapper
      title="Delivery Operations"
      subtitle="Cross-tenant delivery job management. Secrets and credentials are never shown here."
    >
      {replayMsg && (
        <div className="rounded border border-border-default px-3 py-2 text-sm bg-surface-subtle mb-2">
          {replayMsg}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex gap-1">
          {(['all', 'dead_letter'] as TabId[]).map((t) => (
            <Button
              key={t}
              size="sm"
              variant={tab === t ? 'primary' : 'secondary'}
              onClick={() => { setTab(t); setPage(1); }}
            >
              {t === 'all' ? 'All Jobs' : 'Dead-Letter'}
            </Button>
          ))}
        </div>
        <input
          className="border border-border-default rounded px-2 py-1 text-sm bg-surface-default text-text-primary font-mono w-48"
          placeholder="Filter by tenant ID…"
          value={tenantFilter}
          onChange={(e) => { setTenantFilter(e.target.value); setPage(1); }}
        />
        <input
          className="border border-border-default rounded px-2 py-1 text-sm bg-surface-default text-text-primary font-mono w-36"
          placeholder="Provider…"
          value={providerFilter}
          onChange={(e) => { setProviderFilter(e.target.value); setPage(1); }}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{tab === 'dead_letter' ? 'Dead-Letter Jobs' : 'All Delivery Jobs'}</CardTitle>
        </CardHeader>
        <CardContent>
          {loading
            ? <LoadingState lines={4} />
            : error
              ? <EmptyState title="Unable to load jobs" description={error} />
              : jobs.length === 0
                ? <EmptyState title="No jobs found" />
                : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono border-collapse">
                      <thead>
                        <tr className="border-b border-border-default text-text-muted">
                          <th className="py-2 px-2 text-left">Job ID</th>
                          <th className="py-2 px-2 text-left">Tenant</th>
                          <th className="py-2 px-2 text-left">Provider</th>
                          <th className="py-2 px-2 text-left">State</th>
                          <th className="py-2 px-2 text-right">Attempts</th>
                          <th className="py-2 px-2 text-left">Created</th>
                          <th className="py-2 px-2 text-left">External ID</th>
                          {tab === 'dead_letter' && <th className="py-2 px-2 text-left">Last Error</th>}
                          {tab === 'dead_letter' && <th className="py-2 px-2" />}
                        </tr>
                      </thead>
                      <tbody>
                        {jobs.map((j) => {
                          const state = String(j.state ?? '—');
                          return (
                            <tr key={String(j.id)} className="border-b border-border-subtle hover:bg-surface-hover">
                              <td className="py-1.5 px-2 text-text-muted">{truncate(j.id)}</td>
                              <td className="py-1.5 px-2 text-text-primary">{truncate(j.tenant_id, 16)}</td>
                              <td className="py-1.5 px-2">{String(j.provider_adapter ?? '—')}</td>
                              <td className="py-1.5 px-2"><Badge variant={STATE_VARIANT[state] ?? 'default'}>{state}</Badge></td>
                              <td className="py-1.5 px-2 text-right">{String(j.attempt_count ?? 0)}/{String(j.max_attempts ?? '—')}</td>
                              <td className="py-1.5 px-2 text-text-muted">{formatTs(j.created_at as string)}</td>
                              <td className="py-1.5 px-2">
                                {j.external_id
                                  ? j.external_url
                                    ? <a href={String(j.external_url)} target="_blank" rel="noreferrer" className="text-link hover:underline">{truncate(j.external_id, 20)}</a>
                                    : <span>{truncate(j.external_id, 20)}</span>
                                  : <span className="text-text-faint">—</span>}
                              </td>
                              {tab === 'dead_letter' && (
                                <td className="py-1.5 px-2 text-danger max-w-xs truncate" title={String(j.error_summary ?? '')}>
                                  {j.error_summary ? truncate(j.error_summary, 40) : '—'}
                                </td>
                              )}
                              {tab === 'dead_letter' && (
                                <td className="py-1.5 px-2">
                                  <Button
                                    size="sm"
                                    variant="secondary"
                                    onClick={() => setReplayTarget(j)}
                                  >
                                    Replay
                                  </Button>
                                </td>
                              )}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
          <div className="flex gap-2 justify-end mt-3">
            {page > 1 && <Button size="sm" variant="secondary" onClick={() => setPage(p => p - 1)}>Previous</Button>}
            {hasMore && <Button size="sm" variant="secondary" onClick={() => setPage(p => p + 1)}>Next</Button>}
          </div>
        </CardContent>
      </Card>

      {replayTarget && (
        <ReplayDialog
          job={replayTarget}
          onConfirm={() => handleReplay(replayTarget)}
          onCancel={() => setReplayTarget(null)}
        />
      )}
    </PageWrapper>
  );
}
