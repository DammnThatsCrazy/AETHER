import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { StatCard } from '../../components/ui/stat-card';
import { AetherBadge } from '../../components/ui/aether-badge';
import { SeverityChip } from '../../components/ui/severity-chip';
import { LiveIndicator, PulsingDot } from '../../components/ui/live-indicator';
import { EntityId } from '../../components/ui/entity-id';

// ── Mock data ────────────────────────────────────────────────────
type Severity = 'P0' | 'P1' | 'P2' | 'P3' | 'INFO';
type EventKind = 'alert' | 'cluster' | 'entity' | 'relationship' | 'governance' | 'journey' | 'system';

interface FeedEvent {
  id: string;
  ts: string;
  sev: Severity;
  kind: EventKind;
  summary: string;
  entityId?: string;
  entityType?: string;
  clusterRef?: string;
  tags: string[];
  confidence: number;
  acknowledged: boolean;
}

const MOCK_EVENTS: FeedEvent[] = [
  { id: 'e001', ts: '14:32:08', sev: 'P0', kind: 'cluster',      summary: 'Coordinated device ring detected — 47 entities, 3 IP subnets', entityId: 'clu_8x2k9f', entityType: 'cluster',    clusterRef: 'CL-28x', tags: ['fraud', 'device-ring', 'coordinated'], confidence: 94, acknowledged: false },
  { id: 'e002', ts: '14:31:45', sev: 'P1', kind: 'entity',       summary: 'Entity risk score crossed threshold (87 → 92): usr_9k2f', entityId: 'usr_9k2f', entityType: 'user', tags: ['risk-escalation', 'behavior'], confidence: 88, acknowledged: false },
  { id: 'e003', ts: '14:29:12', sev: 'P1', kind: 'alert',        summary: 'Graph mutation rate spike: 3.2× baseline over 5min window', entityId: 'sys_graph', entityType: 'system', tags: ['throughput', 'graph'], confidence: 100, acknowledged: false },
  { id: 'e004', ts: '14:28:54', sev: 'P2', kind: 'relationship', summary: 'New high-confidence relationship: usr_7b3m → 0x1a2b…3c4d (wallet bridge)', entityId: 'usr_7b3m', entityType: 'user', tags: ['web3', 'relationship', 'bridge'], confidence: 81, acknowledged: false },
  { id: 'e005', ts: '14:27:03', sev: 'P2', kind: 'journey',      summary: 'Journey anomaly: 14-step funnel compressed to 2 steps (usr_4f9p)', entityId: 'usr_4f9p', entityType: 'user', tags: ['journey', 'anomaly'], confidence: 76, acknowledged: true },
  { id: 'e006', ts: '14:25:41', sev: 'P2', kind: 'governance',   summary: 'Policy violation: PII accessed outside consent scope — 3 records', tags: ['governance', 'consent', 'pii'], confidence: 100, acknowledged: false },
  { id: 'e007', ts: '14:24:18', sev: 'P3', kind: 'entity',       summary: 'New entity resolved from 4 cross-channel signals: usr_2b8x', entityId: 'usr_2b8x', entityType: 'user', tags: ['resolution', 'identity'], confidence: 71, acknowledged: true },
  { id: 'e008', ts: '14:22:07', sev: 'P3', kind: 'cluster',      summary: 'Cluster CL-31f growing: added 12 entities in last 30min', clusterRef: 'CL-31f', tags: ['cluster', 'growth'], confidence: 68, acknowledged: true },
  { id: 'e009', ts: '14:21:55', sev: 'INFO', kind: 'system',     summary: 'Graph checkpoint completed: 2.4M nodes, 18.7M edges snapshotted', tags: ['system', 'checkpoint'], confidence: 100, acknowledged: true },
  { id: 'e010', ts: '14:20:33', sev: 'P1', kind: 'entity',       summary: 'Synthetic account signals detected: dev_fingerprint_shared × 8', entityId: 'dev_k3m9', entityType: 'device', tags: ['device', 'synthetic', 'fraud'], confidence: 85, acknowledged: false },
  { id: 'e011', ts: '14:19:12', sev: 'P2', kind: 'alert',        summary: 'Wallet cluster CW-04 — new bridge activity to Optimism: 3 wallets', tags: ['web3', 'bridge', 'cluster'], confidence: 79, acknowledged: false },
  { id: 'e012', ts: '14:17:44', sev: 'P3', kind: 'relationship', summary: 'Shared device evidence strengthened: 3 entities → same fingerprint', tags: ['device', 'relationship'], confidence: 63, acknowledged: true },
  { id: 'e013', ts: '14:16:20', sev: 'INFO', kind: 'governance', summary: 'Consent audit completed: 99.98% coverage across active entities', tags: ['governance', 'audit', 'consent'], confidence: 100, acknowledged: true },
  { id: 'e014', ts: '14:14:08', sev: 'P1', kind: 'alert',        summary: 'Agent agt_oracle breached tool call threshold: 847 calls/min', entityId: 'agt_oracle', entityType: 'agent', tags: ['agent', 'threshold', 'rate-limit'], confidence: 100, acknowledged: false },
  { id: 'e015', ts: '14:12:39', sev: 'P0', kind: 'cluster',      summary: 'Multi-account fraud pattern: 23 accounts, shared IP range, 72h window', tags: ['fraud', 'multi-account', 'coordinated'], confidence: 91, acknowledged: false },
];

