import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { StatCard } from '../../components/ui/stat-card';
import { AetherBadge } from '../../components/ui/aether-badge';

const POLICY_METRICS = [
  { label: 'Consent coverage', value: '99.98%', accent: 'success' as const, sub: '+0.02% vs last week' },
  { label: 'Policy violations', value: '3', accent: 'danger' as const,  sub: 'Active violations' },
  { label: 'Access reviews due', value: '12', accent: 'warning' as const, sub: 'Quarterly cycle' },
  { label: 'Audit completeness', value: '100%', accent: 'success' as const, sub: 'All events traced' },
];

const VIOLATIONS = [
  { id: 'vio-001', policy: 'P-CONSENT-002', desc: 'PII accessed outside consent scope', severity: 'P1', status: 'open', ts: '14:06', entity: 'usr_9k2f' },
  { id: 'vio-002', policy: 'P-RETENTION-001', desc: 'Data retained beyond 90-day window', severity: 'P2', status: 'in-review', ts: '12:34', entity: 'session batch' },
  { id: 'vio-003', policy: 'P-ACCESS-003', desc: 'Analyst accessed escalated entity without ticket', severity: 'P2', status: 'in-review', ts: '09:18', entity: 'analyst_03' },
];

const POLICIES = [
  { id: 'P-FRAUD-001',   name: 'Fraud Detection', status: 'active', coverage: '100%', entities: 2847, lastModified: '2025-04-12' },
  { id: 'P-CONSENT-002', name: 'Consent Scope',   status: 'active', coverage: '99.98%', entities: 14231, lastModified: '2025-03-28' },
  { id: 'P-RETENTION-001', name: 'Data Retention', status: 'active', coverage: '100%', entities: 14231, lastModified: '2025-02-14' },
  { id: 'P-ACCESS-003',  name: 'Analyst Access',  status: 'active', coverage: '100%', entities: 0, lastModified: '2025-01-20' },
  { id: 'P-EXPORT-001',  name: 'Export Controls', status: 'active', coverage: '100%', entities: 0, lastModified: '2025-01-08' },
];

type Tab = 'overview' | 'policies' | 'consent' | 'access' | 'explainability' | 'audit';

export function GovernancePage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>('overview');

  const TABS: Array<{ id: Tab; label: string }> = [
    { id: 'overview',        label: 'Overview' },
    { id: 'policies',        label: 'Policies' },
    { id: 'consent',         label: 'Consent' },
    { id: 'access',          label: 'Access' },
    { id: 'explainability',  label: 'Explainability' },
    { id: 'audit',           label: 'Audit' },
  ];

  return (
    <div className="px-6 py-5">
      <PageHeader
        eyebrow="Governance"
        title="Governance Center"
        subtitle="Policy management, consent, access control, and audit"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate('/audit')}
              className="text-xs px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors"
            >
              ✓ Audit Center
            </button>
            <button className="text-xs px-3 py-1.5 rounded bg-signal text-stone-white font-medium hover:bg-signal/90 transition-colors">
              + New policy
            </button>
          </div>
        }
      />

      {/* Metrics */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        {POLICY_METRICS.map(m => (
          <StatCard key={m.label} label={m.label} value={m.value} accent={m.accent} sub={m.sub} mono={false} />
        ))}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-0 border-b border-border-default mb-4">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === tab.id
                ? 'border-b-signal text-steel'
                : 'border-b-transparent text-text-muted hover:text-text-primary',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && <GovernanceOverview />}
      {activeTab === 'policies' && <PoliciesTab />}
      {activeTab === 'explainability' && <ExplainabilityTab />}
      {activeTab === 'audit' && <AuditTab navigate={navigate} />}
      {!['overview', 'policies', 'explainability', 'audit'].includes(activeTab) && (
        <ComingSoonTab tab={activeTab} />
      )}
    </div>
  );
}

