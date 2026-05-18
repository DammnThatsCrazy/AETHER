import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { StatCard } from '../../components/ui/stat-card';
import { AetherBadge } from '../../components/ui/aether-badge';
import { SeverityChip } from '../../components/ui/severity-chip';

const CLUSTERS = [
  { id: 'CL-28x', type: 'device-ring',    entities: 47, risk: 94, status: 'escalated', sev: 'P0', growth: '+12h', signals: 5, tags: ['fraud', 'device-ring', 'coordinated'] },
  { id: 'CL-31f', type: 'account-cluster',entities: 23, risk: 81, status: 'escalated', sev: 'P1', growth: '+30m', signals: 3, tags: ['synthetic', 'multi-account'] },
  { id: 'CW-04',  type: 'wallet-cluster', entities: 8,  risk: 72, status: 'watchlist', sev: 'P2', growth: '—',    signals: 2, tags: ['web3', 'bridge'] },
  { id: 'CL-29k', type: 'geo-cluster',    entities: 15, risk: 63, status: 'watchlist', sev: 'P2', growth: '+2d',  signals: 2, tags: ['geo', 'subnet'] },
  { id: 'CL-22m', type: 'behavior',       entities: 41, risk: 44, status: 'active',    sev: 'P3', growth: '+1w',  signals: 1, tags: ['behavior', 'segment'] },
];

export function ClustersPage() {
  const navigate = useNavigate();

  return (
    <div className="px-6 py-5">
      <PageHeader
        eyebrow="Intelligence Surface"
        title="Cluster Intelligence"
        subtitle="Entity cluster detection, analysis, and investigation"
      />

      <div className="grid grid-cols-4 gap-3 mb-5">
        <StatCard label="Total clusters" value={CLUSTERS.length} mono />
        <StatCard label="Escalated" value={CLUSTERS.filter(c => c.status === 'escalated').length} accent="danger" mono />
        <StatCard label="High risk (>75)" value={CLUSTERS.filter(c => c.risk > 75).length} accent="danger" mono />
        <StatCard label="Total entities" value={CLUSTERS.reduce((a, c) => a + c.entities, 0)} mono />
      </div>

      <div className="space-y-2">
        {CLUSTERS.map(cl => (
          <div key={cl.id}
            onClick={() => navigate(`/clusters/${cl.id}`)}
            className={cn('panel p-4 cursor-pointer hover:border-border-hover transition-colors border-l-2',
              cl.sev === 'P0' ? 'border-l-ember' : cl.sev === 'P1' ? 'border-l-amber' : 'border-l-border-default'
            )}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <SeverityChip severity={cl.sev as any} />
                <span className="font-mono text-sm font-medium text-text-primary">{cl.id}</span>
                <AetherBadge variant="default" mono>{cl.type}</AetherBadge>
                <AetherBadge variant={cl.status === 'escalated' ? 'danger' : cl.status === 'watchlist' ? 'warning' : 'success'}>
                  {cl.status}
                </AetherBadge>
              </div>
              <div className="flex items-center gap-6">
                <div className="text-right">
                  <p className="font-mono text-xs text-text-muted">entities</p>
                  <p className="font-mono text-sm text-text-primary">{cl.entities}</p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-xs text-text-muted">risk</p>
                  <p className={cn('font-mono text-sm font-medium', cl.risk > 75 ? 'text-ember' : cl.risk > 50 ? 'text-amber' : 'text-verdant')}>{cl.risk}</p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-xs text-text-muted">signals</p>
                  <p className="font-mono text-sm text-amber">{cl.signals}</p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-xs text-text-muted">growth</p>
                  <p className="font-mono text-sm text-text-secondary">{cl.growth}</p>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1 mt-2">
              {cl.tags.map(t => <span key={t} className="font-mono text-2xs text-text-muted bg-surface-overlay px-1.5 py-px rounded">{t}</span>)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
