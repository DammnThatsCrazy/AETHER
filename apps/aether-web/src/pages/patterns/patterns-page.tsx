import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, Input,
  LoadingState, Select,
} from '@aether/ui';
import type { PatternVerdict } from '@aether/shared';
import {
  PATTERN_VERDICTS, PatternGraphCanvas, markPatternsSeen, usePatternCurate, usePatternDetail,
  usePatternDiscoveryEnabled, usePatternGraph, usePatternList, usePatternReview, useWhatsNew,
  type PatternSummaryRow,
} from '@aether-app/features/pattern-discovery';

function pct(v: unknown): string {
  return typeof v === 'number' ? `${Math.round(v * 100)}%` : '—';
}

function when(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toISOString().replace('T', ' ').slice(0, 16);
}

function Detail({ patternId, onChanged }: { patternId: string; onChanged: () => void }) {
  const detail = usePatternDetail(patternId);
  const graph = usePatternGraph(patternId);
  const { review, busy: reviewing, error: reviewError } = usePatternReview();
  const { curate, busy: curating, error: curateError } = usePatternCurate();
  const [verdict, setVerdict] = useState<PatternVerdict>('valid');
  const [reason, setReason] = useState('');
  const [title, setTitle] = useState('');
  if (detail.isLoading && !detail.data) return <LoadingState lines={5} />;
  if (detail.error) return <ErrorState title="Pattern unavailable" message={detail.error} onRetry={detail.refetch} />;
  const d = detail.data;
  if (!d) return null;
  const hidden = d.status === 'hidden';
  const after = async (ok: Promise<boolean>) => { if (await ok) { detail.refetch(); onChanged(); } };
  return (
    <Card data-testid="pattern-detail">
      <CardHeader><CardTitle>{d.title}</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-text-secondary">{d.summary}</p>
        <p className="text-xs text-text-secondary">
          {d.status.replace(/_/g, ' ')} · surfaced {when(d.surfaced_at)} · confidence {pct(d.confidence)} (cap {pct(d.confidence_cap)}) ·
          novelty {pct(d.novelty)} · {d.affected_entity_count} entities · claim {d.claim_state ?? 'inferred'}
          {d.detector_title && d.detector_title !== d.title ? ` · detector: ${d.detector_title}` : ''}
        </p>
        <div className="flex flex-wrap gap-2" data-testid="pattern-curation">
          <Button size="sm" variant="secondary" disabled={curating} onClick={() => after(curate(d.pattern_id, d.pinned ? 'unpin' : 'pin'))}>
            {d.pinned ? 'Unpin' : 'Pin'}
          </Button>
          <Button size="sm" variant="ghost" disabled={curating} onClick={() => after(curate(d.pattern_id, hidden ? 'unhide' : 'hide'))}>
            {hidden ? 'Unhide' : 'Hide'}
          </Button>
          <Link className="text-xs self-center hover:underline" to={`/explore?pattern=${encodeURIComponent(d.pattern_id)}`}>Show on graph →</Link>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-text-secondary">
            Rename
            <Input aria-label="New title" value={title} onChange={e => setTitle(e.target.value)} placeholder={d.title} />
          </label>
          <Button size="sm" variant="ghost" disabled={curating || !title.trim()}
            onClick={() => after(curate(d.pattern_id, 'rename', title.trim()).then(ok => { if (ok) setTitle(''); return ok; }))}>
            Save title
          </Button>
        </div>
        {curateError && <p className="text-xs text-status-danger">{curateError}</p>}
        {graph.data && <PatternGraphCanvas graph={graph.data} />}
        <div>
          <h4 className="text-xs font-medium">Evidence</h4>
          <ul className="list-disc pl-5 text-xs">
            {d.evidence.map(e => <li key={e.type}>{e.type.replace(/_/g, ' ')} ({e.basis}, strength {e.strength.toFixed(2)})</li>)}
          </ul>
        </div>
        <div>
          <h4 className="text-xs font-medium">Competing explanations</h4>
          <ul className="list-disc pl-5 text-xs">{d.competing_explanations.map(c => <li key={c.id}>{c.note}</li>)}</ul>
        </div>
        <details>
          <summary className="text-xs cursor-pointer">Record a verdict (optional)</summary>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <Select label="Verdict" value={verdict} onChange={v => setVerdict(v as PatternVerdict)}
              options={PATTERN_VERDICTS.filter(v => v !== 'duplicate').map(v => ({ value: v, label: v }))} />
            <label className="text-xs text-text-secondary">
              Reason (10+ characters)
              <Input aria-label="Reason" value={reason} onChange={e => setReason(e.target.value)} />
            </label>
            <Button size="sm" disabled={reviewing || reason.trim().length < 10}
              onClick={() => after(review(d.pattern_id, verdict, reason.trim()).then(ok => { if (ok) setReason(''); return ok; }))}>
              Record verdict
            </Button>
          </div>
          {reviewError && <p className="text-xs text-status-danger">{reviewError}</p>}
        </details>
      </CardContent>
    </Card>
  );
}

