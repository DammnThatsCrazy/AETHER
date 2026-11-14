import { useState } from 'react';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, Input, LoadingState, Select,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { PermissionGate } from '@kyber/features/permissions';
import {
  PATTERN_KINDS,
  PATTERN_STATUS_FILTERS,
  PATTERN_VERDICTS,
  usePatternActions,
  usePatternDetail,
  usePatternQueue,
  type DiscoveredPatternDetail,
  type DiscoveredPatternSummary,
  type PatternVerdict,
} from '@kyber/features/pattern-discovery';

const COPY =
  'Patterns nobody defined in advance, discovered from raw and semi-structured evidence. ' +
  'Every item is an inferred candidate with capped confidence and competing explanations. ' +
  'Nothing here merges identities, blocks a transaction or writes graph facts; only a promotion ' +
  'after review creates attributed Risk360 signals.';

type BadgeVariant = 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

const SEVERITY_VARIANT: Record<string, BadgeVariant> = {
  critical: 'danger',
  high: 'warning',
  medium: 'info',
  low: 'default',
};

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  needs_review: 'warning',
  candidate: 'default',
  confirmed_valid: 'info',
  confirmed_malicious: 'danger',
  benign: 'success',
  duplicate: 'default',
  unresolved: 'accent',
  promoted: 'danger',
  deprecated: 'default',
};

function humanize(value: unknown): string {
  return String(value ?? '—').replace(/_/g, ' ');
}

function pct(value: unknown): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '—';
}

function when(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toISOString().replace('T', ' ').slice(0, 16);
}

function QueueRow({ item, selected, onSelect }: {
  readonly item: DiscoveredPatternSummary;
  readonly selected: boolean;
  readonly onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(item.pattern_id)}
      className={`w-full text-left border rounded p-3 space-y-1 ${selected ? 'border-border-focus bg-surface-raised' : 'border-border-default'}`}
      aria-pressed={selected}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={SEVERITY_VARIANT[item.severity ?? 'low'] ?? 'default'} size="sm">{item.severity ?? 'low'}</Badge>
        <Badge variant={STATUS_VARIANT[item.status] ?? 'default'} size="sm">{humanize(item.status)}</Badge>
        <span className="text-xs font-mono text-text-muted">{humanize(item.kind)}</span>
        {item.suppressed_by_feedback ? <Badge size="sm">suppressed by feedback</Badge> : null}
      </div>
      <div className="text-sm text-text-primary">{item.title}</div>
      <div className="text-xs font-mono text-text-muted">
        {item.affected_entity_count} entities · confidence {pct(item.confidence)} (cap {pct(item.confidence_cap)}) ·
        novelty {pct(item.novelty)} · last seen {when(item.last_observed_at)}
      </div>
    </button>
  );
}

function ReviewPanel({ tenantId, detail, onChanged }: {
  readonly tenantId: string;
  readonly detail: DiscoveredPatternDetail;
  readonly onChanged: () => void;
}) {
  const actions = usePatternActions(tenantId);
  const [verdict, setVerdict] = useState<PatternVerdict>('valid');
  const [reason, setReason] = useState('');
  const [duplicateOf, setDuplicateOf] = useState('');
  const reasonOk = reason.trim().length >= 10;
  const promotable = detail.status === 'confirmed_valid' || detail.status === 'confirmed_malicious';

  const after = async (p: Promise<unknown>) => {
    const res = await p;
    if (res) {
      setReason('');
      onChanged();
    }
  };

  return (
    <Card>
      <CardHeader><CardTitle>Analyst decision</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Verdict"
            value={verdict}
            onChange={(v) => setVerdict(v as PatternVerdict)}
            options={PATTERN_VERDICTS.map(v => ({ value: v, label: humanize(v) }))}
          />
          {verdict === 'duplicate' ? (
            <label className="text-xs font-mono text-text-muted">
              Duplicate of (pattern id)
              <Input aria-label="Duplicate of" value={duplicateOf} onChange={e => setDuplicateOf(e.target.value)} />
            </label>
          ) : null}
        </div>
        <label className="block text-xs font-mono text-text-muted">
          Reason (at least 10 characters; recorded in the review history and used to calibrate detectors)
          <Input aria-label="Reason" value={reason} onChange={e => setReason(e.target.value)} />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={!reasonOk || actions.busy || (verdict === 'duplicate' && !duplicateOf.trim())}
            onClick={() => after(actions.review(detail.pattern_id, verdict, reason.trim(), duplicateOf.trim() || undefined))}>
            Record verdict
          </Button>
          <Button size="sm" variant="danger" disabled={!reasonOk || actions.busy || !promotable}
            onClick={() => after(actions.promote(detail.pattern_id, reason.trim()))}
            title={promotable ? 'Writes attributed Risk360 signals for resolvable subjects' : 'Confirm the pattern first'}>
            Promote to risk
          </Button>
          <Button size="sm" variant="ghost" disabled={!reasonOk || actions.busy || detail.status === 'deprecated'}
            onClick={() => after(actions.deprecate(detail.pattern_id, reason.trim()))}>
            Deprecate
          </Button>
        </div>
        {actions.error ? <div className="text-xs text-status-danger font-mono">{actions.error}</div> : null}
      </CardContent>
    </Card>
  );
}

