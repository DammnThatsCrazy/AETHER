import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, EvidenceDrawer, GlyphIcon, ScrollArea } from '@aether/ui';
import type { EvidenceRef } from '@aether/ui';
import { cn } from '@kyber/lib/utils';
import type { Profile360Section } from '@kyber/types';

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function fmtDur(secs: unknown): string {
  const s = typeof secs === 'number' ? secs : Number(secs ?? 0);
  if (!s || isNaN(s)) return '—';
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function fmtUsd(val: unknown): string {
  const n = typeof val === 'number' ? val : parseFloat(String(val ?? ''));
  if (!n || isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2 }).format(n);
}

// ── Sessions ──────────────────────────────────────────────────────────────────

function SessionRow({ s }: { s: Record<string, unknown> }) {
  const geo = asRec(s.geo ?? s.location);
  const ua = asRec(s.user_agent_parsed ?? s.user_agent);
  const isVpn = Boolean(s.vpn ?? s.is_vpn ?? geo.vpn ?? s.proxy ?? geo.proxy);
  const isTor = Boolean(s.tor ?? s.is_tor ?? geo.tor);
  const country = String(s.country ?? geo.country ?? geo.country_code ?? '—');
  const city = String(s.city ?? geo.city ?? '');
  const platform = String(s.platform ?? s.device_type ?? '—');
  const browser = String(s.browser ?? ua.browser ?? ua.browser_family ?? '—');
  const os = String(s.os ?? ua.os ?? ua.os_family ?? '—');
  const entryUrl = String(s.entry_url ?? s.landing_url ?? '');
  const campaign = String(s.utm_campaign ?? asRec(s.utm).campaign ?? s.campaign_id ?? '');

  return (
    <div className="py-2 px-3 border border-border-subtle rounded bg-surface-raised text-xs space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge size="sm">{platform}</Badge>
        <span className="text-text-secondary">{browser}</span>
        <span className="text-text-muted">·</span>
        <span className="text-text-secondary">{os}</span>
        <span className="text-text-muted">·</span>
        <span className="font-mono text-text-primary">{city ? `${city}, ${country}` : country}</span>
        {isVpn && <Badge variant="warning" size="sm">VPN/Proxy</Badge>}
        {isTor && <Badge variant="danger" size="sm">Tor</Badge>}
        <span className="ml-auto text-text-muted">{fmtDur(s.duration_seconds ?? s.duration)}</span>
        {(s.page_views ?? s.pages) !== undefined && (
          <span className="text-text-muted">{String(s.page_views ?? s.pages)} pages</span>
        )}
      </div>
      {(entryUrl || campaign) && (
        <div className="flex flex-wrap gap-3 text-[10px] text-text-muted">
          {entryUrl && <span className="font-mono truncate max-w-xs">{entryUrl}</span>}
          {campaign && <span className="text-accent">↳ {campaign}</span>}
        </div>
      )}
    </div>
  );
}

