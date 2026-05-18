import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { StatCard } from '../../components/ui/stat-card';
import { SeverityChip } from '../../components/ui/severity-chip';
import { AetherBadge } from '../../components/ui/aether-badge';
import { LiveIndicator } from '../../components/ui/live-indicator';

interface Alert {
  id: string;
  name: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3' | 'INFO';
  status: 'firing' | 'resolved' | 'suppressed' | 'pending';
  category: string;
  triggered: string;
  count: number;
  assignee?: string;
  entityRef?: string;
}

const ALERTS: Alert[] = [
  { id: 'ALT-0091', name: 'Cluster CL-28x: Coordinated device activity threshold exceeded', priority: 'P0', status: 'firing', category: 'fraud',      triggered: '2m ago',  count: 1,  assignee: 'analyst_01' },
  { id: 'ALT-0090', name: 'Entity usr_9k2f: Risk score > 90 threshold', priority: 'P1', status: 'firing',  category: 'risk',       triggered: '14m ago', count: 1,  assignee: 'analyst_01', entityRef: 'usr_9k2f' },
  { id: 'ALT-0089', name: 'Graph mutation rate spike: 3.2× baseline', priority: 'P1', status: 'firing',  category: 'system',     triggered: '32m ago', count: 3 },
  { id: 'ALT-0088', name: 'Agent agt_oracle: Tool call rate > 800/min', priority: 'P1', status: 'firing',  category: 'agent',      triggered: '40m ago', count: 1,  entityRef: 'agt_oracle' },
  { id: 'ALT-0087', name: 'Policy violation: PII access out of scope', priority: 'P1', status: 'pending', category: 'governance', triggered: '1h ago',  count: 1 },
  { id: 'ALT-0086', name: 'Wallet bridge anomaly: 3 wallets → Optimism', priority: 'P2', status: 'firing',  category: 'web3',       triggered: '1h ago',  count: 3 },
  { id: 'ALT-0085', name: 'WebSocket throughput degraded: p99 > 800ms', priority: 'P2', status: 'resolved',category: 'system',     triggered: '2h ago',  count: 7 },
  { id: 'ALT-0084', name: 'New cluster growth: CL-31f +12 entities', priority: 'P3', status: 'firing',  category: 'cluster',    triggered: '2h ago',  count: 1 },
];

const RULES = [
  { id: 'R-001', name: 'High risk entity',         condition: 'risk_score > 85', priority: 'P1', enabled: true,  triggered: 47 },
  { id: 'R-002', name: 'Coordinated cluster',       condition: 'cluster.size > 10 AND cluster.risk > 80', priority: 'P0', enabled: true,  triggered: 12 },
  { id: 'R-003', name: 'Graph mutation spike',      condition: 'mutation_rate > 2x_baseline', priority: 'P1', enabled: true,  triggered: 3 },
  { id: 'R-004', name: 'Policy violation',          condition: 'policy.violated = true', priority: 'P1', enabled: true,  triggered: 2 },
  { id: 'R-005', name: 'Wallet bridge anomaly',     condition: 'wallet.bridge AND created_at < 24h', priority: 'P2', enabled: true,  triggered: 8 },
  { id: 'R-006', name: 'Agent rate exceeded',       condition: 'agent.tool_calls > 800/min', priority: 'P1', enabled: true,  triggered: 1 },
  { id: 'R-007', name: 'Journey time anomaly',      condition: 'journey.duration < p1_baseline * 0.1', priority: 'P2', enabled: false, triggered: 24 },
];

type View = 'active' | 'rules' | 'history';

