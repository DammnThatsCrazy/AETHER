import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, Input,
  LoadingState, Select,
} from '@aether/ui';
import type { PatternVerdict } from '@aether/shared';
import {
  PATTERN_VERDICTS, usePatternDetail, usePatternDiscoveryEnabled, usePatternList, usePatternReview,
  type PatternSummaryRow,
} from '@aether-app/features/pattern-discovery';

function pct(v: unknown): string {
  return typeof v === 'number' ? `${Math.round(v * 100)}%` : '—';
}

function Detail({ patternId, onReviewed }: { patternId: string; onReviewed: () => void }) {
  const detail = usePatternDetail(patternId);
  const { review, busy, error } = usePatternReview();
  const [verdict, setVerdict] = useState<PatternVerdict>('valid');
  const [reason, setReason] = useState('');
  if (detail.isLoading && !detail.data) return <LoadingState lines={5} />;
  if (detail.error) return <ErrorState title="Pattern unavailable" message={detail.error} onRetry={detail.refetch} />;
  const d = detail.data;
  if (!d) return null;
  return (
    <Card data-testid="pattern-detail">
      <CardHeader><CardTitle>{d.title}</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-text-secondary">{d.summary}</p>
        <p className="text-xs text-text-secondary">
          confidence {pct(d.confidence)} (cap {pct(d.confidence_cap)}) · novelty {pct(d.novelty)} · {d.affected_entity_count} entities · claim {d.claim_state ?? 'inferred'}
        </p>
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
        <div className="flex flex-wrap items-end gap-2">
          <Select label="Verdict" value={verdict} onChange={v => setVerdict(v as PatternVerdict)}
            options={PATTERN_VERDICTS.filter(v => v !== 'duplicate').map(v => ({ value: v, label: v }))} />
          <label className="text-xs text-text-secondary">
            Reason (10+ characters)
            <Input aria-label="Reason" value={reason} onChange={e => setReason(e.target.value)} />
          </label>
          <Button size="sm" disabled={busy || reason.trim().length < 10}
            onClick={async () => { if (await review(d.pattern_id, verdict, reason.trim())) { setReason(''); detail.refetch(); onReviewed(); } }}>
            Record verdict
          </Button>
        </div>
        {error && <p className="text-xs text-status-danger">{error}</p>}
      </CardContent>
    </Card>
  );
}

function Row({ row, selected, onSelect }: { row: PatternSummaryRow; selected: boolean; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected}
      className={`w-full rounded border p-3 text-left ${selected ? 'border-border-focus' : 'border-border-default'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge size="sm">{row.severity ?? 'low'}</Badge>
        <Badge size="sm">{row.status.replace(/_/g, ' ')}</Badge>
        <span className="text-xs text-text-secondary">{row.kind.replace(/_/g, ' ')}</span>
      </div>
      <div className="text-sm">{row.title}</div>
      <div className="text-xs text-text-secondary">{row.affected_entity_count} entities · confidence {pct(row.confidence)}</div>
    </button>
  );
}

/** Tenant review queue for discovered patterns. Promotion stays an admin/operator act. */
export function PatternsPage() {
  const enabled = usePatternDiscoveryEnabled();
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState('');
  const list = usePatternList({ queue: status === '', status });
  const selected = params.get('pattern');
  if (!enabled) {
    return <EmptyState title="Pattern discovery is not enabled" description="Ask your administrator to enable pattern discovery for this workspace." />;
  }
  return (
    <div className="space-y-4" data-testid="patterns-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Discovered patterns</h1>
          <p className="text-xs text-text-secondary">Patterns nobody defined in advance, found in your evidence and waiting for review.</p>
        </div>
        <Select label="Status" value={status} onChange={setStatus} options={[
          { value: '', label: 'needs review' }, { value: 'candidate', label: 'candidate' },
          { value: 'confirmed_valid', label: 'confirmed valid' }, { value: 'confirmed_malicious', label: 'confirmed malicious' },
          { value: 'benign', label: 'benign' }, { value: 'promoted', label: 'promoted' },
        ]} />
      </div>
      {list.isLoading && !list.data && <LoadingState lines={5} />}
      {list.error && <ErrorState title="Patterns unavailable" message={list.error} onRetry={list.refetch} />}
      {list.data && list.data.items.length === 0 && (
        <EmptyState title="Nothing to review" description="No discovered pattern matches this filter." />
      )}
      {list.data && list.data.items.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            {list.data.items.map(row => (
              <Row key={row.pattern_id} row={row} selected={row.pattern_id === selected}
                onSelect={() => setParams({ pattern: row.pattern_id })} />
            ))}
          </div>
          <div>{selected ? <Detail patternId={selected} onReviewed={list.refetch} /> : (
            <EmptyState title="Select a pattern" description="Evidence, competing explanations and the verdict controls appear here." />
          )}</div>
        </div>
      )}
    </div>
  );
}