function GovernanceOverview() {
  return (
    <div className="grid grid-cols-3 gap-4">
      {/* Active violations */}
      <div className="col-span-2 panel overflow-hidden">
        <div className="panel-header">
          <span className="panel-title">Active Violations ({VIOLATIONS.length})</span>
        </div>
        <div className="divide-y divide-border-subtle">
          {VIOLATIONS.map(v => (
            <div key={v.id} className={cn('px-4 py-3 border-l-2', v.severity === 'P1' ? 'sev-p1' : 'sev-p2')}>
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono text-2xs text-text-muted">{v.policy}</span>
                    <AetherBadge variant={v.status === 'open' ? 'danger' : 'warning'}>{v.status}</AetherBadge>
                  </div>
                  <p className="text-sm text-text-primary">{v.desc}</p>
                  <p className="text-xs text-text-muted mt-0.5">Entity: <span className="font-mono text-text-secondary">{v.entity}</span> · {v.ts}</p>
                </div>
                <button className="text-xs px-2 py-1 rounded border border-border-default text-text-muted hover:text-text-primary transition-colors">
                  Review
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Quick stats */}
      <div className="space-y-3">
        <div className="panel p-4">
          <p className="label-eyebrow mb-3">Deployment health</p>
          <div className="space-y-2">
            {[
              { label: 'Tenant isolation', ok: true },
              { label: 'Encryption at rest', ok: true },
              { label: 'Audit logging', ok: true },
              { label: 'Access reviews', ok: false },
              { label: 'Consent sync', ok: true },
            ].map(item => (
              <div key={item.label} className="flex items-center justify-between">
                <span className="text-xs text-text-secondary">{item.label}</span>
                <span className={item.ok ? 'text-verdant font-mono text-xs' : 'text-ember font-mono text-xs'}>
                  {item.ok ? '✓ pass' : '✗ due'}
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="panel p-4">
          <p className="label-eyebrow mb-2">Recent governance events</p>
          <div className="space-y-2">
            {[
              { event: 'Consent audit completed', ts: '13:00' },
              { event: 'Policy P-FRAUD-001 reviewed', ts: '11:30' },
              { event: 'Access review cycle started', ts: '09:00' },
            ].map((e, i) => (
              <div key={i} className="text-xs">
                <span className="font-mono text-text-muted">{e.ts}</span>
                <span className="text-text-secondary ml-2">{e.event}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function PoliciesTab() {
  return (
    <div className="panel overflow-hidden">
      <div className="panel-header">
        <span className="panel-title">Policies ({POLICIES.length})</span>
      </div>
      <div className="grid grid-cols-[120px_1fr_80px_80px_100px_100px] gap-3 px-4 py-2 border-b border-border-subtle bg-surface-sidebar">
        {['ID', 'NAME', 'STATUS', 'COVERAGE', 'ENTITIES', 'MODIFIED'].map(h => (
          <span key={h} className="label-eyebrow">{h}</span>
        ))}
      </div>
      <div className="divide-y divide-border-subtle">
        {POLICIES.map(p => (
          <div key={p.id} className="grid grid-cols-[120px_1fr_80px_80px_100px_100px] gap-3 px-4 py-3 hover:bg-surface-overlay cursor-pointer transition-colors">
            <span className="font-mono text-xs text-text-muted">{p.id}</span>
            <span className="text-sm text-text-primary">{p.name}</span>
            <AetherBadge variant="success">{p.status}</AetherBadge>
            <span className="font-mono text-xs text-verdant">{p.coverage}</span>
            <span className="font-mono text-xs text-text-secondary">{p.entities.toLocaleString()}</span>
            <span className="font-mono text-xs text-text-muted">{p.lastModified}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ExplainabilityTab() {
  const signals = [
    { factor: 'Shared device fingerprint', weight: 35, confidence: 91, type: 'device' },
    { factor: 'Cluster membership (CL-28x)', weight: 28, confidence: 94, type: 'cluster' },
    { factor: 'Session timing correlation', weight: 18, confidence: 88, type: 'journey' },
    { factor: 'IP subnet overlap', weight: 12, confidence: 83, type: 'geo' },
    { factor: 'Wallet bridge activity', weight: 7, confidence: 79, type: 'web3' },
  ];

  return (
    <div className="space-y-4 max-w-2xl">
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Risk Score Explainability — usr_9k2f (92)</span>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-xs text-text-secondary">
            The risk score of 92 is derived from 5 independent signals. Each signal is weighted by confidence and evidential strength.
          </p>
          <div className="space-y-2">
            {signals.map(s => (
              <div key={s.factor}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <AetherBadge variant="default" mono>{s.type}</AetherBadge>
                    <span className="text-sm text-text-primary">{s.factor}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-text-muted">{s.confidence}%</span>
                    <span className="font-mono text-xs text-text-primary font-medium">{s.weight}%</span>
                  </div>
                </div>
                <div className="trust-track h-1.5">
                  <div className="trust-fill bg-signal" style={{ width: `${s.weight * 2.86}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function AuditTab({ navigate }: { navigate: ReturnType<typeof useNavigate> }) {
  const entries = [
    { ts: '14:31', actor: 'system',     action: 'risk_score_updated',   entity: 'usr_9k2f',   detail: '87 → 92' },
    { ts: '14:20', actor: 'analyst_01', action: 'entity_viewed',        entity: 'usr_9k2f',   detail: 'investigation' },
    { ts: '14:06', actor: 'system',     action: 'policy_violation',     entity: 'usr_9k2f',   detail: 'P-CONSENT-002' },
    { ts: '13:52', actor: 'system',     action: 'relationship_created', entity: 'wal_1a2b',   detail: 'bridge_transfer' },
    { ts: '13:00', actor: 'system',     action: 'consent_audit',        entity: 'all-entities',detail: '99.98% coverage' },
  ];

  return (
    <div className="panel overflow-hidden max-w-4xl">
      <div className="panel-header">
        <span className="panel-title">Audit log</span>
        <div className="flex items-center gap-2">
          <button className="text-xs text-text-muted hover:text-text-primary transition-colors" onClick={() => navigate('/audit')}>
            Full audit center →
          </button>
          <button className="text-xs px-2 py-1 rounded border border-border-default text-text-muted hover:text-text-primary transition-colors">
            Export
          </button>
        </div>
      </div>
      <div className="divide-y divide-border-subtle">
        {entries.map((e, i) => (
          <div key={i} className="grid grid-cols-[60px_120px_200px_140px_1fr] gap-3 px-4 py-3">
            <span className="font-mono text-2xs text-text-muted">{e.ts}</span>
            <span className="font-mono text-2xs text-text-secondary">{e.actor}</span>
            <code>{e.action}</code>
            <span className="font-mono text-2xs text-text-accent">{e.entity}</span>
            <span className="text-xs text-text-secondary">{e.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ComingSoonTab({ tab }: { tab: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-text-muted">
      <span className="font-mono text-3xl mb-3">◎</span>
      <p className="text-sm capitalize">{tab} governance</p>
    </div>
  );
}
