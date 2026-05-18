import { useState, useEffect } from 'react';
import { PageHeader } from '../../components/ui/panel-header';
import { StatCard } from '../../components/ui/stat-card';
import { AetherBadge } from '../../components/ui/aether-badge';
import { LiveIndicator } from '../../components/ui/live-indicator';

const SERVICES = [
  { id: 'ingestion',    name: 'Event Ingestion',     status: 'healthy',   latency: '12ms', throughput: '8.4k/s',  uptime: '99.99%' },
  { id: 'graph',        name: 'Graph Engine',         status: 'healthy',   latency: '28ms', throughput: '38.4k/h', uptime: '99.98%' },
  { id: 'intelligence', name: 'Intelligence Engine',  status: 'healthy',   latency: '145ms',throughput: '847/m',   uptime: '99.97%' },
  { id: 'realtime',     name: 'WebSocket Gateway',    status: 'degraded',  latency: '820ms',throughput: '2.1k conn',uptime: '99.91%' },
  { id: 'api',          name: 'REST API',             status: 'healthy',   latency: '18ms', throughput: '48.2k/h', uptime: '99.99%' },
  { id: 'queue',        name: 'Event Queue',          status: 'healthy',   latency: '4ms',  throughput: '0 lag',   uptime: '100%' },
  { id: 'warehouse',    name: 'Data Warehouse',       status: 'healthy',   latency: '230ms',throughput: '—',       uptime: '99.95%' },
  { id: 'governance',   name: 'Governance Engine',    status: 'healthy',   latency: '35ms', throughput: '—',       uptime: '100%' },
];

const STATUS_COLOR: Record<string, string> = {
  healthy:    'bg-verdant',
  degraded:   'bg-amber',
  unhealthy:  'bg-ember',
  unknown:    'bg-text-muted',
};

const STATUS_TEXT: Record<string, string> = {
  healthy:   'text-verdant',
  degraded:  'text-amber',
  unhealthy: 'text-ember',
};

export function MonitoringPage() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(v => v + 1), 5000);
    return () => clearInterval(id);
  }, []);

  const healthy  = SERVICES.filter(s => s.status === 'healthy').length;
  const degraded = SERVICES.filter(s => s.status === 'degraded').length;

  return (
    <div className="px-6 py-5">
      <PageHeader
        eyebrow="Operations"
        title="System Monitoring"
        subtitle="Realtime infrastructure health and operational metrics"
        actions={<LiveIndicator />}
      />

      <div className="grid grid-cols-4 gap-3 mb-5">
        <StatCard label="Healthy services" value={`${healthy}/${SERVICES.length}`} accent="success" mono />
        <StatCard label="Degraded" value={degraded} accent="warning" mono />
        <StatCard label="Event throughput" value="8.4k/s" delta={{ value: '2%', positive: true }} mono />
        <StatCard label="Graph mutations / h" value="38.4k" delta={{ value: '3.2×', positive: false }} mono />
      </div>

      {/* Services grid */}
      <div className="grid grid-cols-2 gap-3 mb-5">
        {SERVICES.map(svc => (
          <div key={svc.id} className="panel p-4">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <div className={`w-2 h-2 rounded-pill flex-shrink-0 ${STATUS_COLOR[svc.status]}`} />
                <span className="text-sm font-medium text-text-primary">{svc.name}</span>
              </div>
              <span className={`font-mono text-xs font-medium ${STATUS_TEXT[svc.status] ?? 'text-text-muted'}`}>
                {svc.status}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <p className="label-eyebrow mb-1">Latency</p>
                <p className="font-mono text-sm text-text-primary">{svc.latency}</p>
              </div>
              <div>
                <p className="label-eyebrow mb-1">Throughput</p>
                <p className="font-mono text-sm text-text-primary">{svc.throughput}</p>
              </div>
              <div>
                <p className="label-eyebrow mb-1">Uptime</p>
                <p className={`font-mono text-sm ${svc.status === 'healthy' ? 'text-verdant' : 'text-amber'}`}>{svc.uptime}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Event throughput chart placeholder */}
      <div className="panel p-4 mb-4">
        <div className="flex items-center justify-between mb-3">
          <p className="panel-title">Event Throughput (5min buckets)</p>
          <AetherBadge variant="success" mono>live</AetherBadge>
        </div>
        <div className="flex items-end gap-1 h-20">
          {Array.from({ length: 60 }, (_, i) => {
            const h = 20 + Math.random() * 80;
            return (
              <div
                key={i}
                className="flex-1 rounded-t bg-signal/40 hover:bg-signal/60 transition-colors"
                style={{ height: `${h}%` }}
                title={`${Math.round(8000 + Math.random() * 800)}/s`}
              />
            );
          })}
        </div>
        <div className="flex items-center justify-between mt-1">
          <span className="font-mono text-2xs text-text-muted">−60min</span>
          <span className="font-mono text-2xs text-text-muted">now</span>
        </div>
      </div>

      {/* WebSocket panel */}
      <div className="panel p-4">
        <p className="panel-title mb-3">WebSocket Gateway — P99 Latency ⚠ degraded</p>
        <div className="flex items-end gap-1 h-16">
          {Array.from({ length: 60 }, (_, i) => {
            const isSpike = i > 45;
            const h = isSpike ? 60 + Math.random() * 40 : 10 + Math.random() * 30;
            return (
              <div
                key={i}
                className={`flex-1 rounded-t transition-colors ${isSpike ? 'bg-amber/60' : 'bg-verdant/40'}`}
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
        <p className="font-mono text-xs text-amber mt-2">P99 currently 820ms · threshold 500ms · investigating</p>
      </div>
    </div>
  );
}