export function Profile360SessionsPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'sessions-overview');
  const data = asRec(section?.data);
  const sessions = Array.isArray(data.sessions) ? data.sessions : [];
  const devices = Array.isArray(data.devices) ? data.devices : [];

  return (
    <div className="space-y-4 pt-2">
      {section?.metrics && section.metrics.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
          {section.metrics.map(m => (
            <div key={m.id} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">{m.label}</div>
              <div className={cn('mt-1 text-base font-semibold font-mono',
                m.tone === 'good' ? 'text-success' : m.tone === 'warning' ? 'text-warning' : m.tone === 'danger' ? 'text-danger' : 'text-text-primary'
              )}>{m.value}</div>
            </div>
          ))}
        </div>
      )}

      <Card>
        <CardHeader><CardTitle>Recent sessions ({sessions.length})</CardTitle></CardHeader>
        <CardContent>
          {sessions.length === 0 ? (
            <EmptyState title="No sessions" description="No session data recorded for this entity." />
          ) : (
            <ScrollArea maxHeight="420px">
              <div className="space-y-1.5">
                {sessions.map((s, i) => (
                  <SessionRow key={String(asRec(s).session_id ?? asRec(s).id ?? i)} s={asRec(s)} />
                ))}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>

      {devices.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Device fingerprints ({devices.length})</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-2">
              {devices.map((d, i) => {
                const dr = asRec(d);
                const did = String(dr.device_id ?? dr.id ?? i);
                const confidence = typeof dr.confidence === 'number' ? Math.round(dr.confidence * 100) : null;
                return (
                  <div key={did} className="flex items-center gap-3 p-3 border border-border-subtle rounded bg-surface-raised text-xs">
                    <div className="flex-1 min-w-0">
                      <div className="font-mono text-text-primary truncate text-[10px]">{did}</div>
                      <div className="text-text-muted mt-0.5">
                        {String(dr.device_type ?? dr.type ?? 'device')}
                        {dr.os ? ` · ${String(dr.os)}` : ''}
                        {dr.browser ? ` · ${String(dr.browser)}` : ''}
                      </div>
                    </div>
                    {confidence !== null && (
                      <Badge variant={confidence > 80 ? 'success' : confidence > 50 ? 'warning' : 'default'} size="sm">
                        {`${confidence}%`}
                      </Badge>
                    )}
                    {Boolean(dr.deterministic) && <Badge variant="accent" size="sm">det.</Badge>}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Journeys ──────────────────────────────────────────────────────────────────

function JourneyCard({ j }: { j: Record<string, unknown> }) {
  const steps = Array.isArray(j.steps) ? j.steps : [];
  const completed = Boolean(j.completed ?? j.converted);
  const abandoned = Boolean(j.abandoned ?? j.dropped);
  const campaign = String(j.campaign_id ?? j.campaign_name ?? j.campaign ?? '');

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between w-full">
          <span className="text-xs font-mono text-text-muted truncate max-w-[200px]">
            {String(j.journey_id ?? j.id ?? 'journey')}
          </span>
          <div className="flex items-center gap-1">
            {completed && <Badge variant="success" size="sm">converted</Badge>}
            {abandoned && <Badge variant="warning" size="sm">abandoned</Badge>}
            {campaign && <Badge variant="info" size="sm">{campaign}</Badge>}
          </div>
        </div>
      </CardHeader>
      {steps.length > 0 && (
        <CardContent>
          <div className="flex items-start gap-0.5 overflow-x-auto pb-1">
            {steps.map((step, idx) => {
              const sr = asRec(step);
              const dropped = Boolean(sr.dropped ?? sr.drop_off ?? sr.exit);
              const dropRate = typeof sr.drop_rate === 'number' ? sr.drop_rate : typeof sr.dropoff_rate === 'number' ? sr.dropoff_rate : null;
              return (
                <div key={idx} className="flex items-center gap-0.5 shrink-0">
                  <div className={cn(
                    'flex flex-col items-center rounded p-1.5 border text-[10px] min-w-[72px]',
                    dropped ? 'border-warning/40 bg-warning/5 text-warning' : 'border-border-subtle bg-surface-raised text-text-primary',
                  )}>
                    <span className="font-mono text-text-muted">{idx + 1}</span>
                    <span className="font-medium truncate max-w-[64px]">
                      {String(sr.name ?? sr.event_type ?? sr.step_name ?? `step ${idx + 1}`)}
                    </span>
                    {dropRate !== null && (
                      <span className={cn('text-[9px]', dropRate > 0.3 ? 'text-danger' : 'text-text-muted')}>
                        ↓{Math.round(dropRate * 100)}%
                      </span>
                    )}
                  </div>
                  {idx < steps.length - 1 && <span className="text-text-muted text-[10px]">→</span>}
                </div>
              );
            })}
          </div>
        </CardContent>
      )}
    </Card>
  );
}

export function Profile360JourneysPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'journeys-overview');
  const data = asRec(section?.data);
  const journeys = Array.isArray(data.journeys) ? data.journeys : [];

  return (
    <div className="space-y-4 pt-2">
      {section?.metrics && section.metrics.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-7 gap-2">
          {section.metrics.map(m => (
            <div key={m.id} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">{m.label}</div>
              <div className={cn('mt-1 text-base font-semibold font-mono',
                m.tone === 'good' ? 'text-success' : m.tone === 'warning' ? 'text-warning' : m.tone === 'danger' ? 'text-danger' : 'text-text-primary'
              )}>{m.value}{m.unit ?? ''}</div>
            </div>
          ))}
        </div>
      )}
      {journeys.length === 0 ? (
        <EmptyState title="No journeys" description="No cross-session journey chains have been recorded." />
      ) : (
        <ScrollArea maxHeight="540px">
          <div className="space-y-2">
            {journeys.map((j, i) => (
              <JourneyCard key={String(asRec(j).journey_id ?? asRec(j).id ?? i)} j={asRec(j)} />
            ))}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}

// ── Wallets ───────────────────────────────────────────────────────────────────

function WalletCard({ w }: { w: Record<string, unknown> }) {
  const addr = String(w.wallet_address ?? w.address ?? w.id ?? '—');
  const chain = String(w.chain ?? w.network ?? '');
  const totalUsd = fmtUsd(w.total_usd ?? w.balance_usd ?? w.total_balance_usd);
  const riskScore = typeof w.risk_score === 'number' ? w.risk_score : null;
  const loyaltyTier = String(w.loyalty_tier ?? w.tier ?? '');
  const txs: unknown[] = Array.isArray(w.recent_transactions) ? w.recent_transactions : Array.isArray(w.transactions) ? w.transactions : [];
  const tokens: unknown[] = Array.isArray(w.token_balances) ? w.token_balances : Array.isArray(w.balances) ? w.balances : [];
  const protocols: unknown[] = Array.isArray(w.protocol_interactions) ? w.protocol_interactions : Array.isArray(w.protocols) ? w.protocols : [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2 w-full">
          <div className="min-w-0">
            <code className="text-[10px] text-text-muted font-mono break-all">{addr}</code>
            <div className="flex flex-wrap items-center gap-1 mt-1">
              {chain && <Badge size="sm">{chain}</Badge>}
              {loyaltyTier && <Badge variant="accent" size="sm">{loyaltyTier}</Badge>}
              {riskScore !== null && (
                <Badge variant={riskScore > 0.6 ? 'danger' : riskScore > 0.3 ? 'warning' : 'success'} size="sm">
                  {`risk ${(riskScore * 100).toFixed(0)}%`}
                </Badge>
              )}
            </div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-sm font-semibold font-mono text-text-primary">{totalUsd}</div>
            <div className="text-[10px] text-text-muted">{txs.length} recent txs</div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {tokens.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Token balances</p>
            <div className="flex flex-wrap gap-1">
              {tokens.slice(0, 8).map((t, i) => {
                const tr = asRec(t);
                const sym = String(tr.symbol ?? tr.token_symbol ?? tr.token ?? '');
                const usd = fmtUsd(tr.value_usd ?? tr.balance_usd);
                return (
                  <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border-subtle bg-surface-overlay text-[10px]">
                    <span className="font-mono text-text-primary">{sym}</span>
                    {usd !== '—' && <span className="text-text-muted">{usd}</span>}
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {txs.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Recent transactions</p>
            <div className="space-y-1">
              {txs.slice(0, 5).map((tx, i) => {
                const txr = asRec(tx);
                const type = String(txr.type ?? txr.tx_type ?? txr.interaction_type ?? 'transfer');
                const amt = fmtUsd(txr.amount_usd ?? txr.value_usd);
                const hash = String(txr.hash ?? txr.tx_hash ?? '');
                return (
                  <div key={i} className="flex items-center justify-between text-[10px] py-1 border-b border-border-subtle last:border-0">
                    <div className="flex items-center gap-2">
                      <Badge size="sm">{type}</Badge>
                      {hash && <code className="text-text-muted font-mono">{hash.slice(0, 8)}…</code>}
                    </div>
                    <span className="font-mono text-text-primary">{amt}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {protocols.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Protocol interactions</p>
            <div className="flex flex-wrap gap-1">
              {protocols.slice(0, 6).map((p, i) => {
                const pr = asRec(p);
                return (
                  <Badge key={i} variant="info" size="sm">
                    {String(pr.protocol_name ?? pr.name ?? pr.protocol ?? pr)}
                  </Badge>
                );
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function Profile360WalletsPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'wallets-overview');
  const data = asRec(section?.data);
  const wallets = Array.isArray(data.wallets) ? data.wallets : [];

  return (
    <div className="space-y-4 pt-2">
      {section?.metrics && section.metrics.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {section.metrics.map(m => (
            <div key={m.id} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">{m.label}</div>
              <div className="mt-1 text-base font-semibold font-mono text-text-primary">{m.value}</div>
            </div>
          ))}
        </div>
      )}
      {wallets.length === 0 ? (
        <EmptyState title="No wallets" description="No Web3 wallets have been linked to this entity." />
      ) : (
        <div className="space-y-3">
          {wallets.map((w, i) => {
            const wr = asRec(w);
            return <WalletCard key={String(wr.wallet_address ?? wr.address ?? wr.id ?? i)} w={wr} />;
          })}
        </div>
      )}
    </div>
  );
}

// ── Behavioral ────────────────────────────────────────────────────────────────

function BehavioralSignalRow({ sig, index }: { sig: unknown; index: number }) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const sr = asRec(sig);
  const family = String(sr.family ?? sr.signal_family ?? 'other');
  const severity = String(sr.severity ?? sr.level ?? 'info');
  const explanation = String(sr.explanation ?? sr.reason ?? sr.description ?? '');
  const score = typeof sr.score === 'number' ? sr.score : null;
  const signalName = String(sr.name ?? sr.signal_type ?? sr.type ?? '');
  const evidenceRefs = Array.isArray(sr.evidence_refs) ? sr.evidence_refs as EvidenceRef[] : [];

  return (
    <div key={String(sr.id ?? index)} className="border border-border-subtle rounded bg-surface-raised">
      <div className="p-3 space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge size="sm">{family}</Badge>
          <Badge
            variant={severity === 'critical' || severity === 'high' ? 'danger' : severity === 'medium' ? 'warning' : 'default'}
            size="sm"
          >{severity}</Badge>
          <span className="text-xs text-text-primary font-medium">{signalName}</span>
          {score !== null && (
            <span className="text-xs font-mono text-text-secondary">{score.toFixed(3)}</span>
          )}
          {evidenceRefs.length > 0 && (
            <button
              onClick={() => setEvidenceOpen(o => !o)}
              className="ml-auto flex items-center gap-1 text-[10px] font-mono text-text-muted hover:text-accent transition-colors"
            >
              <GlyphIcon glyph={evidenceOpen ? '[-]' : '[>]'} className="text-[10px]" />
              {evidenceOpen ? 'hide' : 'evidence'}
            </button>
          )}
        </div>
        {explanation && <p className="text-xs text-text-secondary">{explanation}</p>}
      </div>
      {evidenceRefs.length > 0 && (
        <EvidenceDrawer
          signalName={signalName}
          evidence={evidenceRefs}
          open={evidenceOpen}
          onClose={() => setEvidenceOpen(false)}
        />
      )}
    </div>
  );
}

export function Profile360BehavioralPanel({ sections, window: _window }: { readonly sections: readonly Profile360Section[]; readonly window?: string }) {
  const section = sections.find(s => s.id === 'behavioral-signals');
  const data = asRec(section?.data);
  const signals = Array.isArray(data.signals) ? data.signals : [];
  const familyCounts = asRec(data.family_counts);

  return (
    <div className="space-y-4 pt-2">
      {section?.metrics && section.metrics.length > 0 && (
        <div className="grid grid-cols-4 gap-2">
          {section.metrics.map(m => (
            <div key={m.id} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">{m.label}</div>
              <div className={cn('mt-1 text-base font-semibold font-mono',
                m.tone === 'good' ? 'text-success' : m.tone === 'warning' ? 'text-warning' : m.tone === 'danger' ? 'text-danger' : 'text-text-primary'
              )}>{m.value}{m.unit ?? ''}</div>
            </div>
          ))}
        </div>
      )}

      {Object.keys(familyCounts).length > 0 && (
        <Card>
          <CardHeader><CardTitle>Signal families</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(familyCounts).map(([fam, count]) => (
                <div key={fam} className="flex items-center gap-1.5 px-2.5 py-1 rounded border border-border-subtle bg-surface-raised text-xs">
                  <span className="text-text-primary">{fam}</span>
                  <Badge size="sm">{String(count)}</Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {signals.length === 0 ? (
        <EmptyState title="No behavioral signals" description="No anomalous behavioral signals have been detected for this entity." />
      ) : (
        <Card>
          <CardHeader><CardTitle>Signals ({signals.length})</CardTitle></CardHeader>
          <CardContent>
            <ScrollArea maxHeight="440px">
              <div className="space-y-2">
                {signals.map((sig, i) => (
                  <BehavioralSignalRow key={String(asRec(sig).id ?? i)} sig={sig} index={i} />
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Attribution ───────────────────────────────────────────────────────────────

export function Profile360AttributionPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'attribution-journey');
  const data = asRec(section?.data);
  const touchpoints = Array.isArray(data.touchpoints) ? data.touchpoints : [];
  const channelCredit = asRec(data.channel_credit);
  const firstCampaign = data.first_campaign != null ? asRec(data.first_campaign) : null;
  const campaignHistory: Record<string, unknown>[] = Array.isArray(data.campaign_history) ? data.campaign_history.map(asRec) : [];
  const attributedConversions: Record<string, unknown>[] = Array.isArray(data.attributed_conversions) ? data.attributed_conversions.map(asRec) : [];
  const attributedRevenue = typeof data.attributed_revenue === 'number' ? data.attributed_revenue : null;
  const attributedRevenueNet = typeof data.attributed_revenue_net === 'number' ? data.attributed_revenue_net : null;

  const maxCredit = Math.max(...Object.values(channelCredit).map(v => typeof v === 'number' ? v : 0), 0.001);

  return (
    <div className="space-y-4 pt-2">
      {section?.metrics && section.metrics.length > 0 && (
        <div className="grid grid-cols-4 gap-2">
          {section.metrics.map(m => (
            <div key={m.id} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">{m.label}</div>
              <div className={cn('mt-1 text-base font-semibold font-mono',
                m.tone === 'good' ? 'text-success' : 'text-text-primary'
              )}>{m.value}</div>
            </div>
          ))}
        </div>
      )}

      {(firstCampaign != null || attributedRevenue != null || attributedConversions.length > 0 || campaignHistory.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle>Acquisition</CardTitle>
            <div className="flex gap-2 mt-1">
              <Link to="/measurement/journeys" className="text-xs text-accent hover:underline">Journey Explorer →</Link>
              <Link to="/measurement/campaigns" className="text-xs text-accent hover:underline">Campaign Intelligence →</Link>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {(attributedRevenue != null || attributedRevenueNet != null) && (
              <div className="grid grid-cols-2 gap-2">
                {attributedRevenue != null && (
                  <div className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
                    <div className="text-[10px] uppercase tracking-wide text-text-muted">Attributed revenue (gross)</div>
                    <div className="mt-1 text-base font-semibold font-mono text-text-primary">{fmtUsd(attributedRevenue)}</div>
                  </div>
                )}
                {attributedRevenueNet != null && (
                  <div className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
                    <div className="text-[10px] uppercase tracking-wide text-text-muted">Attributed revenue (net)</div>
                    <div className="mt-1 text-base font-semibold font-mono text-text-primary">{fmtUsd(attributedRevenueNet)}</div>
                  </div>
                )}
              </div>
            )}
            {firstCampaign != null && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">First campaign</div>
                <div className="flex flex-wrap items-center gap-2 px-3 py-2 rounded border border-border-subtle bg-surface-raised text-xs">
                  <span className="font-mono text-text-primary">{String(firstCampaign.campaign_id ?? firstCampaign.id ?? '—').slice(0, 12)}</span>
                  {!!firstCampaign.name && <span className="text-text-secondary">{String(firstCampaign.name)}</span>}
                  {!!firstCampaign.channel && <Badge size="sm">{String(firstCampaign.channel)}</Badge>}
                  {!!firstCampaign.first_touch_at && (
                    <span className="font-mono text-text-muted">{new Date(String(firstCampaign.first_touch_at)).toLocaleDateString()}</span>
                  )}
                </div>
              </div>
            )}
            {campaignHistory.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Campaign history ({campaignHistory.length})</div>
                <ScrollArea maxHeight="200px">
                  <div className="space-y-1">
                    {campaignHistory.map((c, i) => (
                      <div key={String(c.campaign_id ?? i)} className="flex flex-wrap items-center gap-2 px-2 py-1.5 rounded border border-border-subtle bg-surface-raised text-xs">
                        <span className="font-mono text-text-muted">{String(c.campaign_id ?? '—').slice(0, 10)}…</span>
                        {!!c.name && <span className="text-text-secondary truncate max-w-[120px]">{String(c.name)}</span>}
                        {!!c.channel && <Badge size="sm">{String(c.channel)}</Badge>}
                        {c.attributed_revenue != null && <span className="font-mono text-text-primary ml-auto">{fmtUsd(c.attributed_revenue)}</span>}
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            )}
            {attributedConversions.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-text-muted mb-1">Attributed conversions ({attributedConversions.length})</div>
                <ScrollArea maxHeight="200px">
                  <div className="space-y-1">
                    {attributedConversions.map((cv, i) => (
                      <div key={String(cv.conversion_id ?? i)} className="flex flex-wrap items-center gap-2 px-2 py-1.5 rounded border border-border-subtle bg-surface-raised text-xs">
                        <span className="font-mono text-text-muted">{String(cv.conversion_id ?? '—').slice(0, 8)}…</span>
                        {!!cv.conversion_type && <Badge size="sm">{String(cv.conversion_type)}</Badge>}
                        {cv.gross_value != null && <span className="font-mono text-text-primary">{fmtUsd(cv.gross_value)}</span>}
                        {!!cv.occurred_at && <span className="font-mono text-text-muted ml-auto">{new Date(String(cv.occurred_at)).toLocaleDateString()}</span>}
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {Object.keys(channelCredit).length > 0 && (
        <Card>
          <CardHeader><CardTitle>Attribution credit by channel</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {Object.entries(channelCredit)
                .sort(([, a], [, b]) => (typeof b === 'number' ? b : 0) - (typeof a === 'number' ? a : 0))
                .map(([channel, credit]) => {
                  const val = typeof credit === 'number' ? credit : 0;
                  const pct = Math.round((val / maxCredit) * 100);
                  return (
                    <div key={channel} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-text-primary">{channel}</span>
                        <span className="font-mono text-text-secondary">{val.toFixed(3)}</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-surface-overlay overflow-hidden">
                        <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
            </div>
          </CardContent>
        </Card>
      )}

      {touchpoints.length === 0 ? (
        <EmptyState title="No attribution data" description="No touchpoints have been recorded for this entity." />
      ) : (
        <Card>
          <CardHeader><CardTitle>Touchpoint journey ({touchpoints.length})</CardTitle></CardHeader>
          <CardContent>
            <ScrollArea maxHeight="440px">
              <div className="space-y-1.5">
                {touchpoints.map((tp, i) => {
                  const tpr = asRec(tp);
                  const channel = String(tpr.channel ?? tpr.source ?? 'direct');
                  const campaign = String(tpr.campaign ?? tpr.campaign_id ?? tpr.utm_campaign ?? '');
                  const event = String(tpr.event_type ?? tpr.type ?? '');
                  const credit = typeof tpr.credit === 'number' ? tpr.credit : typeof tpr.attribution_credit === 'number' ? tpr.attribution_credit : null;
                  const isConversion = Boolean(tpr.is_conversion ?? tpr.converted);
                  const ts = String(tpr.timestamp ?? tpr.created_at ?? '');
                  return (
                    <div key={i} className="flex items-start gap-3 py-2 px-3 rounded border border-border-subtle bg-surface-raised text-xs">
                      <div className="flex-1 min-w-0 space-y-0.5">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge size="sm">{channel}</Badge>
                          {event && <span className="text-text-secondary">{event}</span>}
                          {campaign && <span className="text-accent text-[10px]">{campaign}</span>}
                          {isConversion && <Badge variant="success" size="sm">conversion</Badge>}
                        </div>
                        {ts && <div className="text-[10px] font-mono text-text-muted">{ts}</div>}
                      </div>
                      {credit !== null && (
                        <span className="font-mono text-text-secondary shrink-0">{credit.toFixed(3)}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Cluster ───────────────────────────────────────────────────────────────────

export function Profile360ClusterPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'cluster-overview');
  const data = asRec(section?.data);
  const clusters = Array.isArray(data.all_clusters) ? data.all_clusters : [];
  const primary = asRec(data.cluster);

  return (
    <div className="space-y-4 pt-2">
      {section?.metrics && section.metrics.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {section.metrics.map(m => (
            <div key={m.id} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">{m.label}</div>
              <div className={cn('mt-1 text-base font-semibold font-mono',
                m.tone === 'good' ? 'text-success' : m.tone === 'warning' ? 'text-warning' : m.tone === 'danger' ? 'text-danger' : 'text-text-primary'
              )}>{m.value}</div>
            </div>
          ))}
        </div>
      )}
      {Boolean(primary.cluster_id) && (
        <Card>
          <CardHeader><CardTitle>Primary cluster</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-1.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-text-muted">Cluster ID</span>
                <code className="font-mono text-text-primary">{String(primary.cluster_id)}</code>
              </div>
              {primary.confidence !== undefined && (
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Confidence</span>
                  <Badge variant={Number(primary.confidence) > 0.8 ? 'success' : Number(primary.confidence) > 0.5 ? 'warning' : 'default'} size="sm">
                    {`${Math.round(Number(primary.confidence) * 100)}%`}
                  </Badge>
                </div>
              )}
              {primary.member_count !== undefined && (
                <div className="flex items-center justify-between">
                  <span className="text-text-muted">Members</span>
                  <span className="font-mono text-text-primary">{String(primary.member_count)}</span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}
      {clusters.length === 0 && !primary.cluster_id ? (
        <EmptyState title="No cluster membership" description="This entity has not been assigned to an identity cluster. Source: identity resolution graph." />
      ) : (
        clusters.length > 0 && (
          <Card>
            <CardHeader><CardTitle>All clusters ({clusters.length})</CardTitle></CardHeader>
            <CardContent>
              <ScrollArea maxHeight="360px">
                <div className="space-y-2">
                  {clusters.map((c, i) => {
                    const cr = asRec(c);
                    return (
                      <div key={String(cr.cluster_id ?? i)} className="flex items-center justify-between py-2 px-3 border border-border-subtle rounded bg-surface-raised text-xs">
                        <code className="font-mono text-text-muted truncate">{String(cr.cluster_id ?? cr.id ?? '—')}</code>
                        <div className="flex items-center gap-2">
                          {cr.confidence !== undefined && <Badge size="sm">{`${Math.round(Number(cr.confidence) * 100)}%`}</Badge>}
                          {Boolean(cr.is_primary) && <Badge variant="accent" size="sm">primary</Badge>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        )
      )}
    </div>
  );
}

// ── Agents ────────────────────────────────────────────────────────────────────

export function Profile360AgentsPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'agents-overview');
  const data = asRec(section?.data);
  const agents = Array.isArray(data.items) ? data.items : Array.isArray(data.agents) ? data.agents : [];
  const delegations = Array.isArray(data.delegations) ? data.delegations : [];

  return (
    <div className="space-y-4 pt-2">
      {section?.metrics && section.metrics.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {section.metrics.map(m => (
            <div key={m.id} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">{m.label}</div>
              <div className="mt-1 text-base font-semibold font-mono text-text-primary">{m.value}</div>
            </div>
          ))}
        </div>
      )}
      {agents.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Agents ({agents.length})</CardTitle></CardHeader>
          <CardContent>
            <ScrollArea maxHeight="320px">
              <div className="space-y-2">
                {agents.map((a, i) => {
                  const ar = asRec(a);
                  const status = String(ar.status ?? 'unknown');
                  const exCount = typeof ar.execution_count === 'number' ? ar.execution_count : null;
                  return (
                    <div key={String(ar.agent_id ?? ar.id ?? i)} className="flex items-center justify-between py-2 px-3 border border-border-subtle rounded bg-surface-raised text-xs">
                      <div className="min-w-0">
                        <div className="font-medium text-text-primary truncate">{String(ar.name ?? ar.agent_name ?? ar.agent_id ?? '—')}</div>
                        <div className="text-text-muted text-[10px] font-mono truncate">{String(ar.agent_id ?? ar.id ?? '')}</div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {exCount !== null && <span className="text-text-muted">{exCount} execs</span>}
                        <Badge variant={status === 'active' ? 'success' : status === 'error' ? 'danger' : 'default'} size="sm">{status}</Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}
      {delegations.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Delegations ({delegations.length})</CardTitle></CardHeader>
          <CardContent>
            <ScrollArea maxHeight="280px">
              <div className="space-y-2">
                {delegations.map((d, i) => {
                  const dr = asRec(d);
                  const active = Boolean(dr.active ?? dr.is_active);
                  return (
                    <div key={String(dr.delegation_id ?? dr.id ?? i)} className="flex items-center justify-between py-1.5 px-3 border border-border-subtle rounded bg-surface-raised text-xs">
                      <div className="text-text-muted font-mono truncate text-[10px]">{String(dr.delegation_id ?? dr.id ?? '—')}</div>
                      <div className="flex items-center gap-1.5">
                        <Badge size="sm">{String(dr.role ?? dr.type ?? 'delegation')}</Badge>
                        <Badge variant={active ? 'success' : 'default'} size="sm">{active ? 'active' : 'expired'}</Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}
      {agents.length === 0 && delegations.length === 0 && (
        <EmptyState title="No agents or delegations" description="No agent profiles or delegation relationships have been recorded for this entity." />
      )}
    </div>
  );
}

// ── Consent ───────────────────────────────────────────────────────────────────

export function Profile360ConsentPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'consent-overview');
  const data = asRec(section?.data);
  const consentStatus = String(data.consent_status ?? 'unknown');
  const eligibility = String(data.activation_eligibility ?? 'observe_only');
  const allowedUseCases: string[] = Array.isArray(data.allowed_use_cases) ? data.allowed_use_cases.map(String) : [];
  const restrictedUseCases: string[] = Array.isArray(data.restricted_use_cases) ? data.restricted_use_cases.map(String) : [];
  const blockedUseCases: string[] = Array.isArray(data.blocked_use_cases) ? data.blocked_use_cases.map(String) : [];
  const dsrState = String(data.dsr_state ?? 'none');
  const retentionStatus = String(data.retention_status ?? 'unknown');

  const consentVariant = consentStatus === 'granted' ? 'success' : consentStatus === 'revoked' ? 'danger' : consentStatus === 'restricted' || consentStatus === 'partial' ? 'warning' : 'default';
  const eligibilityVariant = eligibility === 'allowed' ? 'success' : eligibility === 'blocked' ? 'danger' : eligibility === 'restricted' ? 'warning' : 'default';

  return (
    <div className="space-y-4 pt-2">
      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardHeader><CardTitle>Consent status</CardTitle></CardHeader>
          <CardContent>
            <Badge variant={consentVariant} size="md">{consentStatus}</Badge>
            {Boolean(data.last_consent_update) && (
              <p className="text-[10px] text-text-muted mt-2 font-mono">Updated: {String(data.last_consent_update)}</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Activation eligibility</CardTitle></CardHeader>
          <CardContent>
            <Badge variant={eligibilityVariant} size="md">{eligibility}</Badge>
            <p className="text-[10px] text-text-muted mt-2">Retention: {retentionStatus} · DSR: {dsrState}</p>
          </CardContent>
        </Card>
      </div>
      {(allowedUseCases.length > 0 || restrictedUseCases.length > 0 || blockedUseCases.length > 0) ? (
        <Card>
          <CardHeader><CardTitle>Use case permissions</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {allowedUseCases.length > 0 && (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-success mb-1">Allowed</p>
                <div className="flex flex-wrap gap-1">{allowedUseCases.map(u => <Badge key={u} variant="success" size="sm">{u}</Badge>)}</div>
              </div>
            )}
            {restrictedUseCases.length > 0 && (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-warning mb-1">Restricted</p>
                <div className="flex flex-wrap gap-1">{restrictedUseCases.map(u => <Badge key={u} variant="warning" size="sm">{u}</Badge>)}</div>
              </div>
            )}
            {blockedUseCases.length > 0 && (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-danger mb-1">Blocked</p>
                <div className="flex flex-wrap gap-1">{blockedUseCases.map(u => <Badge key={u} variant="danger" size="sm">{u}</Badge>)}</div>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <EmptyState title="No consent data" description="Consent records are unavailable for this entity. Source: consent service." />
      )}
    </div>
  );
}

// ── Quality ───────────────────────────────────────────────────────────────────

export function Profile360QualityPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'quality-overview');
  const data = asRec(section?.data);
  const readiness = String(data.readiness_status ?? 'unknown');
  const scoresObj = asRec(data.scores);
  const scores = [
    { label: 'Completeness', value: data.completeness ?? scoresObj.completeness },
    { label: 'Freshness', value: data.freshness ?? scoresObj.freshness },
    { label: 'Confidence', value: data.confidence ?? scoresObj.confidence },
    { label: 'Source coverage', value: data.source_coverage ?? scoresObj.source_coverage },
    { label: 'Relationship density', value: data.relationship_density ?? scoresObj.relationship_density },
    { label: 'Journey coverage', value: data.journey_coverage ?? scoresObj.journey_coverage },
    { label: 'Attribution coverage', value: data.attribution_coverage ?? scoresObj.attribution_coverage },
    { label: 'Consent coverage', value: data.consent_coverage ?? scoresObj.consent_coverage },
    { label: 'Provenance coverage', value: data.provenance_coverage ?? scoresObj.provenance_coverage },
  ].filter(s => s.value !== undefined && s.value !== null);

  const readinessVariant = readiness === 'release_grade' || readiness === 'strong' ? 'success' : readiness === 'usable' ? 'warning' : readiness === 'empty' ? 'danger' : 'default';
  const missingDims: string[] = Array.isArray(data.missing_dimensions) ? data.missing_dimensions.map(String) : [];
  const staleDims: string[] = Array.isArray(data.stale_dimensions) ? data.stale_dimensions.map(String) : [];

  return (
    <div className="space-y-4 pt-2">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between w-full">
            <CardTitle>Profile readiness</CardTitle>
            <Badge variant={readinessVariant}>{readiness.replace('_', ' ')}</Badge>
          </div>
        </CardHeader>
        {scores.length > 0 && (
          <CardContent>
            <div className="space-y-2">
              {scores.map(({ label, value }) => {
                const pct = Math.round(Number(value) * 100);
                return (
                  <div key={label} className="space-y-0.5">
                    <div className="flex justify-between text-xs">
                      <span className="text-text-secondary">{label}</span>
                      <span className="font-mono text-text-primary">{pct}%</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-surface-overlay overflow-hidden">
                      <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        )}
      </Card>
      {(missingDims.length > 0 || staleDims.length > 0) && (
        <Card>
          <CardHeader><CardTitle>Gaps</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {missingDims.length > 0 && (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-danger mb-1">Missing dimensions</p>
                <div className="flex flex-wrap gap-1">{missingDims.map(d => <Badge key={d} variant="danger" size="sm">{d}</Badge>)}</div>
              </div>
            )}
            {staleDims.length > 0 && (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-warning mb-1">Stale dimensions</p>
                <div className="flex flex-wrap gap-1">{staleDims.map(d => <Badge key={d} variant="warning" size="sm">{d}</Badge>)}</div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
      {scores.length === 0 && missingDims.length === 0 && (
        <EmptyState title="No quality data" description="Profile quality has not been computed yet. Source: quality scorer." />
      )}
    </div>
  );
}

// ── Recommendations ───────────────────────────────────────────────────────────

export function Profile360RecommendationsPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'recommendations-overview');
  const data = asRec(section?.data);
  const items: unknown[] = Array.isArray(data.items) ? data.items : [];

  return (
    <div className="space-y-4 pt-2">
      {section?.metrics && section.metrics.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {section.metrics.map(m => (
            <div key={m.id} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">{m.label}</div>
              <div className="mt-1 text-base font-semibold font-mono text-text-primary">{m.value}</div>
            </div>
          ))}
        </div>
      )}
      {items.length === 0 ? (
        <EmptyState title="No recommendations" description="No intelligence recommendations have been generated for this entity." />
      ) : (
        <div className="space-y-2">
          {items.map((item, i) => {
            const ir = asRec(item);
            const status = String(ir.status ?? 'pending');
            const confidence = typeof ir.confidence === 'number' ? Math.round(ir.confidence * 100) : null;
            const eligibility = String(ir.activation_eligibility ?? '');
            return (
              <Card key={String(ir.recommendation_id ?? ir.id ?? i)}>
                <CardContent className="pt-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-text-primary">{String(ir.title ?? ir.recommendation_type ?? 'Recommendation')}</div>
                      {Boolean(ir.rationale) && <p className="text-xs text-text-secondary mt-1">{String(ir.rationale)}</p>}
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      {confidence !== null && <Badge variant={confidence > 70 ? 'success' : 'warning'} size="sm">{confidence}%</Badge>}
                      <Badge variant={status === 'active' ? 'success' : status === 'blocked' ? 'danger' : 'default'} size="sm">{status}</Badge>
                      {eligibility && eligibility !== 'allowed' && (
                        <Badge variant={eligibility === 'blocked' ? 'danger' : 'warning'} size="sm">{eligibility}</Badge>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Outcomes ──────────────────────────────────────────────────────────────────

export function Profile360OutcomesPanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'outcomes-overview');
  const data = asRec(section?.data);
  const items: unknown[] = Array.isArray(data.items) ? data.items : [];
  const ledger = asRec(data.ledger);

  return (
    <div className="space-y-4 pt-2">
      {Boolean(ledger.summary) && (
        <Card>
          <CardHeader><CardTitle>Outcome ledger summary</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {Object.entries(asRec(ledger.summary)).map(([k, v]) => (
                <div key={k} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
                  <div className="text-[10px] uppercase tracking-wide text-text-muted">{k.replace(/_/g, ' ')}</div>
                  <div className="mt-1 text-base font-semibold font-mono text-text-primary">{String(v)}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
      {items.length === 0 ? (
        <EmptyState title="No outcomes" description="No outcome history has been recorded for this entity." />
      ) : (
        <Card>
          <CardHeader><CardTitle>Outcomes ({items.length})</CardTitle></CardHeader>
          <CardContent>
            <ScrollArea maxHeight="400px">
              <div className="space-y-2">
                {items.map((item, i) => {
                  const or = asRec(item);
                  const outcome = String(or.outcome_type ?? or.type ?? 'outcome');
                  const status = String(or.status ?? '');
                  const ts = String(or.created_at ?? or.timestamp ?? '');
                  return (
                    <div key={String(or.outcome_id ?? or.id ?? i)} className="flex items-center justify-between py-2 px-3 border border-border-subtle rounded bg-surface-raised text-xs">
                      <div className="flex-1 min-w-0">
                        <Badge size="sm">{outcome}</Badge>
                        {Boolean(or.description) && <span className="ml-2 text-text-secondary">{String(or.description)}</span>}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {status && <Badge variant={status === 'completed' ? 'success' : status === 'failed' ? 'danger' : 'default'} size="sm">{status}</Badge>}
                        {ts && <span className="text-[10px] font-mono text-text-muted">{ts.slice(0, 16)}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Intelligence ──────────────────────────────────────────────────────────────

export function Profile360IntelligencePanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'intelligence-overview');
  const data = asRec(section?.data);
  const tier = String(data.tier ?? data.loyalty_tier ?? '');
  const riskScore = typeof data.risk_score === 'number' ? data.risk_score : null;
  const trustScore = typeof data.trust_score === 'number' ? data.trust_score : null;
  const anomalyScore = typeof data.anomaly_score === 'number' ? data.anomaly_score : null;
  const riskFlags: string[] = Array.isArray(data.risk_flags) ? data.risk_flags.map(String) : [];

  return (
    <div className="space-y-4 pt-2">
      {section?.metrics && section.metrics.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
          {section.metrics.map(m => (
            <div key={m.id} className="rounded border border-border-subtle bg-surface-raised p-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-muted">{m.label}</div>
              <div className={cn('mt-1 text-base font-semibold font-mono',
                m.tone === 'good' ? 'text-success' : m.tone === 'warning' ? 'text-warning' : m.tone === 'danger' ? 'text-danger' : 'text-text-primary'
              )}>{m.value}{m.unit ?? ''}</div>
            </div>
          ))}
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {riskScore !== null && (
          <Card>
            <CardHeader><CardTitle>Risk</CardTitle></CardHeader>
            <CardContent>
              <div className={cn('text-3xl font-bold font-mono', riskScore > 0.6 ? 'text-danger' : riskScore > 0.3 ? 'text-warning' : 'text-success')}>
                {(riskScore * 100).toFixed(0)}%
              </div>
            </CardContent>
          </Card>
        )}
        {trustScore !== null && (
          <Card>
            <CardHeader><CardTitle>Trust</CardTitle></CardHeader>
            <CardContent>
              <div className={cn('text-3xl font-bold font-mono', trustScore > 0.7 ? 'text-success' : trustScore > 0.4 ? 'text-warning' : 'text-danger')}>
                {(trustScore * 100).toFixed(0)}%
              </div>
            </CardContent>
          </Card>
        )}
        {anomalyScore !== null && (
          <Card>
            <CardHeader><CardTitle>Anomaly</CardTitle></CardHeader>
            <CardContent>
              <div className={cn('text-3xl font-bold font-mono', anomalyScore > 0.6 ? 'text-danger' : anomalyScore > 0.3 ? 'text-warning' : 'text-success')}>
                {(anomalyScore * 100).toFixed(0)}%
              </div>
            </CardContent>
          </Card>
        )}
      </div>
      {tier && (
        <Card>
          <CardHeader><CardTitle>Entity tier</CardTitle></CardHeader>
          <CardContent><Badge variant="accent" size="md">{tier}</Badge></CardContent>
        </Card>
      )}
      {riskFlags.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Risk flags ({riskFlags.length})</CardTitle></CardHeader>
          <CardContent><div className="flex flex-wrap gap-1">{riskFlags.map(f => <Badge key={f} variant="danger" size="sm">{f}</Badge>)}</div></CardContent>
        </Card>
      )}
      {riskScore === null && trustScore === null && section?.metrics?.length === 0 && (
        <EmptyState title="No intelligence data" description="Intelligence scores have not been computed. Source: ML intelligence service." />
      )}
    </div>
  );
}

// ── Provenance ────────────────────────────────────────────────────────────────

export function Profile360ProvenancePanel({ sections }: { readonly sections: readonly Profile360Section[] }) {
  const section = sections.find(s => s.id === 'provenance-overview');
  const data = asRec(section?.data);
  const sources: string[] = Array.isArray(data.sources) ? data.sources.map(String) : [];
  const freshnessStatus = String(data.freshness_status ?? 'unknown');
  const sourceWarnings: string[] = Array.isArray(data.source_warnings) ? data.source_warnings.map(String) : [];
  const dimensions = asRec(data.dimensions);

  const freshnessVariant = freshnessStatus === 'fresh' ? 'success' : freshnessStatus === 'stale' ? 'danger' : freshnessStatus === 'aging' ? 'warning' : 'default';

  return (
    <div className="space-y-4 pt-2">
      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardHeader><CardTitle>Sources</CardTitle></CardHeader>
          <CardContent>
            <div className="text-3xl font-bold font-mono text-text-primary">{sources.length || String(data.source_count ?? '—')}</div>
            {Boolean(data.primary_source) && <p className="text-xs text-text-muted mt-1">Primary: {String(data.primary_source)}</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Freshness</CardTitle></CardHeader>
          <CardContent>
            <Badge variant={freshnessVariant} size="md">{freshnessStatus}</Badge>
            {Boolean(data.last_source_update) && <p className="text-[10px] text-text-muted mt-2 font-mono">{String(data.last_source_update).slice(0, 16)}</p>}
          </CardContent>
        </Card>
      </div>
      {sources.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Source systems</CardTitle></CardHeader>
          <CardContent><div className="flex flex-wrap gap-1">{sources.map(s => <Badge key={s} size="sm">{s}</Badge>)}</div></CardContent>
        </Card>
      )}
      {sourceWarnings.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Source warnings ({sourceWarnings.length})</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-1">
              {sourceWarnings.map((w, i) => <p key={i} className="text-xs text-warning">{w}</p>)}
            </div>
          </CardContent>
        </Card>
      )}
      {Object.keys(dimensions).length > 0 && (
        <Card>
          <CardHeader><CardTitle>Per-dimension freshness</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {Object.entries(dimensions).map(([dim, dimData]) => {
                const dd = asRec(dimData);
                const dimFreshness = String(dd.freshness_status ?? dd.status ?? 'unknown');
                return (
                  <div key={dim} className="flex items-center justify-between text-xs py-1 border-b border-border-subtle last:border-0">
                    <span className="text-text-secondary">{dim}</span>
                    <div className="flex items-center gap-2">
                      {Boolean(dd.last_updated) && <span className="text-[10px] font-mono text-text-muted">{String(dd.last_updated).slice(0, 10)}</span>}
                      <Badge variant={dimFreshness === 'fresh' ? 'success' : dimFreshness === 'stale' ? 'danger' : dimFreshness === 'aging' ? 'warning' : 'default'} size="sm">{dimFreshness}</Badge>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
      {sources.length === 0 && sourceWarnings.length === 0 && Object.keys(dimensions).length === 0 && (
        <EmptyState title="No provenance data" description="Data provenance has not been recorded. Source: connector pipeline." />
      )}
    </div>
  );
}
