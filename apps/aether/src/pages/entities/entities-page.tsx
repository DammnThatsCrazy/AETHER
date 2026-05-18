import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { AetherBadge } from '../../components/ui/aether-badge';
import { StatCard } from '../../components/ui/stat-card';
import { EntityId } from '../../components/ui/entity-id';

interface Entity {
  id: string;
  type: 'user' | 'device' | 'wallet' | 'agent';
  riskScore: number;
  trustScore: number;
  confidence: number;
  relationships: number;
  lastSeen: string;
  signals: number;
  status: 'active' | 'escalated' | 'resolved' | 'watchlist';
  country: string;
}

const MOCK_ENTITIES: Entity[] = [
  { id: 'usr_9k2f', type: 'user',   riskScore: 92, trustScore: 31, confidence: 88, relationships: 5, lastSeen: '2m ago',  signals: 5, status: 'escalated', country: 'US' },
  { id: 'usr_7b3m', type: 'user',   riskScore: 67, trustScore: 58, confidence: 82, relationships: 3, lastSeen: '14m ago', signals: 2, status: 'watchlist', country: 'DE' },
  { id: 'usr_4f9p', type: 'user',   riskScore: 44, trustScore: 71, confidence: 76, relationships: 2, lastSeen: '31m ago', signals: 1, status: 'active',    country: 'GB' },
  { id: 'dev_k3m9', type: 'device', riskScore: 85, trustScore: 40, confidence: 91, relationships: 3, lastSeen: '8m ago',  signals: 3, status: 'escalated', country: 'US' },
  { id: 'dev_p2x8', type: 'device', riskScore: 51, trustScore: 62, confidence: 74, relationships: 2, lastSeen: '1h ago',  signals: 1, status: 'active',    country: 'FR' },
  { id: 'wal_1a2b', type: 'wallet', riskScore: 72, trustScore: 45, confidence: 88, relationships: 2, lastSeen: '20m ago', signals: 2, status: 'watchlist', country: '—' },
  { id: 'wal_9f8e', type: 'wallet', riskScore: 38, trustScore: 78, confidence: 90, relationships: 1, lastSeen: '3h ago',  signals: 0, status: 'active',    country: '—' },
  { id: 'agt_ora',  type: 'agent',  riskScore: 55, trustScore: 65, confidence: 100,relationships: 1, lastSeen: '1m ago',  signals: 1, status: 'watchlist', country: '—' },
  { id: 'usr_2b8x', type: 'user',   riskScore: 29, trustScore: 84, confidence: 71, relationships: 4, lastSeen: '4h ago',  signals: 0, status: 'active',    country: 'CA' },
  { id: 'usr_m9k3', type: 'user',   riskScore: 18, trustScore: 92, confidence: 95, relationships: 7, lastSeen: '5h ago',  signals: 0, status: 'active',    country: 'JP' },
];

type Filter = 'all' | 'escalated' | 'watchlist' | 'user' | 'device' | 'wallet' | 'agent';
type Sort = 'risk' | 'trust' | 'lastSeen' | 'signals';

const STATUS_STYLE: Record<string, string> = {
  escalated: 'danger',
  watchlist: 'warning',
  active:    'success',
  resolved:  'default',
};

