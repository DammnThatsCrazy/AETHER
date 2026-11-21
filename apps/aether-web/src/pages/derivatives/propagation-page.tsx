import { useState } from 'react';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, DataTable, EmptyState, Input, LoadingState,
  queryCache, useQuery, useToast,
} from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { EvidenceBoundary, asList, asRecord, fmt } from '@aether-app/components/domain-intelligence';

type Row = Record<string, unknown>;
const RUNS_KEY = 'propagation:runs';

const CLASSIFICATION_LABELS: Record<string, string> = {
  organic: 'Organic',
  viral: 'Viral',
  coordinated: 'Coordinated',
  insufficient_data: 'Not enough data',
};

const STALE_REASONS: Record<string, string> = {
  source_grant_revoked: 'a member revoked access to an account it used',
  linked_population_changed: 'linked accounts changed since it ran',
  linked_population_unverifiable: 'linked accounts could not be checked',
};

/**
 * A `datetime-local` value (`YYYY-MM-DDTHH:mm`) in the browser's own time
 * zone. `compute` parses these inputs as local time, so the defaults must be
 * local too; `toISOString()` would put UTC clock values here and shift the
 * submitted window by the browser's UTC offset.
 */
export function localDateTimeDaysAgo(days: number, now: number = Date.now()): string {
  const d = new Date(now - days * 86_400_000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function PropagationPage() {
  const { toast } = useToast();
  const runs = useQuery({ key: RUNS_KEY, fetcher: () => api.propagation.listRuns(), staleTime: 30_000 });
  const [windowStart, setWindowStart] = useState(localDateTimeDaysAgo(7));
  const [windowEnd, setWindowEnd] = useState(localDateTimeDaysAgo(0));
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Row | null>(null);

  async function compute(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const run = asRecord(await api.propagation.run({
        window_start: new Date(windowStart).toISOString(),
        window_end: new Date(windowEnd).toISOString(),
        include_live: true,
        save: true,
      }));
      setSelected({ run, stale: false, stale_reasons: [] });
      queryCache.invalidate(RUNS_KEY);
      void runs.refetch();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function open(runId: string) {
    setBusy(true);
    try {
      setSelected(asRecord(await api.propagation.getRun(runId)));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function recompute(runId: string) {
    setBusy(true);
    try {
      setSelected({ ...asRecord(await api.propagation.recompute(runId)), stale: false, stale_reasons: [] });
      queryCache.invalidate(RUNS_KEY);
      void runs.refetch();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  const savedRows = asList(asRecord(runs.data).items).map(asRecord) as Row[];
  const run = selected ? asRecord(selected.run) : null;
  const episodes = run ? (asList(run.episodes).map(asRecord) as Row[]) : [];
  const limitations = run ? asList(run.limitations).map(String) : [];
  const staleReasons = selected ? asList(selected.stale_reasons).map(String) : [];

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Propagation</h1>
        <p className="text-sm text-text-secondary mt-1">
          How a trading behavior moved through your own members: who entered first, who followed after seeing
          them, and whether the spread looks organic, viral or coordinated. Read-only and limited to your linked members.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Compute a run</CardTitle></CardHeader>
        <CardContent>
          <form className="flex flex-wrap items-end gap-3" onSubmit={compute}>
            <Input label="From" type="datetime-local" value={windowStart} onChange={e => setWindowStart(e.target.value)} required />
            <Input label="To" type="datetime-local" value={windowEnd} onChange={e => setWindowEnd(e.target.value)} required />
            <Button type="submit" disabled={busy}>{busy ? 'Computing…' : 'Compute and save'}</Button>
          </form>
          <p className="text-xs text-text-secondary mt-2">
            Reads linked accounts first, through each member&apos;s consent and data-rights grant.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Saved runs</CardTitle></CardHeader>
        <CardContent>
          {runs.isLoading && !runs.data ? <LoadingState lines={3} /> : runs.error ? (
            <EmptyState title="Propagation is unavailable" description={String(runs.error)} />
          ) : savedRows.length === 0 ? (
            <EmptyState title="No saved runs" description="Compute a run above to keep it here." />
          ) : (
            <DataTable
              columns={[
                { key: 'saved_at', header: 'Saved', render: (r: Row) => fmt(r.saved_at) },
                { key: 'window', header: 'Window', render: (r: Row) => `${fmt(asRecord(r.query).window_start)} → ${fmt(asRecord(r.query).window_end)}` },
                { key: 'supersedes', header: 'Replaces', render: (r: Row) => (r.supersedes ? <span className="font-mono text-xs">{fmt(r.supersedes)}</span> : '—') },
                { key: 'open', header: '', render: (r: Row) => <Button size="sm" variant="ghost" disabled={busy} onClick={() => open(String(r.run_id))}>Open</Button> },
              ]}
              data={savedRows}
              keyExtractor={(r: Row) => String(r.run_id)}
            />
          )}
        </CardContent>
      </Card>

      {run && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Run {fmt(run.run_id)}</CardTitle>
            {selected?.stale ? (
              <div className="flex items-center gap-2">
                <Badge variant="warning">Out of date</Badge>
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => recompute(String(run.run_id))}>Recompute</Button>
              </div>
            ) : <Badge variant="success">Current</Badge>}
          </CardHeader>
          <CardContent className="space-y-3">
            {staleReasons.length > 0 && (
              <p className="text-xs text-text-secondary">
                Out of date because {staleReasons.map(r => STALE_REASONS[r] ?? r).join('; ')}.
              </p>
            )}
            <EvidenceBoundary>
              Classifications are inferred from observed timing and relationships. They are never causal claims.
              {limitations.length > 0 && ` Limits: ${limitations.join(', ')}.`}
            </EvidenceBoundary>
            {episodes.length === 0 ? (
              <EmptyState title="No episodes in this window" />
            ) : (
              <DataTable
                columns={[
                  { key: 'instrument', header: 'Instrument', render: (r: Row) => <span className="font-mono text-xs">{fmt(r.instrument_key)}</span> },
                  { key: 'side', header: 'Side', render: (r: Row) => fmt(r.side) },
                  { key: 'seed', header: 'First in', render: (r: Row) => fmt(r.seed_subject) },
                  { key: 'adopters', header: 'Members', render: (r: Row) => asList(r.adopters).length },
                  { key: 'reach', header: 'Exposed followers', render: (r: Row) => fmt(asRecord(r.metrics).exposed_adopters) },
                  { key: 'class', header: 'Pattern', render: (r: Row) => <Badge variant="default">{CLASSIFICATION_LABELS[String(r.classification)] ?? fmt(r.classification)}</Badge> },
                ]}
                data={episodes}
                keyExtractor={(r: Row) => String(r.episode_id)}
              />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
