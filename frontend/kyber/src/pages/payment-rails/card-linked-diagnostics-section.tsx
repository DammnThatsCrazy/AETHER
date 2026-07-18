import { useState } from 'react';
import { Badge, Button, CapabilityStatePanel, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState } from '@aether/ui';
import { api } from '@kyber/lib/api';
import { isFeatureEnabled } from '@kyber/lib/featureFlags';

type AnyRecord = Record<string, unknown>;

const CARD_LINKED_COPY =
  'Card-linked economic observability — Aether never processes card payments, issues cards, or makes automated fraud/credit decisions. Top-up volume is never counted as card spend.';

function num(value: unknown): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function CountRow({ label, value, tone = 'default' }: {
  readonly label: string;
  readonly value: string | number;
  readonly tone?: 'default' | 'success' | 'warning' | 'danger';
}) {
  const toneClass =
    tone === 'success' ? 'text-success' : tone === 'warning' ? 'text-warning' : tone === 'danger' ? 'text-danger' : 'text-text-primary';
  return (
    <div className="flex justify-between">
      <span className="text-text-muted">{label}</span>
      <span className={toneClass}>{String(value)}</span>
    </div>
  );
}

function BreakdownCard({ title, entries }: {
  readonly title: string;
  readonly entries: AnyRecord;
}) {
  const keys = Object.keys(entries);
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="text-xs font-mono space-y-1">
        {keys.length === 0 ? (
          <div className="text-text-muted">No records observed.</div>
        ) : (
          keys.sort().map((key) => <CountRow key={key} label={key} value={String(entries[key])} />)
        )}
      </CardContent>
    </Card>
  );
}