const KIND_LABELS: Record<EventKind, string> = {
  alert: 'ALERT', cluster: 'CLUSTER', entity: 'ENTITY',
  relationship: 'REL', governance: 'GOV', journey: 'JOURNEY', system: 'SYSTEM',
};

const KIND_STYLES: Record<EventKind, string> = {
  alert:        'text-ember',
  cluster:      'text-solar',
  entity:       'text-steel',
  relationship: 'text-signal',
  governance:   'text-amber',
  journey:      'text-verdant',
  system:       'text-text-muted',
};

const FILTERS: Array<{ id: string; label: string }> = [
  { id: 'all',        label: 'All' },
  { id: 'P0',         label: 'P0' },
  { id: 'P1',         label: 'P1' },
  { id: 'fraud',      label: 'Fraud' },
  { id: 'governance', label: 'Governance' },
  { id: 'cluster',    label: 'Cluster' },
  { id: 'web3',       label: 'Web3' },
  { id: 'agent',      label: 'Agent' },
];

export function FeedPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('all');
  const [events, setEvents] = useState(MOCK_EVENTS);
  const [selected, setSelected] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [showAcknowledged, setShowAcknowledged] = useState(true);

  const acknowledge = useCallback((id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEvents(prev => prev.map(ev => ev.id === id ? { ...ev, acknowledged: true } : ev));
  }, []);

  const filtered = events.filter(ev => {
    if (!showAcknowledged && ev.acknowledged) return false;
    if (filter === 'all') return true;
    if (filter === 'P0' || filter === 'P1') return ev.sev === filter;
    return ev.kind === filter || ev.tags.includes(filter);
  });

  const unack = events.filter(e => !e.acknowledged).length;
  const p0Count = events.filter(e => e.sev === 'P0').length;

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="px-6 pt-5 pb-0 flex-shrink-0">
        <PageHeader
          eyebrow="Intelligence Surface"
          title="Feed"
          subtitle="Realtime operational intelligence stream"
          actions={
            <div className="flex items-center gap-2">
              <LiveIndicator />
              <button
                onClick={() => setPaused(v => !v)}
                className={cn(
                  'text-xs px-3 py-1.5 rounded border font-medium transition-colors',
                  paused
                    ? 'bg-amber/10 text-amber border-amber/25'
                    : 'border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover',
                )}
              >
                {paused ? '▶ Resume' : '⏸ Pause'}
              </button>
              <button
                onClick={() => navigate('/investigations/new')}
                className="text-xs px-3 py-1.5 rounded bg-signal text-stone-white font-medium hover:bg-signal/90 transition-colors"
              >
                + Investigation
              </button>
            </div>
          }
        />

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-3 mb-4">
          <StatCard label="Unacknowledged" value={unack} accent="warning" icon="△" mono />
          <StatCard label="P0 Active" value={p0Count} accent="danger" icon="●" mono />
          <StatCard label="Events / min" value="847" delta={{ value: '12%', positive: false }} mono />
          <StatCard label="Graph mutations / h" value="38.4k" delta={{ value: '3.2×', positive: false }} mono />
        </div>

        {/* Filter pills */}
        <div className="flex items-center gap-2 mb-3 border-b border-border-subtle pb-3">
          <div className="flex items-center gap-1 flex-1 flex-wrap">
            {FILTERS.map(f => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={cn(
                  'px-3 py-1 rounded-pill border font-mono text-2xs font-medium tracking-wide transition-colors',
                  filter === f.id
                    ? 'bg-signal/10 text-steel border-signal/30'
                    : 'border-border-default text-text-muted hover:text-text-primary hover:border-border-hover',
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-xs text-text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={showAcknowledged}
              onChange={e => setShowAcknowledged(e.target.checked)}
              className="w-3 h-3"
            />
            Show acknowledged
          </label>
          <span className="font-mono text-xs text-text-muted">{filtered.length} events</span>
        </div>
      </div>

      {/* Stream */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {/* Column headers */}
        <div className="grid grid-cols-[56px_56px_80px_1fr_120px_80px_100px] gap-3 py-2 px-2 mb-1 sticky top-0 bg-surface-base z-raised border-b border-border-subtle">
          {['TIME', 'SEV', 'KIND', 'SUMMARY', 'ENTITY', 'CONF', 'ACTION'].map(h => (
            <span key={h} className="label-eyebrow">{h}</span>
          ))}
        </div>

        <div className="divide-y divide-border-subtle">
          {filtered.map(ev => (
            <FeedEventRow
              key={ev.id}
              event={ev}
              selected={selected === ev.id}
              onSelect={() => setSelected(ev.id === selected ? null : ev.id)}
              onAck={acknowledge}
              onInvestigate={() => navigate(`/investigations/new?entity=${ev.entityId ?? ''}`)}
            />
          ))}
        </div>

        {filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-text-muted">
            <span className="font-mono text-3xl mb-3">◎</span>
            <p className="text-sm">No events match current filters</p>
          </div>
        )}
      </div>
    </div>
  );
}

function FeedEventRow({
  event: ev,
  selected,
  onSelect,
  onAck,
  onInvestigate,
}: {
  event: FeedEvent;
  selected: boolean;
  onSelect: () => void;
  onAck: (id: string, e: React.MouseEvent) => void;
  onInvestigate: () => void;
}) {
  const navigate = useNavigate();
  return (
    <div
      onClick={onSelect}
      className={cn(
        'grid grid-cols-[56px_56px_80px_1fr_120px_80px_100px] gap-3 py-2.5 px-2 cursor-pointer transition-colors',
        'hover:bg-surface-overlay',
        selected && 'bg-signal/5',
        ev.sev === 'P0' && !ev.acknowledged && 'bg-ember/3',
        ev.sev === 'P1' && !ev.acknowledged && 'bg-amber/3',
        ev.acknowledged && 'opacity-50',
      )}
    >
      {/* Time */}
      <span className="font-mono text-xs text-text-muted self-center">{ev.ts}</span>

      {/* Severity */}
      <div className="self-center">
        <SeverityChip severity={ev.sev} />
      </div>

      {/* Kind */}
      <span className={cn('font-mono text-2xs font-medium tracking-wide uppercase self-center', KIND_STYLES[ev.kind])}>
        {KIND_LABELS[ev.kind]}
      </span>

      {/* Summary */}
      <div className="self-center min-w-0">
        <p className="text-sm text-text-primary truncate">{ev.summary}</p>
        <div className="flex items-center gap-1 mt-0.5">
          {ev.tags.slice(0, 3).map(t => (
            <span key={t} className="font-mono text-2xs text-text-muted bg-surface-overlay px-1.5 py-px rounded">{t}</span>
          ))}
        </div>
      </div>

      {/* Entity */}
      <div className="self-center">
        {ev.entityId ? (
          <EntityId
            id={ev.entityId}
            type={ev.entityType as any}
            onClick={() => navigate(`/entities/${ev.entityId}`)}
          />
        ) : (
          <span className="text-2xs text-text-muted">—</span>
        )}
      </div>

      {/* Confidence */}
      <div className="self-center">
        <div className="flex items-center gap-1.5">
          <div className="trust-track">
            <div
              className={cn('trust-fill', ev.confidence > 80 ? 'bg-verdant' : ev.confidence > 60 ? 'bg-amber' : 'bg-ember')}
              style={{ width: `${ev.confidence}%` }}
            />
          </div>
          <span className="font-mono text-2xs text-text-muted w-6 text-right">{ev.confidence}</span>
        </div>
      </div>

      {/* Actions */}
      <div className="self-center flex items-center gap-1">
        {!ev.acknowledged && (
          <button
            onClick={e => onAck(ev.id, e)}
            className="text-2xs px-2 py-1 rounded border border-border-default text-text-muted hover:text-text-primary hover:border-border-hover transition-colors font-medium"
          >
            Ack
          </button>
        )}
        <button
          onClick={e => { e.stopPropagation(); onInvestigate(); }}
          className="text-2xs px-2 py-1 rounded border border-signal/30 text-steel hover:bg-signal/10 transition-colors font-medium"
        >
          Inv
        </button>
      </div>
    </div>
  );
}
