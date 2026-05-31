import { useState } from 'react';
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
