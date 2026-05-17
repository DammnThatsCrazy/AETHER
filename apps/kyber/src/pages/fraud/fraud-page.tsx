import { useState } from 'react';
import { PageWrapper } from '@kyber/components/layout';
import {
  Card, CardContent, CardHeader, CardTitle,
  Badge, Button, Tabs, TabsList, TabsTrigger, TabsContent,
  LoadingState, ErrorState, EmptyState,
} from '@aether/ui';
import { cn } from '@kyber/lib/utils';
import { useFraudOpsView } from '@kyber/features/operator';

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function fmt(v: unknown, fallback = '—'): string { return v == null || v === '' ? fallback : String(v); }
function fmtPct(v: unknown): string { return v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`; }
function fmtNum(v: unknown): string { return v == null ? '—' : Number(v).toLocaleString(); }

function RiskBadge({ score }: { score: number }) {
  const variant = score >= 0.8 ? 'danger' : score >= 0.5 ? 'warning' : 'success';
  return <Badge variant={variant}>{Math.round(score * 100)}</Badge>;
}

export function FraudPage() {
  const { stats, config, evaluate, updateConfig } = useFraudOpsView();
  const [testEvent, setTestEvent] = useState('{\n  "event_type": "payment",\n  "user_id": "",\n  "amount": 0\n}');
  const [evalResult, setEvalResult] = useState<unknown>(null);

  const statsData = asRecord(stats.data);
  const configData = asRecord(config.data);

  const handleEvaluate = async () => {
    try {
      const event = JSON.parse(testEvent) as Record<string, unknown>;
      const result = await evaluate.mutate({ event });
      setEvalResult(result);
    } catch {
      setEvalResult({ error: 'Invalid JSON' });
    }
  };

  return (
    <PageWrapper title="Fraud Ops" subtitle="Evaluate events, monitor fraud signals, manage config">
      {/* Stats strip */}
      {stats.isLoading ? <LoadingState lines={1} /> : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          {[
            { label: 'Total Evaluated', value: fmtNum(statsData.total_evaluated ?? statsData.total) },
            { label: 'Flagged', value: fmtNum(statsData.flagged) },
            { label: 'Flag Rate', value: fmtPct(statsData.flag_rate) },
            { label: 'Avg Risk Score', value: fmtPct(statsData.avg_risk_score) },
          ].map(({ label, value }) => (
            <div key={label} className="bg-surface-raised border border-border-default rounded px-3 py-2">
              <p className="text-[10px] text-text-muted font-mono">{label}</p>
              <p className="text-lg font-bold font-mono text-text-primary">{value}</p>
            </div>
          ))}
        </div>
      )}

      <Tabs defaultValue="evaluate">
        <TabsList>
          <TabsTrigger value="evaluate">Evaluate</TabsTrigger>
          <TabsTrigger value="config">Config</TabsTrigger>
        </TabsList>

        {/* ── Evaluate ── */}
        <TabsContent value="evaluate">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <CardHeader><CardTitle className="font-mono text-xs">Test Event Payload</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <textarea
                  value={testEvent}
                  onChange={e => setTestEvent(e.target.value)}
                  rows={10}
                  className="w-full bg-surface-sunken border border-border-default rounded px-2 py-1.5 text-xs font-mono text-text-primary focus:outline-none focus:border-accent resize-y"
                />
                <Button variant="primary" size="sm" onClick={handleEvaluate} disabled={evaluate.isLoading}>
                  {evaluate.isLoading ? 'Evaluating…' : 'Evaluate'}
                </Button>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="font-mono text-xs">Result</CardTitle></CardHeader>
              <CardContent>
                {evalResult == null ? (
                  <p className="text-xs text-text-muted font-mono">Submit an event to see the fraud evaluation result.</p>
                ) : (
                  <pre className="text-xs font-mono text-text-secondary whitespace-pre-wrap overflow-auto max-h-64">
                    {JSON.stringify(evalResult, null, 2)}
                  </pre>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ── Config ── */}
        <TabsContent value="config">
          {config.isLoading ? <LoadingState lines={4} /> : (
            <Card>
              <CardHeader><CardTitle className="font-mono text-xs">Fraud Config</CardTitle></CardHeader>
              <CardContent>
                <pre className="text-xs font-mono text-text-secondary whitespace-pre-wrap">
                  {JSON.stringify(configData, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
