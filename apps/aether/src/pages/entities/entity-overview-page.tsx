import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { AetherBadge } from '../../components/ui/aether-badge';
import { SeverityChip } from '../../components/ui/severity-chip';
import { StatCard } from '../../components/ui/stat-card';
import { EntityId } from '../../components/ui/entity-id';

// ── Mock entity data ─────────────────────────────────────────────
const ENTITY = {
  id: 'usr_9k2f',
  displayName: 'usr_9k2f',
  type: 'user',
  createdAt: '2024-11-03T08:14:22Z',
  lastSeenAt: '2025-05-18T14:31:45Z',
  riskScore: 92,
  trustScore: 31,
  confidenceScore: 88,
  status: 'escalated' as const,
  attributes: {
    email:    'redacted@…',
    country:  'US',
    platform: 'web',
    segment:  'high-value',
  },
  signals: [
    { id: 's1', label: 'Shared device with 3 other entities', sev: 'P1', confidence: 85, source: 'device' },
    { id: 's2', label: 'Bridge transfer to unknown wallet', sev: 'P1', confidence: 79, source: 'web3' },
    { id: 's3', label: 'Journey anomaly: 14-step funnel in <2s', sev: 'P2', confidence: 76, source: 'journey' },
    { id: 's4', label: 'Multiple sessions from 4 different IPs, 1h window', sev: 'P2', confidence: 71, source: 'session' },
    { id: 's5', label: 'Cluster membership: CL-28x (coordinated fraud ring)', sev: 'P0', confidence: 91, source: 'cluster' },
  ],
  relationships: [
    { entityId: 'dev_k3m9', entityType: 'device', relType: 'uses_device',    confidence: 95, firstSeen: '2024-11-10' },
    { entityId: 'wal_1a2b', entityType: 'wallet', relType: 'owns_wallet',    confidence: 88, firstSeen: '2024-12-04' },
    { entityId: 'usr_7b3m', entityType: 'user',   relType: 'shares_device',  confidence: 82, firstSeen: '2025-01-17' },
    { entityId: 'clu_28x',  entityType: 'cluster',relType: 'member_of',      confidence: 91, firstSeen: '2025-03-02' },
    { entityId: 'ip_192',   entityType: 'ip',     relType: 'originates_from',confidence: 89, firstSeen: '2025-04-14' },
  ],
  timeline: [
    { ts: '14:31:45', event: 'Risk score escalated to 92', kind: 'risk',       sev: 'P1' },
    { ts: '14:18:22', event: 'New relationship: shared device dev_k3m9', kind: 'relationship', sev: 'P1' },
    { ts: '13:52:07', event: 'Bridge transfer: 0x1a2b → Optimism', kind: 'web3', sev: 'P2' },
    { ts: '12:44:31', event: 'Journey anomaly detected', kind: 'journey', sev: 'P2' },
    { ts: '11:30:12', event: 'Added to cluster CL-28x', kind: 'cluster', sev: 'P0' },
    { ts: '09:15:44', event: 'Session from new IP range', kind: 'session', sev: 'P3' },
    { ts: '08:14:22', event: 'Entity created via SDK', kind: 'system', sev: 'INFO' },
  ],
};

type Tab = 'overview' | 'relationships' | 'timeline' | 'journey' | 'devices' | 'wallets' | 'sessions' | 'evidence' | 'governance' | 'audit';

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'overview',      label: 'Overview' },
  { id: 'relationships', label: 'Relationships' },
  { id: 'timeline',      label: 'Timeline' },
  { id: 'journey',       label: 'Journey' },
  { id: 'devices',       label: 'Devices' },
  { id: 'wallets',       label: 'Wallets' },
  { id: 'sessions',      label: 'Sessions' },
  { id: 'evidence',      label: 'Evidence' },
  { id: 'governance',    label: 'Governance' },
  { id: 'audit',         label: 'Audit' },
];

const SEV_STYLE: Record<string, string> = {
  P0: 'sev-p0', P1: 'sev-p1', P2: 'sev-p2', P3: 'sev-p3',
};

