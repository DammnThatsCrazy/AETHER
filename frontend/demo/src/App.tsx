import { useState } from 'react';
import { Badge, Card, CardContent, CardHeader, CardTitle } from '@aether/ui';
import {
  DATA_QUALITY, DECISIONS, DEMO_TENANT, DISPATCHES, INGESTION_PATHS, KYBER_VIEW,
  OODA, OUTCOMES, PLAYBOOKS, PROFILE360, RECOMMENDATIONS, VALUE_REVIEW,
} from '@demo/data/dataset';
import { DEMO_DATA_SOURCE_LABEL, getDemoEnv, type DemoEnv } from '@demo/lib/env';

type View = 'tenant' | 'operator';

// Every demo profile serves synthetic data. The label is persistent and
// visible so the app can never be mistaken for a production tenant.
function SyntheticDataBanner({ env }: { readonly env: DemoEnv }) {
  return (
    <div
      role="status"
      data-testid="synthetic-data-banner"
      className="sticky top-0 z-50 -mx-6 -mt-6 mb-1 border-b border-warning bg-surface-raised px-6 py-2 text-xs font-medium text-warning"
    >
      Synthetic demo data — not a production tenant. Profile{' '}
      <span className="font-mono">{env}</span> · {DEMO_DATA_SOURCE_LABEL[env]}.
    </div>
  );
}

