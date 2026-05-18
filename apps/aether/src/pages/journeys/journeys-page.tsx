import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { StatCard } from '../../components/ui/stat-card';
import { AetherBadge } from '../../components/ui/aether-badge';
import { EntityId } from '../../components/ui/entity-id';

const JOURNEYS = [
  { id: 'jrn_9k2f_001', entityId: 'usr_9k2f', type: 'checkout', steps: 2, expectedSteps: 14, duration: '1.8s', anomaly: true,  score: 91, lastEvent: '14:31', conversion: false },
  { id: 'jrn_7b3m_001', entityId: 'usr_7b3m', type: 'onboarding', steps: 8, expectedSteps: 8, duration: '4m 12s', anomaly: false, score: 12, lastEvent: '14:28', conversion: true },
  { id: 'jrn_4f9p_001', entityId: 'usr_4f9p', type: 'checkout', steps: 6, expectedSteps: 7, duration: '2m 33s', anomaly: false, score: 22, lastEvent: '14:18', conversion: true },
  { id: 'jrn_2b8x_001', entityId: 'usr_2b8x', type: 'signup',  steps: 4, expectedSteps: 4, duration: '1m 55s', anomaly: false, score: 8,  lastEvent: '13:52', conversion: true },
  { id: 'jrn_m9k3_001', entityId: 'usr_m9k3', type: 'checkout', steps: 3, expectedSteps: 7, duration: '52s',   anomaly: true,  score: 78, lastEvent: '13:44', conversion: false },
];

export function JourneysPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState('all');

  const anomalies = JOURNEYS.filter(j => j.anomaly).length;
  const conversions = JOURNEYS.filter(j => j.conversion).length;

  return (
    <div className="px-6 py-5">
      <PageHeader
        eyebrow="Intelligence Surface"
        title="Journey Intelligence"
        subtitle="Multi-step entity journey analysis and replay"
      />

      <div className="grid grid-cols-4 gap-3 mb-5">
        <StatCard label="Active journeys" value={JOURNEYS.length} mono />
        <StatCard label="Anomalies" value={anomalies} accent="warning" mono />
        <StatCard label="Conversions" value={conversions} accent="success" mono />
        <StatCard label="Avg steps" value="4.6" mono />
      </div>

      <div className="flex items-center gap-1 mb-4">
        {['all', 'checkout', 'onboarding', 'signup', 'anomaly'].map(f => (
          <button key={f}
            onClick={() => setFilter(f)}
            className={cn('px-3 py-1 rounded-pill border font-mono text-2xs font-medium transition-colors',
              filter === f ? 'bg-signal/10 text-steel border-signal/30' : 'border-border-default text-text-muted hover:text-text-primary')}
          >{f}</button>
        ))}
      </div>

      <div className="panel overflow-hidden">
        <div className="grid grid-cols-[160px_100px_80px_120px_100px_80px_80px_80px] gap-3 px-4 py-2 border-b border-border-subtle bg-surface-sidebar">
          {['ENTITY', 'TYPE', 'STEPS', 'DURATION', 'LAST EVENT', 'ANOMALY', 'RISK', 'CONV.'].map(h => (
            <span key={h} className="label-eyebrow">{h}</span>
          ))}
        </div>
        <div className="divide-y divide-border-subtle">
          {JOURNEYS.map(j => (
            <div key={j.id} onClick={() => navigate(`/journeys/${j.id}`)}
              className="grid grid-cols-[160px_100px_80px_120px_100px_80px_80px_80px] gap-3 px-4 py-3 hover:bg-surface-overlay cursor-pointer transition-colors">
              <EntityId id={j.entityId} />
              <AetherBadge variant="default" mono>{j.type}</AetherBadge>
              <span className={cn('font-mono text-xs', j.anomaly ? 'text-amber' : 'text-text-secondary')}>
                {j.steps}/{j.expectedSteps}
              </span>
              <span className="font-mono text-xs text-text-secondary">{j.duration}</span>
              <span className="font-mono text-xs text-text-muted">{j.lastEvent}</span>
              {j.anomaly
                ? <AetherBadge variant="warning">anomaly</AetherBadge>
                : <span className="text-2xs text-text-muted">—</span>}
              <div className="trust-bar">
                <div className="trust-track"><div className={cn('trust-fill', j.score > 75 ? 'bg-ember' : j.score > 50 ? 'bg-amber' : 'bg-verdant')} style={{ width: `${j.score}%` }} /></div>
                <span className="font-mono text-2xs text-text-muted">{j.score}</span>
              </div>
              {j.conversion
                ? <span className="text-verdant font-mono text-xs">✓</span>
                : <span className="text-ember font-mono text-xs">✗</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