export function CardLinkedDiagnosticsSection() {
  const enabled = isFeatureEnabled('enableCardLinkedPaymentRails');
  const [tenantId, setTenantId] = useState('');
  const [diagnostics, setDiagnostics] = useState<AnyRecord | null>(null);
  const [gate, setGate] = useState<AnyRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!tenantId.trim()) return;
    setLoading(true);
    setError(null);
    Promise.all([
      api.admin.kyber.cardLinkedDiagnostics(tenantId.trim()),
      api.admin.kyber.cardLinkedReleaseGate().catch(() => null),
    ])
      .then(([d, g]) => {
        setDiagnostics(d as AnyRecord);
        setGate(g as AnyRecord | null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  if (!enabled) {
    return (
      <Card>
        <CardHeader><CardTitle>Card-linked Payment Rails</CardTitle></CardHeader>
        <CardContent>
          <CapabilityStatePanel
            state="disabled"
            title="Card-linked observability is disabled"
            description='Enable the "enableCardLinkedPaymentRails" feature flag (VITE_FEATURE_FLAGS) to view card-linked diagnostics.'
          />
        </CardContent>
      </Card>
    );
  }

  const d = diagnostics ?? {};
  const paymentscan = (d.paymentscan ?? {}) as AnyRecord;
  const privacy = (d.privacy ?? {}) as AnyRecord;
  const warnings = (d.warnings ?? {}) as AnyRecord;
  const unmatched = (d.unmatched_events ?? {}) as AnyRecord;
  const basisSupport = (d.basis_support_by_source ?? {}) as AnyRecord;
  const gateChecks = (gate?.checks ?? []) as AnyRecord[];
  const mislabelCount = num(warnings.basis_mislabeling);
  const blockedPii = num(privacy.blocked_pii_attempts);
  const stale = paymentscan.stale === true;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>Card-linked Payment Rails</CardTitle>
          {gate && (
            <Badge variant={gate.passed ? 'success' : 'danger'}>
              {gate.passed ? 'release gate: passing' : 'release gate: FAILING'}
            </Badge>
          )}
        </div>
        <div className="text-[10px] text-text-muted font-mono mt-1">{CARD_LINKED_COPY}</div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          <input
            className="flex-1 rounded border border-border-default bg-surface-sunken px-2 py-1.5 text-xs font-mono text-text-primary"
            placeholder="Tenant ID"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') load(); }}
          />
          <Button size="sm" onClick={load} disabled={!tenantId.trim() || loading}>
            Load diagnostics
          </Button>
        </div>

        {loading && <LoadingState lines={4} />}
        {error && <EmptyState title="Unable to load card-linked diagnostics" description={error} />}

        {!loading && !error && diagnostics && (
          <>
            {stale && (
              <div className="rounded border border-warning/40 bg-warning/10 p-2 text-xs font-mono text-warning">
                PaymentScan catalog data is stale — benchmarks may not reflect current market state.
              </div>
            )}
            {mislabelCount > 0 && (
              <div className="rounded border border-warning/40 bg-warning/10 p-2 text-xs font-mono text-warning">
                {mislabelCount} basis mislabeling warning{mislabelCount === 1 ? '' : 's'} — sources claimed a basis
                they cannot prove (e.g. SDK-claimed spend downgraded to unknown).
              </div>
            )}
            {blockedPii > 0 && (
              <div className="rounded border border-danger/40 bg-danger/10 p-2 text-xs font-mono text-danger">
                {blockedPii} blocked-PII ingestion attempt{blockedPii === 1 ? '' : 's'} rejected (PAN/CVV/KYC/bank fields are never stored).
              </div>
            )}

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <Card>
                <CardHeader><CardTitle>PaymentScan freshness</CardTitle></CardHeader>
                <CardContent className="text-xs font-mono space-y-1">
                  <CountRow label="Card programs" value={num(paymentscan.card_program_count)} />
                  <CountRow label="Issuers" value={num(paymentscan.issuer_count)} />
                  <CountRow label="Networks" value={num(paymentscan.payment_network_count)} />
                  <CountRow label="Last sync" value={String(paymentscan.last_sync_at ?? 'never')} tone={stale ? 'warning' : 'default'} />
                  <CountRow label="Stale" value={stale ? 'yes' : 'no'} tone={stale ? 'warning' : 'success'} />
                  <div className="pt-1 text-[10px] text-text-muted">
                    Benchmarks are catalog/market intelligence — never user-level card spend.
                  </div>
                </CardContent>
              </Card>

              <BreakdownCard title="Coverage by source" entries={(d.by_source ?? {}) as AnyRecord} />
              <BreakdownCard title="Coverage by basis" entries={(d.by_basis ?? {}) as AnyRecord} />

              <Card>
                <CardHeader><CardTitle>Reconciliation</CardTitle></CardHeader>
                <CardContent className="text-xs font-mono space-y-1">
                  <CountRow label="Flows observed" value={num(d.flow_count)} />
                  {Object.entries((d.by_reconciliation_state ?? {}) as AnyRecord).map(([state, count]) => (
                    <CountRow key={state} label={state} value={String(count)} />
                  ))}
                  <CountRow
                    label="Conflicts"
                    value={num(d.reconciliation_conflicts)}
                    tone={num(d.reconciliation_conflicts) > 0 ? 'danger' : 'success'}
                  />
                  {Object.keys(unmatched).length > 0 && (
                    <div className="pt-1 text-[10px] text-warning">
                      Unmatched evidence: {Object.entries(unmatched).map(([k, v]) => `${k}=${String(v)}`).join(', ')}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle>Privacy gates</CardTitle></CardHeader>
                <CardContent className="text-xs font-mono space-y-1">
                  <CountRow label="Region-restricted records" value={num(privacy.region_restricted_records)} />
                  <CountRow label="Region suppressions" value={num(privacy.region_suppression_events)} tone={num(privacy.region_suppression_events) > 0 ? 'warning' : 'default'} />
                  <CountRow label="Consent suppressions" value={num(privacy.consent_suppression_events)} tone={num(privacy.consent_suppression_events) > 0 ? 'warning' : 'default'} />
                  <CountRow label="Blocked PII attempts" value={blockedPii} tone={blockedPii > 0 ? 'danger' : 'success'} />
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle>Basis support by source</CardTitle></CardHeader>
                <CardContent className="text-xs font-mono space-y-1">
                  {Object.keys(basisSupport).length === 0 ? (
                    <div className="text-text-muted">No sources observed.</div>
                  ) : (
                    Object.entries(basisSupport).map(([source, bases]) => (
                      <CountRow key={source} label={source} value={(bases as string[]).join(', ')} />
                    ))
                  )}
                  <div className="pt-1 text-[10px] text-text-muted">
                    On-chain proves top-up/funding; provider webhooks prove spend/settlement. Neither substitutes for the other.
                  </div>
                </CardContent>
              </Card>
            </div>

            {gateChecks.length > 0 && (
              <Card>
                <CardHeader><CardTitle>Release gate checks</CardTitle></CardHeader>
                <CardContent className="text-xs font-mono space-y-1">
                  {gateChecks.map((check) => (
                    <div key={String(check.name)} className="flex items-center justify-between">
                      <span className="text-text-muted">{String(check.name)}</span>
                      <Badge variant={check.passed ? 'success' : 'danger'}>
                        {check.passed ? 'pass' : 'fail'}
                      </Badge>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