function DetailPanel({ tenantId, patternId, onChanged }: {
  readonly tenantId: string;
  readonly patternId: string;
  readonly onChanged: () => void;
}) {
  const { data, loading, error, refresh } = usePatternDetail(tenantId, patternId);
  if (loading && !data) return <LoadingState lines={6} />;
  if (error) return <EmptyState title="Unable to load pattern" description={error} />;
  if (!data) return null;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>{data.title}</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p className="text-text-secondary">{data.summary}</p>
          <div className="flex flex-wrap gap-2">
            {data.risk_categories.map(c => <Badge key={c} size="sm" variant="info">{c}</Badge>)}
          </div>
          <div className="text-xs font-mono text-text-muted">
            v{data.version} · observed {data.times_observed ?? 1}× · first {when(data.first_observed_at)} ·
            claim {data.claim_state ?? 'inferred'}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Evidence</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {data.evidence.map(e => (
            <div key={e.type} className="border border-border-default rounded p-2">
              <div className="flex items-center gap-2 text-xs font-mono">
                <Badge size="sm" variant={e.basis === 'observed' ? 'success' : 'accent'}>{e.basis}</Badge>
                <span>{humanize(e.type)}</span>
                <span className="text-text-muted">strength {e.strength.toFixed(2)}</span>
              </div>
              <pre className="mt-1 text-[11px] text-text-muted whitespace-pre-wrap break-all">
                {JSON.stringify(e.detail, null, 1).slice(0, 1200)}
              </pre>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Competing explanations</CardTitle></CardHeader>
        <CardContent>
          <ul className="list-disc pl-5 space-y-1 text-sm text-text-secondary">
            {data.competing_explanations.map(c => <li key={c.id}><span className="font-mono text-xs">{c.id}</span>: {c.note}</li>)}
          </ul>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Affected entities ({data.affected_entity_count})</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-1">
          {data.affected_entities.slice(0, 60).map(e => (
            <span key={e.key} className="text-[11px] font-mono border border-border-default rounded px-1">{e.key}</span>
          ))}
        </CardContent>
      </Card>
      {data.members.length > 0 || data.similar_patterns.length > 0 ? (
        <Card>
          <CardHeader><CardTitle>Related patterns</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-xs font-mono">
            {data.members.map(m => <div key={m.pattern_id}>member · {humanize(m.kind)} · {m.title}</div>)}
            {data.similar_patterns.map(m => <div key={m.pattern_id}>similar · {humanize(m.kind)} · {m.title}</div>)}
          </CardContent>
        </Card>
      ) : null}
      <ReviewPanel tenantId={tenantId} detail={data} onChanged={() => { refresh(); onChanged(); }} />
      {data.review_history.length > 0 ? (
        <Card>
          <CardHeader><CardTitle>Review history</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-xs font-mono">
            {data.review_history.map((h, i) => (
              <div key={i}>{when(h.at)} · {String(h.reviewer_id ?? 'system')} · {humanize(h.decision)} · {String(h.reason ?? '')}</div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function DiscoveryQueue() {
  const [tenantInput, setTenantInput] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [status, setStatus] = useState('');
  const [kind, setKind] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const queue = usePatternQueue(tenantId, status, kind);
  const actions = usePatternActions(tenantId);

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3">
          <label className="text-xs font-mono text-text-muted">
            Tenant ID (required)
            <Input aria-label="Tenant ID" value={tenantInput} placeholder="tenant identifier"
              onChange={e => setTenantInput(e.target.value)} />
          </label>
          <Button size="sm" disabled={!tenantInput.trim()} onClick={() => { setTenantId(tenantInput.trim()); setSelected(null); }}>
            Open queue
          </Button>
          <Select label="Status" value={status} onChange={setStatus}
            options={PATTERN_STATUS_FILTERS.map(s => ({ value: s, label: s ? humanize(s) : 'open review queue' }))} />
          <Select label="Kind" value={kind} onChange={setKind}
            options={[{ value: '', label: 'all kinds' }, ...PATTERN_KINDS.map(k => ({ value: k, label: humanize(k) }))]} />
          <Button size="sm" variant="secondary" disabled={!tenantId || actions.busy}
            onClick={async () => { if (await actions.run()) queue.refresh(); }}>
            {actions.busy ? 'Running discovery…' : 'Run discovery'}
          </Button>
          {actions.error ? <span className="text-xs text-status-danger font-mono">{actions.error}</span> : null}
        </CardContent>
      </Card>
      {!tenantId ? (
        <EmptyState title="Choose a tenant" description="The discovery queue is per tenant; name one to open it." />
      ) : queue.loading && !queue.data ? (
        <LoadingState lines={6} />
      ) : queue.error ? (
        <EmptyState title="Unable to load the discovery queue" description={queue.error} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <div className="text-xs font-mono text-text-muted">{queue.data?.total ?? 0} patterns</div>
            {(queue.data?.items ?? []).length === 0 ? (
              <EmptyState title="Nothing to review" description="No patterns match this filter. Run discovery to analyse recent evidence." />
            ) : (
              (queue.data?.items ?? []).map(item => (
                <QueueRow key={item.pattern_id} item={item} selected={selected === item.pattern_id} onSelect={setSelected} />
              ))
            )}
          </div>
          <div>
            {selected ? (
              <DetailPanel tenantId={tenantId} patternId={selected} onChanged={queue.refresh} />
            ) : (
              <EmptyState title="Select a pattern" description="Evidence, competing explanations and the review controls appear here." />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function PatternDiscoveryPage() {
  return (
    <PageWrapper title="Pattern Discovery" subtitle={COPY}>
      <PermissionGate
        requires="canApprove"
        fallback={
          <EmptyState
            title="Operator approval permissions required"
            description="The discovery queue is restricted to operators with approval permissions."
          />
        }
      >
        <DiscoveryQueue />
      </PermissionGate>
    </PageWrapper>
  );
}
