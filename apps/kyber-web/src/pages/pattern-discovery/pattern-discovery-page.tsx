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
  usePatternCuration,
  usePatternDetail,
  usePatternGraph,
  usePatternQueue,
  usePatternWhatsNew,
  type DiscoveredPatternDetail,
  type DiscoveredPatternSummary,
  type PatternVerdict,
} from '@kyber/features/pattern-discovery';

const COPY =
  'Patterns nobody defined in advance, discovered from raw and semi-structured evidence and surfaced ' +
  'to tenants automatically once they clear the confidence and novelty bar. Every item stays inferred, ' +
  'with capped confidence and competing explanations, and stays reviewable: hide, pin, rename or give a ' +
  'verdict at any time. Nothing here merges identities or blocks a transaction; only a deliberate ' +
  'promotion creates attributed Risk360 signals.';

type BadgeVariant = 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info';

const SEVERITY_VARIANT: Record<string, BadgeVariant> = {
  critical: 'danger',
  high: 'warning',
  medium: 'info',
  low: 'default',
};

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  surfaced: 'warning',
  candidate: 'default',
  hidden: 'default',
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
        {item.pinned ? <Badge size="sm" variant="accent">pinned</Badge> : null}
        <Badge variant={SEVERITY_VARIANT[item.severity ?? 'low'] ?? 'default'} size="sm">{item.severity ?? 'low'}</Badge>
        <Badge variant={STATUS_VARIANT[item.status] ?? 'default'} size="sm">{humanize(item.status)}</Badge>
        <span className="text-xs font-mono text-text-muted">{humanize(item.kind)}</span>
        {item.suppressed_by_feedback ? <Badge size="sm">suppressed by feedback</Badge> : null}
      </div>
      <div className="text-sm text-text-primary">{item.title}</div>
      <div className="text-xs font-mono text-text-muted">
        {item.affected_entity_count} entities · confidence {pct(item.confidence)} (cap {pct(item.confidence_cap)}) ·
        novelty {pct(item.novelty)} · surfaced {when(item.surfaced_at)} · last seen {when(item.last_observed_at)}
      </div>
    </button>
  );
}

function CurationPanel({ tenantId, detail, onChanged }: {
  readonly tenantId: string;
  readonly detail: DiscoveredPatternDetail;
  readonly onChanged: () => void;
}) {
  const curation = usePatternCuration(tenantId);
  const [title, setTitle] = useState('');
  const hidden = detail.status === 'hidden';
  const act = async (action: 'pin' | 'unpin' | 'hide' | 'unhide' | 'rename', newTitle?: string) => {
    if (await curation.curate(detail.pattern_id, action, newTitle)) {
      if (action === 'rename') setTitle('');
      onChanged();
    }
  };
  return (
    <Card>
      <CardHeader><CardTitle>Curation</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-text-muted">
          Curation changes how the pattern is presented to the tenant without a verdict. A hidden pattern
          resurfaces only if its evidence materially changes.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" disabled={curation.busy}
            onClick={() => act(detail.pinned ? 'unpin' : 'pin')}>{detail.pinned ? 'Unpin' : 'Pin'}</Button>
          <Button size="sm" variant="ghost" disabled={curation.busy}
            onClick={() => act(hidden ? 'unhide' : 'hide')}>{hidden ? 'Unhide' : 'Hide'}</Button>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs font-mono text-text-muted">
            Display title
            <Input aria-label="Display title" value={title} placeholder={detail.title} onChange={e => setTitle(e.target.value)} />
          </label>
          <Button size="sm" variant="ghost" disabled={curation.busy || !title.trim()}
            onClick={() => act('rename', title.trim())}>Rename</Button>
        </div>
        {detail.detector_title && detail.detector_title !== detail.title ? (
          <div className="text-xs font-mono text-text-muted">detector title: {detail.detector_title}</div>
        ) : null}
        {curation.error ? <div className="text-xs text-status-danger font-mono">{curation.error}</div> : null}
      </CardContent>
    </Card>
  );
}

