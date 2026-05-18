import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { AetherBadge } from '../../components/ui/aether-badge';
import { SeverityChip } from '../../components/ui/severity-chip';
import { StatCard } from '../../components/ui/stat-card';

interface Investigation {
  id: string;
  title: string;
  status: 'open' | 'in-progress' | 'pending-review' | 'closed';
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  assignee: string;
  entities: number;
  evidence: number;
  opened: string;
  updated: string;
  tags: string[];
}

const MOCK_INVESTIGATIONS: Investigation[] = [
  { id: 'INV-0041', title: 'Coordinated fraud ring — CL-28x (47 entities)', status: 'in-progress',    priority: 'P0', assignee: 'analyst_01', entities: 47, evidence: 23, opened: '2h ago',  updated: '14m ago', tags: ['fraud', 'cluster', 'device-ring'] },
  { id: 'INV-0040', title: 'Multi-account synthetic identity cluster',         status: 'pending-review', priority: 'P1', assignee: 'analyst_02', entities: 12, evidence: 8,  opened: '6h ago',  updated: '2h ago',  tags: ['synthetic', 'identity', 'multi-account'] },
  { id: 'INV-0039', title: 'Agent agt_oracle rate limit breach analysis',      status: 'open',           priority: 'P1', assignee: 'unassigned', entities: 1,  evidence: 3,  opened: '8h ago',  updated: '8h ago',  tags: ['agent', 'rate-limit', 'agentic'] },
  { id: 'INV-0038', title: 'Cross-chain wallet bridge anomaly — Optimism',     status: 'in-progress',    priority: 'P2', assignee: 'analyst_03', entities: 6,  evidence: 11, opened: '1d ago',  updated: '3h ago',  tags: ['web3', 'bridge', 'wallet'] },
  { id: 'INV-0037', title: 'Journey friction analysis — checkout funnel',      status: 'closed',         priority: 'P3', assignee: 'analyst_01', entities: 3,  evidence: 5,  opened: '2d ago',  updated: '1d ago',  tags: ['journey', 'friction', 'ecommerce'] },
  { id: 'INV-0036', title: 'PII access outside consent scope — 3 records',    status: 'pending-review', priority: 'P1', assignee: 'analyst_04', entities: 3,  evidence: 7,  opened: '3d ago',  updated: '5h ago',  tags: ['governance', 'consent', 'pii'] },
  { id: 'INV-0035', title: 'Device fingerprint collision — shared hardware',   status: 'in-progress',    priority: 'P2', assignee: 'analyst_02', entities: 8,  evidence: 14, opened: '4d ago',  updated: '1h ago',  tags: ['device', 'fingerprint', 'collision'] },
];

const STATUS_STYLE: Record<string, string> = {
  'open':           'default',
  'in-progress':    'info',
  'pending-review': 'warning',
  'closed':         'success',
};

export function InvestigationsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<string>('all');

  const filtered = MOCK_INVESTIGATIONS.filter(i =>
    status === 'all' || i.status === status
  );

  const open = MOCK_INVESTIGATIONS.filter(i => i.status !== 'closed').length;
  const pendingReview = MOCK_INVESTIGATIONS.filter(i => i.status === 'pending-review').length;

  return (
    <div className="px-6 py-5">
      <PageHeader
        eyebrow="Investigations"
        title="Investigations"
        subtitle="Active and historical intelligence investigations"
        actions={
          <button
            onClick={() => navigate('/investigations/new')}
            className="text-xs px-3 py-1.5 rounded bg-signal text-stone-white font-medium hover:bg-signal/90 transition-colors"
          >
            + New investigation
          </button>
        }
      />

      <div className="grid grid-cols-4 gap-3 mb-5">
        <StatCard label="Open"           value={open}          accent="warning" mono />
        <StatCard label="Pending review" value={pendingReview} accent="warning" mono />
        <StatCard label="Total"          value={MOCK_INVESTIGATIONS.length} mono />
        <StatCard label="Closed (30d)"   value={1} accent="success" mono />
      </div>

      {/* Status filter */}
      <div className="flex items-center gap-1 mb-4">
        {['all', 'open', 'in-progress', 'pending-review', 'closed'].map(s => (
          <button
            key={s}
            onClick={() => setStatus(s)}
            className={cn(
              'px-3 py-1 rounded-pill border font-mono text-2xs font-medium tracking-wide transition-colors',
              status === s
                ? 'bg-signal/10 text-steel border-signal/30'
                : 'border-border-default text-text-muted hover:text-text-primary',
            )}
          >
            {s}
          </button>
        ))}
        <span className="font-mono text-xs text-text-muted ml-auto">{filtered.length} investigations</span>
      </div>

      <div className="space-y-2">
        {filtered.map(inv => (
          <div
            key={inv.id}
            onClick={() => navigate(`/investigations/${inv.id}`)}
            className={cn(
              'panel p-4 cursor-pointer hover:border-border-hover transition-colors',
              'border-l-2',
              inv.priority === 'P0' ? 'border-l-ember' : inv.priority === 'P1' ? 'border-l-amber' : 'border-l-border-default',
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-3 flex-1 min-w-0">
                <SeverityChip severity={inv.priority} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono text-xs text-text-muted">{inv.id}</span>
                    <AetherBadge variant={STATUS_STYLE[inv.status] as any}>{inv.status}</AetherBadge>
                  </div>
                  <p className="text-sm text-text-primary font-medium truncate">{inv.title}</p>
                  <div className="flex items-center gap-4 mt-1.5">
                    <span className="text-xs text-text-muted">
                      <span className="text-text-secondary">{inv.entities}</span> entities
                    </span>
                    <span className="text-xs text-text-muted">
                      <span className="text-text-secondary">{inv.evidence}</span> evidence
                    </span>
                    <span className="text-xs text-text-muted">assigned: <span className="font-mono text-text-secondary">{inv.assignee}</span></span>
                    <div className="flex items-center gap-1">
                      {inv.tags.slice(0, 3).map(t => (
                        <span key={t} className="font-mono text-2xs text-text-muted bg-surface-overlay px-1.5 py-px rounded">{t}</span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
              <div className="text-right flex-shrink-0">
                <p className="font-mono text-2xs text-text-muted">opened {inv.opened}</p>
                <p className="font-mono text-2xs text-text-muted">updated {inv.updated}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