export function EntityOverviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>('overview');
  const entity = ENTITY; // in prod: fetch by id

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 pt-5 pb-0 flex-shrink-0">
        <PageHeader
          eyebrow={`${entity.type} · entity`}
          title={entity.displayName}
          actions={
            <div className="flex items-center gap-2">
              <AetherBadge
                variant={entity.riskScore > 75 ? 'danger' : entity.riskScore > 50 ? 'warning' : 'success'}
              >
                Risk {entity.riskScore}
              </AetherBadge>
              <AetherBadge variant="warning">Escalated</AetherBadge>
              <button
                onClick={() => navigate('/graph?focus=' + entity.id)}
                className="text-xs px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors"
              >
                ⬡ Graph
              </button>
              <button
                onClick={() => navigate('/investigations/new?entity=' + entity.id)}
                className="text-xs px-3 py-1.5 rounded bg-signal text-stone-white font-medium hover:bg-signal/90 transition-colors"
              >
                + Investigation
              </button>
            </div>
          }
        />

        {/* Score row */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          <StatCard label="Risk Score"  value={entity.riskScore}  accent="danger"  mono sub="Escalated — P1 threshold" />
          <StatCard label="Trust Score" value={entity.trustScore}  accent="warning" mono sub="Below baseline (40)" />
          <StatCard label="Confidence"  value={`${entity.confidenceScore}%`} accent="default" mono sub="High confidence resolution" />
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-0 border-b border-border-default overflow-x-auto">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors',
                activeTab === tab.id
                  ? 'border-b-signal text-steel'
                  : 'border-b-transparent text-text-muted hover:text-text-primary',
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {activeTab === 'overview' && <OverviewTab entity={entity} />}
        {activeTab === 'relationships' && <RelationshipsTab entity={entity} />}
        {activeTab === 'timeline' && <TimelineTab entity={entity} />}
        {activeTab === 'evidence' && <EvidenceTab entity={entity} />}
        {activeTab === 'governance' && <GovernanceTab entity={entity} />}
        {activeTab === 'audit' && <AuditTab entity={entity} />}
        {!['overview','relationships','timeline','evidence','governance','audit'].includes(activeTab) && (
          <PlaceholderTab tab={activeTab} entityId={entity.id} />
        )}
      </div>
    </div>
  );
}

// ── Tab implementations ──────────────────────────────────────────

