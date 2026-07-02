import { useEffect, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

type AnyRecord = Record<string, unknown>;

const STATE_VARIANT: Record<string, 'success' | 'warning' | 'danger' | 'default'> = {
  delivered: 'success',
  succeeded: 'success',
  pending: 'default',
  scheduled: 'default',
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

function ms(v: unknown): string {
  if (v == null) return '—';
  return `${v}ms`;
}

interface AttemptRowProps {
  readonly attempt: AnyRecord;
}

function AttemptRow({ attempt }: AttemptRowProps) {
  const outcome = String(attempt.outcome ?? '—');
  const variant = outcome === 'SUCCESS' ? 'success' : outcome.includes('ERROR') || outcome.includes('TIMEOUT') ? 'danger' : 'default';
  return (
    <tr className="border-t border-border-default text-xs">
      <td className="py-1 px-2 text-text-muted">#{String(attempt.attempt_number ?? '?')}</td>
      <td className="py-1 px-2"><Badge variant={variant}>{outcome}</Badge></td>
      <td className="py-1 px-2 text-text-muted">{String(attempt.http_status ?? '—')}</td>
      <td className="py-1 px-2 text-text-muted">{ms(attempt.latency_ms)}</td>
      <td className="py-1 px-2 text-text-muted truncate max-w-xs">{attempt.error_message ? String(attempt.error_message) : '—'}</td>
      <td className="py-1 px-2 text-text-muted">{formatTs(attempt.started_at as string)}</td>
    </tr>
  );
}

interface JobRowProps {
  readonly job: AnyRecord;
  readonly receipt: AnyRecord | null;
  readonly attempts: AnyRecord[];
  readonly expanded: boolean;
  readonly onToggle: () => void;
}

function JobRow({ job, receipt, attempts, expanded, onToggle }: JobRowProps) {
  const state = String(job.state ?? '—');
  return (
    <>
      <tr
        className="border-t border-border-default cursor-pointer hover:bg-surface-hover text-sm"
        onClick={onToggle}
      >
        <td className="py-2 px-3 font-mono text-xs text-text-muted">{String(job.provider_adapter ?? '—')}</td>
        <td className="py-2 px-3"><Badge variant={STATE_VARIANT[state] ?? 'default'}>{state}</Badge></td>
        <td className="py-2 px-3 text-text-muted">{String(job.attempt_count ?? 0)}/{String(job.max_attempts ?? '—')}</td>
        <td className="py-2 px-3 text-text-muted font-mono text-xs">
          {receipt?.external_id
            ? receipt.external_url
              ? <a href={String(receipt.external_url)} target="_blank" rel="noreferrer" className="text-link hover:underline" onClick={(e) => e.stopPropagation()}>{String(receipt.external_id)}</a>
              : <span>{String(receipt.external_id)}</span>
            : '—'}
        </td>
        <td className="py-2 px-3 text-text-muted text-xs">{formatTs(job.created_at as string)}</td>
        <td className="py-2 px-3 text-text-muted text-xs">{expanded ? '▲' : '▼'}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} className="bg-surface-subtle px-3 py-2">
            {state === 'dead_letter' && (
              <p className="text-xs text-danger mb-2">
                This delivery failed after all retry attempts. Contact support to replay.
                {job.error_summary ? ` Last error: ${String(job.error_summary)}` : ''}
              </p>
            )}
            {attempts.length === 0
              ? <p className="text-xs text-text-muted">No attempts recorded.</p>
              : (
                <table className="w-full">
                  <thead>
                    <tr className="text-xs text-text-muted">
                      <th className="text-left py-1 px-2">#</th>
                      <th className="text-left py-1 px-2">Outcome</th>
                      <th className="text-left py-1 px-2">HTTP</th>
                      <th className="text-left py-1 px-2">Latency</th>
                      <th className="text-left py-1 px-2">Error</th>
                      <th className="text-left py-1 px-2">Started</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attempts.map((a, i) => <AttemptRow key={i} attempt={a} />)}
                  </tbody>
                </table>
              )}
          </td>
        </tr>
      )}
    </>
  );
}

interface IntentCardProps {
  readonly intent: AnyRecord;
}