export function AlertsPage() {
  const navigate = useNavigate();
  const [view, setView] = useState<View>('active');
  const [category, setCategory] = useState('all');

  const firing   = ALERTS.filter(a => a.status === 'firing').length;
  const pending  = ALERTS.filter(a => a.status === 'pending').length;
  const resolved = ALERTS.filter(a => a.status === 'resolved').length;
  const categories = ['all', 'fraud', 'risk', 'system', 'governance', 'web3', 'agent', 'cluster'];

  const filtered = ALERTS.filter(a => category === 'all' || a.category === category);

  return (
    <div className="px-6 py-5">
      <PageHeader
        eyebrow="Operations"
        title="Alert Center"
        subtitle="Operational alerts and monitoring rules"
        actions={
          <div className="flex items-center gap-2">
            <LiveIndicator />
            <button
              onClick={() => navigate('/monitoring')}
              className="text-xs px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors"
            >
              ⊙ Monitoring
            </button>
            <button className="text-xs px-3 py-1.5 rounded bg-signal text-stone-white font-medium hover:bg-signal/90 transition-colors">
              + Alert rule
            </button>
          </div>
        }
      />

      <div className="grid grid-cols-4 gap-3 mb-5">
        <StatCard label="Firing"   value={firing}   accent="danger"  icon="●" mono />
        <StatCard label="Pending"  value={pending}   accent="warning" icon="○" mono />
        <StatCard label="Resolved" value={resolved}  accent="success" icon="✓" mono sub="Last 24h" />
        <StatCard label="Rules"    value={RULES.length} mono />
      </div>

      {/* View tabs */}
      <div className="flex items-center gap-0 border-b border-border-default mb-4">
        {(['active', 'rules', 'history'] as View[]).map(v => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={cn(
              'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors capitalize',
              view === v
                ? 'border-b-signal text-steel'
                : 'border-b-transparent text-text-muted hover:text-text-primary',
            )}
          >
            {v}
          </button>
        ))}
      </div>

      {view === 'active' && (
        <>
          <div className="flex items-center gap-1 mb-4">
            {categories.map(c => (
              <button
                key={c}
                onClick={() => setCategory(c)}
                className={cn(
                  'px-3 py-1 rounded-pill border font-mono text-2xs font-medium transition-colors',
                  category === c
                    ? 'bg-signal/10 text-steel border-signal/30'
                    : 'border-border-default text-text-muted hover:text-text-primary',
                )}
              >
                {c}
              </button>
            ))}
            <span className="font-mono text-xs text-text-muted ml-auto">{filtered.length} alerts</span>
          </div>
          <div className="space-y-2">
            {filtered.map(alert => (
              <AlertRow key={alert.id} alert={alert} />
            ))}
          </div>
        </>
      )}

      {view === 'rules' && (
        <div className="panel overflow-hidden">
          <div className="panel-header">
            <span className="panel-title">Alert rules ({RULES.length})</span>
          </div>
          <div className="grid grid-cols-[80px_1fr_1fr_80px_80px_80px] gap-3 px-4 py-2 border-b border-border-subtle bg-surface-sidebar">
            {['ID', 'NAME', 'CONDITION', 'PRIORITY', 'ENABLED', 'FIRED'].map(h => (
              <span key={h} className="label-eyebrow">{h}</span>
            ))}
          </div>
          <div className="divide-y divide-border-subtle">
            {RULES.map(r => (
              <div key={r.id} className="grid grid-cols-[80px_1fr_1fr_80px_80px_80px] gap-3 px-4 py-3 hover:bg-surface-overlay transition-colors cursor-pointer">
                <span className="font-mono text-xs text-text-muted">{r.id}</span>
                <span className="text-sm text-text-primary">{r.name}</span>
                <code className="text-2xs">{r.condition}</code>
                <SeverityChip severity={r.priority as any} />
                <span className={cn('font-mono text-xs', r.enabled ? 'text-verdant' : 'text-text-muted')}>
                  {r.enabled ? 'on' : 'off'}
                </span>
                <span className="font-mono text-xs text-text-secondary">{r.triggered}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {view === 'history' && (
        <div className="flex flex-col items-center justify-center py-20 text-text-muted">
          <p className="text-sm">Alert history (last 30d)</p>
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert }: { alert: Alert }) {
  const navigate = useNavigate();
  const statusVariant: Record<string, string> = {
    firing:    'danger',
    resolved:  'success',
    suppressed:'default',
    pending:   'warning',
  };

  return (
    <div
      onClick={() => navigate(`/alerts/${alert.id}`)}
      className={cn(
        'panel p-4 cursor-pointer hover:border-border-hover transition-colors border-l-2',
        alert.priority === 'P0' ? 'border-l-ember' :
        alert.priority === 'P1' ? 'border-l-amber' :
        alert.priority === 'P2' ? 'border-l-signal' : 'border-l-border-default',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <SeverityChip severity={alert.priority} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span className="font-mono text-2xs text-text-muted">{alert.id}</span>
              <AetherBadge variant={statusVariant[alert.status] as any}>{alert.status}</AetherBadge>
              <AetherBadge variant="default" mono>{alert.category}</AetherBadge>
            </div>
            <p className="text-sm text-text-primary truncate">{alert.name}</p>
            <div className="flex items-center gap-3 mt-1">
              <span className="text-xs text-text-muted">triggered {alert.triggered}</span>
              {alert.count > 1 && <span className="font-mono text-2xs text-amber">×{alert.count}</span>}
              {alert.assignee && (
                <span className="text-xs text-text-muted">
                  assignee: <span className="font-mono text-text-secondary">{alert.assignee}</span>
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={e => { e.stopPropagation(); navigate(`/investigations/new?alert=${alert.id}`); }}
            className="text-xs px-2 py-1 rounded border border-signal/30 text-steel hover:bg-signal/5 transition-colors"
          >
            Investigate
          </button>
          <button onClick={e => e.stopPropagation()} className="text-xs px-2 py-1 rounded border border-border-default text-text-muted hover:text-text-primary transition-colors">
            Suppress
          </button>
        </div>
      </div>
    </div>
  );
}
