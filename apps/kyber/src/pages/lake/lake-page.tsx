import { useState } from 'react';
import { PageWrapper } from '@kyber/components/layout';
import {
  Card, CardContent, CardHeader, CardTitle,
  Badge, Button, Tabs, TabsList, TabsTrigger, TabsContent,
  LoadingState, Select,
} from '@aether/ui';
import { cn } from '@kyber/lib/utils';
import { useLakeOpsView } from '@kyber/features/operator';

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function fmt(v: unknown, fallback = '—'): string { return v == null || v === '' ? fallback : String(v); }

const DOMAINS = [
  { value: 'identity', label: 'Identity' },
  { value: 'market', label: 'Market' },
  { value: 'onchain', label: 'Onchain' },
  { value: 'social', label: 'Social' },
];

function qualityColor(score: number) {
  if (score >= 0.9) return 'text-success';
  if (score >= 0.7) return 'text-warning';
  return 'text-danger';
}

export function LakePage() {
  const [domain, setDomain] = useState('identity');
  const { status, quality, ingest, rollback } = useLakeOpsView(domain);

  const statusData = asRecord(status.data);
  const qualityData = asRecord(quality.data);
  const qualityScore = Number(qualityData.quality_score ?? qualityData.score ?? 0);
  const dimensions = asRecord(qualityData.dimensions ?? {});

  return (
    <PageWrapper
      title="Lake Ops"
      subtitle="Data lake quality, status, and ingestion control"
      actions={
        <Select
          options={DOMAINS}
          value={domain}
          onChange={setDomain}
          label="Domain"
        />
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Status */}
        <Card>
          <CardHeader><CardTitle className="font-mono text-xs">Lake Status</CardTitle></CardHeader>
          <CardContent>
            {status.isLoading ? <LoadingState lines={3} /> : (
              <div className="space-y-2">
                {Object.entries(statusData).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between text-xs font-mono">
                    <span className="text-text-secondary capitalize">{k.replace(/_/g, ' ')}</span>
                    <span className="text-text-primary">{fmt(v)}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Quality */}
        <Card>
          <CardHeader>
            <CardTitle className="font-mono text-xs">Quality — {domain}</CardTitle>
            {!quality.isLoading && qualityScore > 0 && (
              <span className={cn('text-2xl font-bold font-mono', qualityColor(qualityScore))}>
                {Math.round(qualityScore * 100)}%
              </span>
            )}
          </CardHeader>
          <CardContent>
            {quality.isLoading ? <LoadingState lines={3} /> : (
              <div className="space-y-2">
                {Object.entries(dimensions).map(([dim, score]) => {
                  const pct = Math.round(Number(score) * 100);
                  return (
                    <div key={dim} className="space-y-0.5">
                      <div className="flex justify-between text-xs font-mono">
                        <span className="text-text-secondary capitalize">{dim}</span>
                        <span className={qualityColor(Number(score))}>{pct}%</span>
                      </div>
                      <div className="h-1 bg-surface-overlay rounded-full overflow-hidden">
                        <div className={cn('h-full rounded-full', pct >= 90 ? 'bg-success' : pct >= 70 ? 'bg-warning' : 'bg-danger')} style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Rollback */}
      <Card className="mt-4">
        <CardHeader><CardTitle className="font-mono text-xs">Rollback</CardTitle></CardHeader>
        <CardContent className="flex items-center gap-3">
          <p className="text-xs text-text-muted font-mono">Rollback ingested data for the selected domain by source tag.</p>
          <Button
            variant="danger"
            size="sm"
            onClick={() => rollback.mutate({ domain, source_tag: 'latest' })}
            disabled={rollback.isLoading}
          >
            {rollback.isLoading ? 'Rolling back…' : 'Rollback Latest'}
          </Button>
          {rollback.data != null && <span className="text-xs text-success font-mono">Rolled back.</span>}
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