function Step({ n, title, children }: { readonly n: number; readonly title: string; readonly children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          <span className="mr-2 font-mono text-text-muted">{n}</span>{title}
        </CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function IngestionSimulator() {
  const [count, setCount] = useState(0);
  const [last, setLast] = useState<string | null>(null);
  async function send(kind: string) {
    try {
      const res = await fetch('/v1/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch: [{ id: `demo_${Date.now()}`, type: 'track', timestamp: new Date().toISOString(), sessionId: 'demo', anonymousId: 'demo', properties: { event: kind } }] }),
      });
      const body = await res.json().catch(() => ({}));
      setCount((c) => c + 1);
      setLast((body?.data?.event_id as string) ?? 'accepted');
    } catch {
      setLast('error');
    }
  }
  return (
    <div className="space-y-2 text-xs">
      <div className="flex flex-wrap gap-2">
        <button className="rounded border border-border-default px-2 py-1 hover:border-accent" onClick={() => send('sdk_page_view')}>Send SDK event</button>
        <button className="rounded border border-border-default px-2 py-1 hover:border-accent" onClick={() => send('webhook_order')}>Send webhook event</button>
      </div>
      <div className="text-text-muted">Simulated events ingested: {count}{last ? ` · last id: ${last}` : ''}</div>
    </div>
  );
}

export function App() {
  const [view, setView] = useState<View>('tenant');
  const env = getDemoEnv();

  return (
    <div className="min-h-screen p-6 space-y-5">
      <SyntheticDataBanner env={env} />
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border-default pb-4">
        <div>
          <h1 className="text-xl font-mono font-bold">Aether — Demo</h1>
          <p className="text-sm text-text-secondary">{DEMO_TENANT.name} · {DEMO_TENANT.plan} · synthetic data</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge>{env}</Badge>
          <button className={`rounded px-3 py-1 text-sm ${view === 'tenant' ? 'bg-accent text-surface-base' : 'border border-border-default'}`} onClick={() => setView('tenant')}>Tenant (Aether)</button>
          <button className={`rounded px-3 py-1 text-sm ${view === 'operator' ? 'bg-accent text-surface-base' : 'border border-border-default'}`} onClick={() => setView('operator')}>Operator (Kyber)</button>
        </div>
      </header>

      <p className="text-sm text-text-secondary">
        SDK or no SDK → connect Aether → generate graph intelligence → surface recommendations →
        make decisions → take action → observe outcomes → prove value.
      </p>

      {view === 'tenant' ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Step n={1} title="Ingestion — SDK and no-SDK paths">
            <div className="grid gap-1 text-xs">
              {INGESTION_PATHS.map((p) => (
                <div key={p.id} className="flex items-center justify-between rounded border border-border-default px-2 py-1">
                  <span><Badge variant={p.kind === 'SDK' ? 'success' : 'default'}>{p.kind}</Badge> {p.label} — <span className="text-text-muted">{p.detail}</span></span>
                  <Badge variant="success">{p.status}</Badge>
                </div>
              ))}
            </div>
            <div className="mt-3"><IngestionSimulator /></div>
          </Step>

          <Step n={2} title="Graph & Profile360">
            <div className="text-sm">{PROFILE360.entity}</div>
            <div className="text-xs text-text-muted">{PROFILE360.signals} signals · {PROFILE360.relationships} relationships · confidence {Math.round(PROFILE360.confidence * 100)}%</div>
            <div className="mt-2 flex flex-wrap gap-1">{PROFILE360.identities.map((i) => <Badge key={i}>{i}</Badge>)}</div>
          </Step>

          <Step n={3} title="Recommendation families">
            <div className="space-y-1 text-xs">
              {RECOMMENDATIONS.map((r) => (
                <div key={r.id} className="flex items-center justify-between rounded border border-border-default px-2 py-1">
                  <span><span className="font-mono text-text-muted">{r.family}</span> · {r.title}</span>
                  <Badge>{Math.round(r.confidence * 100)}%</Badge>
                </div>
              ))}
            </div>
          </Step>

          <Step n={4} title="OODA loop">
            <div className="grid gap-1 text-xs">
              {OODA.map((o) => <div key={o.step}><span className="font-medium">{o.step}:</span> <span className="text-text-muted">{o.detail}</span></div>)}
            </div>
          </Step>

          <Step n={5} title="Decisions, actions & dispatch">
            <div className="space-y-1 text-xs">
              {DECISIONS.map((d) => (
                <div key={d.id} className="rounded border border-border-default px-2 py-1">
                  {d.action} <Badge variant="success">{d.status}</Badge>
                  <span className="text-text-muted"> → dispatch {DISPATCHES.find((x) => x.decision === d.id)?.status ?? '—'}</span>
                </div>
              ))}
            </div>
          </Step>

          <Step n={6} title="Outcomes & ledger">
            <div className="space-y-1 text-xs">
              {OUTCOMES.map((o) => (
                <div key={o.id} className="flex justify-between rounded border border-border-default px-2 py-1">
                  <span><Badge variant="success">{o.label}</Badge> ${o.value}</span>
                  <span className="text-text-muted">Δconfidence +{o.confidence_delta}</span>
                </div>
              ))}
            </div>
          </Step>

          <Step n={7} title="Playbooks & ROI">
            <div className="space-y-1 text-xs">
              {PLAYBOOKS.map((p) => (
                <div key={p.id} className="flex justify-between rounded border border-border-default px-2 py-1">
                  <span>{p.name} — {p.runs} runs · {Math.round(p.success_rate * 100)}%</span>
                  <span className="text-text-muted">${p.observed_value.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </Step>

          <Step n={8} title="Value review & data quality">
            <div className="text-sm font-semibold">${VALUE_REVIEW.total.toLocaleString()} value created</div>
            <div className="text-xs text-text-muted">retained ${VALUE_REVIEW.retained_revenue.toLocaleString()} · expansion ${VALUE_REVIEW.expansion_revenue.toLocaleString()} · avoided ${VALUE_REVIEW.avoided_loss.toLocaleString()}</div>
            <div className="mt-2 text-xs">Intelligence quality: <Badge variant="success">{Math.round(DATA_QUALITY.overall * 100)}% {DATA_QUALITY.status}</Badge></div>
          </Step>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card><CardHeader><CardTitle>Tenant value health</CardTitle></CardHeader><CardContent className="text-xs space-y-1">
            <div>Tenant: {KYBER_VIEW.tenant}</div>
            <div>Health score: <Badge variant="success">{Math.round(KYBER_VIEW.health_score * 100)}%</Badge></div>
            <div>Expansion score: {Math.round(KYBER_VIEW.expansion_score * 100)}%</div>
            <div>Renewal risk: <Badge>{KYBER_VIEW.renewal_risk}</Badge></div>
          </CardContent></Card>
          <Card><CardHeader><CardTitle>Outcome & value</CardTitle></CardHeader><CardContent className="text-xs space-y-1">
            <div>Recommendations acted: {KYBER_VIEW.recommendations_acted}</div>
            <div>Value created: ${KYBER_VIEW.value_created_total.toLocaleString()}</div>
          </CardContent></Card>
          <Card><CardHeader><CardTitle>Intelligence quality</CardTitle></CardHeader><CardContent className="text-xs space-y-1">
            <div>Overall: <Badge variant="success">{Math.round(KYBER_VIEW.intelligence_quality * 100)}%</Badge></div>
            <div className="text-text-muted">Aggregate-only; no raw tenant-private payloads.</div>
          </CardContent></Card>
        </div>
      )}
    </div>
  );
}