function IntentCard({ intent }: IntentCardProps) {
  const [jobs, setJobs] = useState<AnyRecord[]>([]);
  const [receipts, setReceipts] = useState<Record<string, AnyRecord>>({});
  const [attempts, setAttempts] = useState<Record<string, AnyRecord[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);

  function loadJobs() {
    if (loaded) return;
    setLoaded(true);
    api.delivery.listJobs({ intent_id: String(intent.id) })
      .then(async (d: unknown) => {
        const jobList = (((d as AnyRecord).items) ?? []) as AnyRecord[];
        setJobs(jobList);
        const rcpts: Record<string, AnyRecord> = {};
        const atts: Record<string, AnyRecord[]> = {};
        await Promise.allSettled(jobList.map(async (j) => {
          const jid = String(j.id);
          try {
            const r = await api.delivery.getReceipt(jid) as AnyRecord;
            if (r?.id) rcpts[jid] = r;
          } catch { /* no receipt yet */ }
          try {
            const a = await api.delivery.listAttempts(jid) as AnyRecord;
            atts[jid] = ((a?.items ?? []) as AnyRecord[]);
          } catch { atts[jid] = []; }
        }));
        setReceipts(rcpts);
        setAttempts(atts);
      })
      .catch(() => {/* silently stay empty */});
  }

  const source = String(intent.source_type ?? '—');
  const state = String(intent.state ?? '—');
  const channels = Array.isArray(intent.channels) ? intent.channels.join(', ') : '—';

  return (
    <Card>
      <CardHeader
        className="cursor-pointer select-none"
        onClick={loadJobs}
      >
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm font-mono">{String(intent.id).slice(0, 8)}…</CardTitle>
            <p className="text-xs text-text-muted mt-0.5">{source} · {channels} · {formatTs(intent.created_at as string)}</p>
          </div>
          <Badge variant={STATE_VARIANT[state] ?? 'default'}>{state}</Badge>
        </div>
      </CardHeader>
      {loaded && (
        <CardContent className="pt-0">
          {jobs.length === 0
            ? <p className="text-xs text-text-muted">No delivery jobs.</p>
            : (
              <table className="w-full">
                <thead>
                  <tr className="text-xs text-text-muted">
                    <th className="text-left py-1 px-3">Provider</th>
                    <th className="text-left py-1 px-3">State</th>
                    <th className="text-left py-1 px-3">Attempts</th>
                    <th className="text-left py-1 px-3">External ID</th>
                    <th className="text-left py-1 px-3">Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((j) => {
                    const jid = String(j.id);
                    return (
                      <JobRow
                        key={jid}
                        job={j}
                        receipt={receipts[jid] ?? null}
                        attempts={attempts[jid] ?? []}
                        expanded={expanded.has(jid)}
                        onToggle={() => setExpanded((prev) => {
                          const next = new Set(prev);
                          if (next.has(jid)) next.delete(jid); else next.add(jid);
                          return next;
                        })}
                      />
                    );
                  })}
                </tbody>
              </table>
            )}
        </CardContent>
      )}
    </Card>
  );
}

export function DeliveryHistoryPage() {
  const [intents, setIntents] = useState<AnyRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const PAGE_SIZE = 10;

  function load(p: number) {
    setLoading(true);
    api.delivery.listIntents({ page: p, per_page: PAGE_SIZE })
      .then((d: unknown) => {
        const items = (((d as AnyRecord).items) ?? []) as AnyRecord[];
        setIntents(items);
        setHasMore(items.length === PAGE_SIZE);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(page); }, [page]);

  if (loading) return <main className="p-6"><LoadingState lines={6} /></main>;
  if (error) return <main className="p-6"><EmptyState title="Unable to load delivery history" description={error} /></main>;

  return (
    <main className="p-6 space-y-4">
      <div>
        <h1 className="text-xl font-mono font-bold">Delivery History</h1>
        <p className="text-sm text-text-secondary">
          Outbound delivery intents for this tenant. Click an intent to see per-provider
          jobs, attempt details, and provider receipts.
        </p>
      </div>

      {intents.length === 0
        ? <EmptyState title="No delivery records" description="Approved suggestions and notifications will appear here once delivered." />
        : (
          <>
            <div className="space-y-3">
              {intents.map((intent) => <IntentCard key={String(intent.id)} intent={intent} />)}
            </div>
            <div className="flex gap-2 justify-end">
              {page > 1 && <Button variant="secondary" onClick={() => setPage(p => p - 1)}>Previous</Button>}
              {hasMore && <Button variant="secondary" onClick={() => setPage(p => p + 1)}>Next</Button>}
            </div>
          </>
        )}
    </main>
  );
}
