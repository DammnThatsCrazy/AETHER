import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  DataTable, EmptyState, GlyphIcon, LoadingState, Modal,
  ModalBody, ModalFooter, ModalHeader, ScrollArea, Skeleton, StatusIndicator,
  TerminalSeparator, useToast,
} from '@aether/ui';
import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import { PermissionGate } from '@kyber/features/permissions';

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function severityVariant(s: unknown): 'danger' | 'warning' | 'default' {
  const str = String(s ?? '').toLowerCase();
  if (str === 'critical' || str === 'high') return 'danger';
  if (str === 'medium' || str === 'warning') return 'warning';
  return 'default';
}

// ── Health overview ────────────────────────────────────────────────────────────

function CisHealthPanel() {
  const { data, isLoading } = useQuery({
    key: 'cis:health:global',
    fetcher: () => api.cis.getGlobalHealth(),
    staleTime: 15_000,
  });

  if (isLoading) return <div className="grid grid-cols-2 md:grid-cols-4 gap-3">{[1,2,3,4].map(i => <Skeleton key={i} className="h-20" />)}</div>;
  if (!data) return null;

  const d = asRec(data);
  const metrics = [
    { label: 'Overall status', value: fmt(d.status ?? d.overall_status), isStatus: true },
    { label: 'Active mutations', value: fmt(d.active_mutations ?? d.mutation_count ?? 0) },
    { label: 'Drift alerts', value: fmt(d.drift_alert_count ?? d.drift_alerts ?? 0) },
    { label: 'Contamination score', value: fmt(d.contamination_score ?? d.contamination ?? '—') },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {metrics.map(m => (
        <Card key={m.label}>
          <CardContent className="p-4">
            <div className="text-[10px] uppercase text-text-muted font-mono">{m.label}</div>
            {m.isStatus ? (
              <div className="mt-1">
                <StatusIndicator status={(() => { const s = String(d.status ?? 'unknown'); return (s === 'healthy' || s === 'degraded' || s === 'unhealthy' ? s : 'unknown') as 'healthy' | 'degraded' | 'unhealthy' | 'unknown'; })()} label={fmt(d.status ?? 'unknown')} />
              </div>
            ) : (
              <div className="text-xl font-semibold font-mono text-text-primary mt-1">{m.value}</div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Mutations list ─────────────────────────────────────────────────────────────

type MutationRow = Record<string, unknown>;

function CisMutationsPanel() {
  const { toast } = useToast();
  const [actionId, setActionId] = useState<{ id: string; action: 'quarantine' | 'approve' } | null>(null);
  const [reason, setReason] = useState('');

  const { data, isLoading } = useQuery({
    key: 'cis:mutations',
    fetcher: () => api.cis.getMutations({ limit: 50 }),
    staleTime: 15_000,
  });

  const quarantine = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => api.cis.quarantineMutation(id, reason),
  });

  const approve = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => api.cis.approveMutation(id, reason),
  });

  const mutations = Array.isArray(data) ? data as MutationRow[] : Array.isArray(asRec(data).mutations) ? asRec(data).mutations as MutationRow[] : [];

  async function handleAction() {
    if (!actionId) return;
    try {
      let result: unknown;
      if (actionId.action === 'quarantine') {
        result = await quarantine.mutate({ id: actionId.id, reason });
      } else {
        result = await approve.mutate({ id: actionId.id, reason });
      }
      if (result === null) {
        toast.error(`${actionId.action === 'quarantine' ? 'Quarantine' : 'Approval'} failed`);
      } else {
        toast.success(actionId.action === 'quarantine' ? 'Mutation quarantined' : 'Mutation approved');
      }
      setActionId(null);
      setReason('');
    } catch {
      toast.error(`${actionId.action === 'quarantine' ? 'Quarantine' : 'Approval'} failed`);
    }
  }

  if (isLoading) return <LoadingState lines={5} />;
  if (mutations.length === 0) return <EmptyState title="No mutations" description="No active CIS mutations detected." />;

  return (
    <>
      <DataTable<MutationRow>
        keyExtractor={m => String(m.mutation_id ?? m.id ?? Math.random())}
        data={mutations}
        emptyMessage="No mutations"
        columns={[
          {
            key: 'id',
            header: 'Mutation ID',
            render: m => <span className="text-xs font-mono text-text-muted">{String(m.mutation_id ?? m.id ?? '—').slice(0, 12)}…</span>,
          },
          { key: 'type', header: 'Type', render: m => <Badge size="sm">{fmt(m.mutation_type ?? m.type)}</Badge> },
          {
            key: 'severity',
            header: 'Severity',
            render: m => <Badge variant={severityVariant(m.severity)} size="sm">{fmt(m.severity)}</Badge>,
          },
          { key: 'node', header: 'Node', render: m => <span className="text-xs font-mono">{fmt(m.node_id ?? m.entity_id)}</span> },
          {
            key: 'status',
            header: 'Status',
            render: m => {
              const s = fmt(m.status);
              return <Badge variant={s === 'quarantined' ? 'warning' : s === 'approved' ? 'success' : 'default'} size="sm">{s}</Badge>;
            },
          },
          {
            key: 'actions',
            header: '',
            render: m => (
              <PermissionGate requires="canApprove">
                <div className="flex gap-1">
                  <Button variant="ghost" size="sm" onClick={() => { setActionId({ id: String(m.mutation_id ?? m.id), action: 'quarantine' }); setReason(''); }}>
                    Quarantine
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => { setActionId({ id: String(m.mutation_id ?? m.id), action: 'approve' }); setReason(''); }}>
                    Approve
                  </Button>
                </div>
              </PermissionGate>
            ),
          },
        ]}
      />

      {actionId && (
        <Modal open onClose={() => setActionId(null)}>
          <ModalHeader>
            <h2 className="font-mono text-sm font-medium capitalize">{actionId.action} mutation</h2>
          </ModalHeader>
          <ModalBody>
            <p className="text-xs text-text-muted mb-3 font-mono">ID: {actionId.id}</p>
            <input
              className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
              placeholder="Reason (required)"
              value={reason}
              onChange={e => setReason(e.target.value)}
              autoFocus
            />
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setActionId(null)}>Cancel</Button>
            <Button
              variant={actionId.action === 'quarantine' ? 'danger' : 'primary'}
              size="sm"
              disabled={!reason.trim()}
              onClick={() => void handleAction()}
            >
              Confirm {actionId.action}
            </Button>
          </ModalFooter>
        </Modal>
      )}
    </>
  );
}

// ── Forensics (single node) ────────────────────────────────────────────────────

function CisForensicsPanel({ nodeId }: { nodeId: string }) {
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    key: `cis:forensics:${nodeId}`,
    fetcher: () => api.cis.getForensics(nodeId),
    staleTime: 60_000,
    enabled: !!nodeId,
  });

  if (isLoading) return <LoadingState lines={6} className="pt-2" />;
  if (!data) return <EmptyState title="Node not found" description={`No CIS forensics data for node ${nodeId}`} />;

  const d = asRec(data);
  const timeline = Array.isArray(d.timeline) ? d.timeline as unknown[] : [];
  const signals = Array.isArray(d.signals) ? d.signals as unknown[] : [];

  return (
    <div className="space-y-4 pt-2">
      <div className="flex items-center gap-2">
        <button onClick={() => navigate('/cis')} className="text-xs text-text-muted hover:text-accent font-mono">← CIS</button>
        <span className="text-xs text-text-muted">/</span>
        <span className="text-xs font-mono text-text-primary">{nodeId}</span>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Node type', value: fmt(d.node_type ?? d.kind) },
          { label: 'Trust score', value: fmt(d.trust_score) },
          { label: 'Risk level', value: fmt(d.risk_level ?? d.risk) },
        ].map(m => (
          <Card key={m.label}>
            <CardContent className="p-3">
              <div className="text-[10px] uppercase text-text-muted font-mono">{m.label}</div>
              <div className="text-sm font-mono text-text-primary mt-0.5">{m.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {signals.length > 0 && (
        <>
          <TerminalSeparator label="integrity signals" />
          <div className="space-y-2">
            {signals.map((s, i) => {
              const sr = asRec(s);
              return (
                <div key={i} className="flex items-center gap-3 border border-border-subtle rounded px-3 py-2 text-xs font-mono">
                  <Badge variant={severityVariant(sr.severity)} size="sm">{fmt(sr.severity)}</Badge>
                  <span className="text-text-primary">{fmt(sr.signal ?? sr.name ?? sr.type)}</span>
                  <span className="text-text-muted ml-auto">{fmt(sr.score)}</span>
                </div>
              );
            })}
          </div>
        </>
      )}

      {timeline.length > 0 && (
        <>
          <TerminalSeparator label="event timeline" />
          <ScrollArea maxHeight="300px">
            <div className="space-y-1.5">
              {timeline.map((e, i) => {
                const er = asRec(e);
                return (
                  <div key={i} className="text-xs font-mono flex items-center gap-3 border border-border-subtle rounded px-2 py-1.5">
                    <span className="text-text-muted">{fmt(er.ts ?? er.timestamp)}</span>
                    <span className="text-text-secondary">{fmt(er.event ?? er.type ?? er.action)}</span>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </>
      )}
    </div>
  );
}

// ── Drift panel ────────────────────────────────────────────────────────────────

function CisDriftPanel() {
  const { data, isLoading } = useQuery({
    key: 'cis:drift',
    fetcher: () => api.cis.getDrift({}),
    staleTime: 30_000,
  });

  if (isLoading) return <LoadingState lines={4} />;
  const d = asRec(data);
  const alerts = Array.isArray(d.alerts) ? d.alerts as unknown[] : Array.isArray(data) ? data as unknown[] : [];

  if (alerts.length === 0) return <EmptyState title="No drift detected" description="All graph nodes are within expected parameters." />;

  return (
    <div className="space-y-2">
      {alerts.map((a, i) => {
        const ar = asRec(a);
        return (
          <Card key={i}>
            <CardContent className="p-4 flex items-start gap-4">
              <Badge variant={severityVariant(ar.severity)} size="sm" className="mt-0.5">{fmt(ar.severity)}</Badge>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-text-primary">{fmt(ar.title ?? ar.alert_type ?? ar.type)}</div>
                <div className="text-xs text-text-muted mt-0.5">{fmt(ar.description ?? ar.detail)}</div>
                {Boolean(ar.node_id) && <div className="text-[10px] font-mono text-text-muted mt-1">Node: {String(ar.node_id)}</div>}
              </div>
              <span className="text-[10px] font-mono text-text-muted whitespace-nowrap">{fmt(ar.detected_at ?? ar.ts)}</span>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

// ── Page entry ─────────────────────────────────────────────────────────────────

type CisView = 'overview' | 'mutations' | 'drift';

export function CisPage() {
  const { nodeId } = useParams<{ nodeId?: string }>();
  const [view, setView] = useState<CisView>('overview');

  if (nodeId) {
    return (
      <div className="p-6 max-w-4xl">
        <CisForensicsPanel nodeId={nodeId} />
      </div>
    );
  }

  const tabs: { id: CisView; label: string }[] = [
    { id: 'overview', label: 'Health' },
    { id: 'mutations', label: 'Mutations' },
    { id: 'drift', label: 'Drift' },
  ];

  return (
    <div className="p-6 max-w-5xl space-y-4">
      <div>
        <h1 className="text-lg font-bold font-mono text-text-primary">Cognitive Integrity System</h1>
        <p className="text-xs text-text-muted mt-0.5">Graph mutation detection, drift monitoring, and forensic node analysis</p>
      </div>

      <TerminalSeparator />

      {/* Tab strip */}
      <div className="flex gap-2">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setView(t.id)}
            className={`font-mono text-xs px-3 py-1 rounded border transition-colors ${
              view === t.id
                ? 'bg-accent/20 text-accent border-accent/40'
                : 'text-text-muted border-border-default hover:text-text-secondary'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {view === 'overview' && <CisHealthPanel />}
      {view === 'mutations' && <CisMutationsPanel />}
      {view === 'drift' && <CisDriftPanel />}
    </div>
  );
}