function Row({ row, selected, onSelect }: { row: PatternSummaryRow; selected: boolean; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected}
      className={`w-full rounded border p-3 text-left ${selected ? 'border-border-focus' : 'border-border-default'}`}>
      <div className="flex flex-wrap items-center gap-2">
        {row.pinned && <Badge size="sm">pinned</Badge>}
        <Badge size="sm">{row.severity ?? 'low'}</Badge>
        <Badge size="sm">{row.status.replace(/_/g, ' ')}</Badge>
        <span className="text-xs text-text-secondary">{row.kind.replace(/_/g, ' ')}</span>
      </div>
      <div className="text-sm">{row.title}</div>
      <div className="text-xs text-text-secondary">{row.affected_entity_count} entities · confidence {pct(row.confidence)} · surfaced {when(row.surfaced_at)}</div>
    </button>
  );
}

function List({ rows, selected, onSelect }: { rows: PatternSummaryRow[]; selected: string | null; onSelect: (id: string) => void }) {
  return <div className="space-y-2">{rows.map(r => <Row key={r.pattern_id} row={r} selected={r.pattern_id === selected} onSelect={() => onSelect(r.pattern_id)} />)}</div>;
}

/** Tenant view of automatically surfaced patterns: what is new, everything surfaced, and curation. */
export function PatternsPage() {
  const enabled = usePatternDiscoveryEnabled();
  const [params, setParams] = useSearchParams();
  const view = params.get('view') === 'new' ? 'new' : 'all';
  const [status, setStatus] = useState('');
  const list = usePatternList({ feed: status === '', status });
  const fresh = useWhatsNew('feed');
  const [marking, setMarking] = useState(false);
  const selected = params.get('pattern');
  const select = (id: string) => { const next = new URLSearchParams(params); next.set('pattern', id); setParams(next); };
  const setView = (v: 'new' | 'all') => { const next = new URLSearchParams(params); next.set('view', v); setParams(next); };
  if (!enabled) {
    return <EmptyState title="Pattern discovery is not enabled" description="Ask your administrator to enable pattern discovery for this workspace." />;
  }
  const newRows = fresh.data?.new ?? [];
  const changedRows = fresh.data?.changed ?? [];
  return (
    <div className="space-y-4" data-testid="patterns-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Discovered patterns</h1>
          <p className="text-xs text-text-secondary">Found and surfaced automatically from your evidence. Pin what matters, hide what doesn't, rename anything.</p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Button size="sm" variant={view === 'new' ? 'primary' : 'ghost'} onClick={() => setView('new')}>
            New since you last looked{fresh.data ? ` · ${newRows.length}` : ''}
          </Button>
          <Button size="sm" variant={view === 'all' ? 'primary' : 'ghost'} onClick={() => setView('all')}>All surfaced</Button>
          {view === 'all' && (
            <Select label="Show" value={status} onChange={setStatus} options={[
              { value: '', label: 'surfaced (default)' }, { value: 'candidate', label: 'watching (below bar)' },
              { value: 'hidden', label: 'hidden' }, { value: 'confirmed_malicious', label: 'confirmed malicious' },
              { value: 'benign', label: 'benign' }, { value: 'promoted', label: 'promoted' }, { value: 'deprecated', label: 'retired' },
            ]} />
          )}
        </div>
      </div>
      {view === 'new' ? (
        <section className="space-y-3" data-testid="patterns-whats-new">
          {fresh.isLoading && !fresh.data && <LoadingState lines={4} />}
          {fresh.error && <ErrorState title="What's new is unavailable" message={fresh.error} onRetry={fresh.refetch} />}
          {fresh.data && (
            <>
              <div className="flex flex-wrap items-center gap-3 text-xs text-text-secondary">
                <span>Since {when(fresh.data.since)}{fresh.data.since_source === 'default_lookback' ? ' (last 7 days)' : ''}:</span>
                <span>{newRows.length} new</span><span>{changedRows.length} changed</span><span>{fresh.data.retired.length} retired</span>
                <Button size="sm" variant="ghost" disabled={marking} onClick={async () => {
                  setMarking(true);
                  try { await markPatternsSeen('feed'); fresh.refetch(); } finally { setMarking(false); }
                }}>Mark all seen</Button>
              </div>
              {newRows.length === 0 && changedRows.length === 0 ? (
                <EmptyState title="Nothing new" description="No pattern surfaced or changed since you last looked." />
              ) : (
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-3">
                    {newRows.length > 0 && <><h3 className="text-sm font-medium">New</h3><List rows={newRows} selected={selected} onSelect={select} /></>}
                    {changedRows.length > 0 && <><h3 className="text-sm font-medium">Changed</h3><List rows={changedRows} selected={selected} onSelect={select} /></>}
                  </div>
                  <div>{selected ? <Detail patternId={selected} onChanged={() => { fresh.refetch(); list.refetch(); }} /> : (
                    <EmptyState title="Select a pattern" description="Its graph, evidence and curation controls appear here." />
                  )}</div>
                </div>
              )}
            </>
          )}
        </section>
      ) : (
        <>
          {list.isLoading && !list.data && <LoadingState lines={5} />}
          {list.error && <ErrorState title="Patterns unavailable" message={list.error} onRetry={list.refetch} />}
          {list.data && list.data.items.length === 0 && (
            <EmptyState title="Nothing to show" description="No discovered pattern matches this filter." />
          )}
          {list.data && list.data.items.length > 0 && (
            <div className="grid gap-4 lg:grid-cols-2">
              <List rows={list.data.items} selected={selected} onSelect={select} />
              <div>{selected ? <Detail patternId={selected} onChanged={list.refetch} /> : (
                <EmptyState title="Select a pattern" description="Its graph, evidence and curation controls appear here." />
              )}</div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