function OverviewTab({ entity }: { entity: typeof ENTITY }) {
  return (
    <div className="grid grid-cols-3 gap-4">
      {/* Signals */}
      <div className="col-span-2 space-y-3">
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Intelligence Signals ({entity.signals.length})</span>
          </div>
          <div className="divide-y divide-border-subtle">
            {entity.signals.map(sig => (
              <div key={sig.id} className={cn('flex items-start gap-3 px-4 py-3 border-l-2', SEV_STYLE[sig.sev])}>
                <SeverityChip severity={sig.sev as any} />
                <div className="flex-1">
                  <p className="text-sm text-text-primary">{sig.label}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <AetherBadge variant="default" mono>{sig.source}</AetherBadge>
                    <span className="font-mono text-2xs text-text-muted">{sig.confidence}% confidence</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Metadata */}
      <div className="space-y-3">
        <div className="panel">
          <div className="panel-header"><span className="panel-title">Attributes</span></div>
          <div className="divide-y divide-border-subtle">
            {Object.entries(entity.attributes).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between px-4 py-2.5">
                <span className="text-xs text-text-secondary">{k}</span>
                <span className="font-mono text-xs text-text-primary">{v}</span>
              </div>
            ))}
            <div className="flex items-center justify-between px-4 py-2.5">
              <span className="text-xs text-text-secondary">First seen</span>
              <span className="font-mono text-xs text-text-primary">2024-11-03</span>
            </div>
            <div className="flex items-center justify-between px-4 py-2.5">
              <span className="text-xs text-text-secondary">Last seen</span>
              <span className="font-mono text-xs text-text-primary">2025-05-18</span>
            </div>
          </div>
        </div>

        <div className="panel p-4 space-y-2">
          <p className="label-eyebrow mb-2">Quick links</p>
          {[
            { label: '⬡ View in graph', href: `/graph?focus=${entity.id}` },
            { label: '↝ Journey replay', href: `/journeys?entity=${entity.id}` },
            { label: '⊡ Device history', href: `/devices?entity=${entity.id}` },
            { label: '⟐ Wallet links', href: `/wallets?entity=${entity.id}` },
            { label: '◈ Cluster membership', href: `/clusters?entity=${entity.id}` },
          ].map(l => (
            <a key={l.href} href={l.href} className="block text-xs text-text-secondary hover:text-steel transition-colors py-1">
              {l.label}
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}

function RelationshipsTab({ entity }: { entity: typeof ENTITY }) {
  const navigate = useNavigate();
  return (
    <div className="panel overflow-hidden">
      <div className="panel-header">
        <span className="panel-title">Relationships ({entity.relationships.length})</span>
        <button className="text-xs text-text-muted hover:text-text-primary transition-colors" onClick={() => navigate('/graph?focus=' + entity.id)}>
          Open in graph →
        </button>
      </div>
      {/* Header row */}
      <div className="grid grid-cols-[120px_100px_200px_120px_100px] gap-3 px-4 py-2 border-b border-border-subtle">
        {['ENTITY', 'TYPE', 'RELATIONSHIP', 'CONFIDENCE', 'FIRST SEEN'].map(h => (
          <span key={h} className="label-eyebrow">{h}</span>
        ))}
      </div>
      <div className="divide-y divide-border-subtle">
        {entity.relationships.map(rel => (
          <div key={rel.entityId} className="grid grid-cols-[120px_100px_200px_120px_100px] gap-3 px-4 py-3 hover:bg-surface-overlay transition-colors cursor-pointer"
            onClick={() => navigate(`/entities/${rel.entityId}`)}>
            <EntityId id={rel.entityId} type={rel.entityType as any} />
            <AetherBadge variant="default" mono>{rel.entityType}</AetherBadge>
            <span className="text-xs text-text-secondary">{rel.relType.replace(/_/g, ' ')}</span>
            <div className="trust-bar">
              <div className="trust-track"><div className="trust-fill bg-steel" style={{ width: `${rel.confidence}%` }} /></div>
              <span className="font-mono text-2xs text-text-muted w-6">{rel.confidence}</span>
            </div>
            <span className="font-mono text-xs text-text-muted">{rel.firstSeen}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TimelineTab({ entity }: { entity: typeof ENTITY }) {
  return (
    <div className="space-y-1 max-w-2xl">
      {entity.timeline.map((ev, idx) => (
        <div key={idx} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className={cn('w-2 h-2 rounded-pill mt-1.5 flex-shrink-0',
              ev.sev === 'P0' ? 'bg-ember' : ev.sev === 'P1' ? 'bg-amber' : ev.sev === 'P2' ? 'bg-signal' : 'bg-text-muted'
            )} />
            {idx < entity.timeline.length - 1 && <div className="w-px flex-1 bg-border-subtle mt-1" />}
          </div>
          <div className="pb-4 flex-1">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="font-mono text-2xs text-text-muted">{ev.ts}</span>
              <SeverityChip severity={ev.sev as any} />
              <AetherBadge variant="default" mono>{ev.kind}</AetherBadge>
            </div>
            <p className="text-sm text-text-primary">{ev.event}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function EvidenceTab({ entity }: { entity: typeof ENTITY }) {
  return (
    <div className="space-y-3 max-w-2xl">
      <p className="label-eyebrow">Evidence ({entity.signals.length} signals)</p>
      {entity.signals.map(sig => (
        <div key={sig.id} className={cn('evidence-item', SEV_STYLE[sig.sev])}>
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm text-text-primary">{sig.label}</p>
            <SeverityChip severity={sig.sev as any} />
          </div>
          <div className="flex items-center gap-3 mt-1.5">
            <AetherBadge variant="default" mono>{sig.source}</AetherBadge>
            <span className="font-mono text-2xs text-text-muted">{sig.confidence}% confidence</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function GovernanceTab({ entity }: { entity: typeof ENTITY }) {
  return (
    <div className="grid grid-cols-2 gap-4 max-w-2xl">
      {[
        { label: 'Consent Status',    value: 'Active',            ok: true },
        { label: 'Data Retention',    value: '180 days',          ok: true },
        { label: 'PII Scope',         value: 'Redacted',          ok: true },
        { label: 'Access Tier',       value: 'Analyst',           ok: true },
        { label: 'Explainability',    value: '3 signals traced',  ok: true },
        { label: 'Policy Compliance', value: 'P-FRAUD-001 active',ok: true },
      ].map(item => (
        <div key={item.label} className="panel p-4 flex items-center justify-between">
          <span className="text-sm text-text-secondary">{item.label}</span>
          <div className="flex items-center gap-2">
            <span className="text-sm text-text-primary font-mono">{item.value}</span>
            <span className={item.ok ? 'text-verdant font-mono text-xs' : 'text-ember font-mono text-xs'}>
              {item.ok ? '✓' : '✗'}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function AuditTab({ entity }: { entity: typeof ENTITY }) {
  const entries = [
    { ts: '14:31:45', actor: 'system',     action: 'risk_score_updated',   detail: `92 (was 87)` },
    { ts: '14:28:22', actor: 'analyst_01', action: 'entity_viewed',        detail: 'entity overview' },
    { ts: '13:52:07', actor: 'system',     action: 'relationship_created', detail: `wal_1a2b bridge_transfer` },
    { ts: '11:30:12', actor: 'system',     action: 'cluster_membership',   detail: 'CL-28x' },
    { ts: '09:15:44', actor: 'system',     action: 'signal_generated',     detail: 'session IP anomaly' },
  ];

  return (
    <div className="panel overflow-hidden max-w-3xl">
      <div className="panel-header">
        <span className="panel-title">Audit Trail</span>
        <button className="text-xs text-text-muted hover:text-text-primary transition-colors">Export</button>
      </div>
      <div className="divide-y divide-border-subtle">
        {entries.map((e, i) => (
          <div key={i} className="grid grid-cols-[80px_120px_200px_1fr] gap-3 px-4 py-3">
            <span className="font-mono text-2xs text-text-muted">{e.ts}</span>
            <span className="font-mono text-2xs text-text-secondary">{e.actor}</span>
            <code>{e.action}</code>
            <span className="text-xs text-text-secondary">{e.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PlaceholderTab({ tab, entityId }: { tab: Tab; entityId: string }) {
  const labels: Record<Tab, string> = {
    overview: '', relationships: '', timeline: '', evidence: '', governance: '', audit: '',
    journey: 'Journey Intelligence', devices: 'Device History', wallets: 'Wallet Links', sessions: 'Session History',
  };
  return (
    <div className="flex flex-col items-center justify-center py-20 text-text-muted">
      <span className="font-mono text-3xl mb-3">◎</span>
      <p className="text-sm mb-1">{labels[tab]}</p>
      <p className="text-xs text-text-muted">Entity: <code>{entityId}</code></p>
    </div>
  );
}