export function EntitiesPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>('all');
  const [sort, setSort] = useState<Sort>('risk');
  const [search, setSearch] = useState('');

  const filtered = MOCK_ENTITIES
    .filter(e => {
      if (search) return e.id.includes(search.toLowerCase());
      if (filter === 'all') return true;
      if (filter === 'escalated') return e.status === 'escalated';
      if (filter === 'watchlist') return e.status === 'watchlist';
      return e.type === filter;
    })
    .sort((a, b) => {
      if (sort === 'risk') return b.riskScore - a.riskScore;
      if (sort === 'trust') return a.trustScore - b.trustScore;
      if (sort === 'signals') return b.signals - a.signals;
      return 0;
    });

  const escalated = MOCK_ENTITIES.filter(e => e.status === 'escalated').length;
  const watchlist = MOCK_ENTITIES.filter(e => e.status === 'watchlist').length;

  return (
    <div className="px-6 py-5">
      <PageHeader
        eyebrow="Intelligence Surface"
        title="Entities"
        subtitle="Resolved entity intelligence across all types"
        actions={
          <button
            onClick={() => navigate('/graph')}
            className="text-xs px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors"
          >
            ⬡ Graph view
          </button>
        }
      />

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        <StatCard label="Total entities" value={MOCK_ENTITIES.length} mono />
        <StatCard label="Escalated"     value={escalated} accent="danger"  icon="△" mono />
        <StatCard label="Watchlist"     value={watchlist}  accent="warning" icon="○" mono />
        <StatCard label="High risk (>75)" value={MOCK_ENTITIES.filter(e => e.riskScore > 75).length} accent="danger" mono />
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3 mb-4">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter by entity ID…"
          className="flex-1 max-w-xs bg-surface-raised border border-border-default rounded px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted outline-none focus:border-signal transition-colors font-mono"
        />
        <div className="flex items-center gap-1">
          {(['all', 'escalated', 'watchlist', 'user', 'device', 'wallet', 'agent'] as Filter[]).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'px-3 py-1 rounded-pill border font-mono text-2xs font-medium tracking-wide transition-colors',
                filter === f
                  ? 'bg-signal/10 text-steel border-signal/30'
                  : 'border-border-default text-text-muted hover:text-text-primary',
              )}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5 ml-auto">
          <span className="label-eyebrow">Sort</span>
          <select
            value={sort}
            onChange={e => setSort(e.target.value as Sort)}
            className="bg-surface-raised border border-border-default rounded px-2 py-1 text-xs text-text-secondary outline-none"
          >
            <option value="risk">Risk ↓</option>
            <option value="trust">Trust ↑</option>
            <option value="lastSeen">Last seen</option>
            <option value="signals">Signals ↓</option>
          </select>
        </div>
        <span className="font-mono text-xs text-text-muted">{filtered.length} entities</span>
      </div>

      {/* Table */}
      <div className="panel overflow-hidden">
        {/* Header */}
        <div className="grid grid-cols-[160px_80px_80px_80px_100px_80px_80px_100px_100px] gap-3 px-4 py-2 border-b border-border-subtle bg-surface-sidebar">
          {['ENTITY', 'TYPE', 'RISK', 'TRUST', 'CONFIDENCE', 'REL', 'SIGNALS', 'LAST SEEN', 'STATUS'].map(h => (
            <span key={h} className="label-eyebrow">{h}</span>
          ))}
        </div>

        <div className="divide-y divide-border-subtle">
          {filtered.map(entity => (
            <div
              key={entity.id}
              onClick={() => navigate(`/entities/${entity.id}`)}
              className="grid grid-cols-[160px_80px_80px_80px_100px_80px_80px_100px_100px] gap-3 px-4 py-3 hover:bg-surface-overlay cursor-pointer transition-colors"
            >
              <EntityId id={entity.id} type={entity.type as 'entity'} truncate={false} />
              <AetherBadge variant="default" mono>{entity.type}</AetherBadge>

              <div className="flex items-center gap-1.5">
                <div className="trust-track w-12"><div className={cn('trust-fill', entity.riskScore > 75 ? 'bg-ember' : entity.riskScore > 50 ? 'bg-amber' : 'bg-verdant')} style={{ width: `${entity.riskScore}%` }} /></div>
                <span className="font-mono text-2xs text-text-primary w-5">{entity.riskScore}</span>
              </div>

              <div className="flex items-center gap-1.5">
                <div className="trust-track w-12"><div className="trust-fill bg-steel" style={{ width: `${entity.trustScore}%` }} /></div>
                <span className="font-mono text-2xs text-text-primary w-5">{entity.trustScore}</span>
              </div>

              <span className="font-mono text-2xs text-text-secondary">{entity.confidence}%</span>
              <span className="font-mono text-2xs text-text-secondary">{entity.relationships}</span>
              <span className={cn('font-mono text-2xs', entity.signals > 0 ? 'text-amber' : 'text-text-muted')}>
                {entity.signals > 0 ? `▲ ${entity.signals}` : '—'}
              </span>
              <span className="font-mono text-2xs text-text-muted">{entity.lastSeen}</span>
              <AetherBadge variant={(STATUS_STYLE[entity.status] ?? 'default') as any}>
                {entity.status}
              </AetherBadge>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