function GraphPanel({ tenantId, patternId }: { readonly tenantId: string; readonly patternId: string }) {
  const graph = usePatternGraph(tenantId, patternId);
  if (graph.loading && !graph.data) return <LoadingState lines={3} />;
  if (graph.error) return <EmptyState title="Unable to load the pattern graph" description={graph.error} />;
  const data = graph.data;
  if (!data) return null;
  const byRole = (role: string) => data.nodes.filter(n => n.role === role);
  const groups: Array<[string, string]> = [
    ['member', 'Members'], ['attribute', 'Shared values'], ['principal', 'Principals'], ['member_pattern', 'Member patterns'],
  ];
  return (
    <Card data-testid="kyber-pattern-graph">
      <CardHeader><CardTitle>Pattern graph</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-xs font-mono">
        <div className="text-text-muted">
          {data.nodes.length} nodes · {data.edges.length} links{data.truncated ? ' · truncated' : ''}
        </div>
        {groups.map(([role, heading]) => {
          const nodes = byRole(role);
          if (nodes.length === 0) return null;
          return (
            <div key={role}>
              <div className="text-text-secondary">{heading} ({nodes.length})</div>
              <div className="flex flex-wrap gap-1">
                {nodes.slice(0, 60).map(n => (
                  <span key={n.id} className="border border-border-default rounded px-1" title={`${n.kind}: ${n.id}`}>{n.label}</span>
                ))}
              </div>
            </div>
          );
        })}
        <details>
          <summary className="cursor-pointer text-text-secondary">Links</summary>
          <ul className="mt-1 space-y-0.5">
            {data.edges.slice(0, 120).map((e, i) => <li key={i}>{e.source} —{humanize(e.type)}→ {e.target}</li>)}
          </ul>
        </details>
      </CardContent>
    </Card>
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
      <CardHeader><CardTitle>Analyst decision (optional)</CardTitle></CardHeader>
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
      <CurationPanel tenantId={tenantId} detail={data} onChanged={() => { refresh(); onChanged(); }} />
      <GraphPanel tenantId={tenantId} patternId={data.pattern_id} />
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
  const fresh = usePatternWhatsNew(tenantId);
  const curation = usePatternCuration(tenantId);

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
            Open feed
          </Button>
          <Select label="Status" value={status} onChange={setStatus}
            options={PATTERN_STATUS_FILTERS.map(s => ({
              value: s,
              label: s === '' ? 'surfaced feed' : s === 'candidate' ? 'watching (below bar)' : humanize(s),
            }))} />
          <Select label="Kind" value={kind} onChange={setKind}
            options={[{ value: '', label: 'all kinds' }, ...PATTERN_KINDS.map(k => ({ value: k, label: humanize(k) }))]} />
          <Button size="sm" variant="secondary" disabled={!tenantId || actions.busy}
            onClick={async () => { if (await actions.run()) { queue.refresh(); fresh.refresh(); } }}>
            {actions.busy ? 'Running discovery…' : 'Run discovery'}
          </Button>
          {actions.error ? <span className="text-xs text-status-danger font-mono">{actions.error}</span> : null}
        </CardContent>
      </Card>
      {tenantId && fresh.data && (fresh.data.new.length > 0 || fresh.data.changed.length > 0 || fresh.data.retired.length > 0) ? (
        <Card data-testid="kyber-pattern-whats-new">
          <CardContent className="space-y-2">
            <div className="flex flex-wrap items-center gap-3 text-xs font-mono">
              <span>Since you last looked ({when(fresh.data.since)}):</span>
              <span>{fresh.data.new.length} new</span>
              <span>{fresh.data.changed.length} changed</span>
              <span>{fresh.data.retired.length} retired</span>
              <Button size="sm" variant="ghost" onClick={async () => { if (await curation.markSeen()) fresh.refresh(); }}>
                Mark seen
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {[...fresh.data.new, ...fresh.data.changed].slice(0, 8).map(p => (
                <button key={p.pattern_id} type="button" className="text-xs underline text-left" onClick={() => setSelected(p.pattern_id)}>
                  {p.title}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}
      {!tenantId ? (
        <EmptyState title="Choose a tenant" description="Discovered patterns are per tenant; name one to open its feed." />
      ) : queue.loading && !queue.data ? (
        <LoadingState lines={6} />
      ) : queue.error ? (
        <EmptyState title="Unable to load discovered patterns" description={queue.error} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <div className="text-xs font-mono text-text-muted">{queue.data?.total ?? 0} patterns</div>
            {(queue.data?.items ?? []).length === 0 ? (
              <EmptyState title="Nothing surfaced" description="No patterns match this filter. Run discovery to analyse recent evidence." />
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
              <EmptyState title="Select a pattern" description="Evidence, the pattern graph, curation and the optional review controls appear here." />
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
            description="Operator pattern curation is restricted to operators with approval permissions."
          />
        }
      >
        <DiscoveryQueue />
      </PermissionGate>
    </PageWrapper>
  );
}
