import { useParams, useNavigate } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader,
  DataTable, EmptyState, ErrorState, LoadingState,
  Skeleton, StatusIndicator, Tabs, TabsContent, TabsList, TabsTrigger,
} from '@aether/ui';
import {
  useUserProfile, useUserSessions, useUserDevices, useUserPlatforms,
  useUserJourneys, useUserWallets, useUserFinancials, useUserRewards,
  useUserIdentifiers, useUserIntelligence, useUserBehavioral,
  useUserWhyExplain, useUserAttributionJourney, useUserGraph, useUserCluster,
} from '@aether-app/features/users/use-user-profile';

// ── helpers ────────────────────────────────────────────────────────────────────

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function fmtScore(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return `${Math.round(Number(v) * 100)}`;
}

function relTime(iso: string | undefined | null): string {
  if (!iso) return '—';
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d === 0) return 'Today';
  if (d === 1) return 'Yesterday';
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
}

function fmtDuration(ms: number | undefined | null): string {
  if (!ms) return '—';
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function scoreBadge(score: number | undefined, label: string, invert = false) {
  if (score === undefined) return null;
  const pct = Math.round(score * 100);
  const v = invert
    ? (score >= 0.7 ? 'danger' : score >= 0.4 ? 'warning' : 'success')
    : (score >= 0.7 ? 'success' : score >= 0.4 ? 'warning' : 'danger');
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-text-secondary">{label}</span>
      <Badge variant={v} size="sm">{pct}</Badge>
    </div>
  );
}

// ── Section wrapper ────────────────────────────────────────────────────────────

function Section({ title, children, loading, error }: { title: string; children: React.ReactNode; loading?: boolean; error?: string | null }) {
  if (loading) return <LoadingState lines={4} />;
  if (error) return <p className="text-xs text-danger">{error}</p>;
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-text-secondary uppercase tracking-wide">{title}</h3>
      {children}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="bg-surface-raised border border-border-default rounded-md px-3 py-2">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className="text-sm font-medium text-text-primary mt-0.5">{value}</p>
    </div>
  );
}

// ── Overview tab ──────────────────────────────────────────────────────────────

function OverviewTab({ userId }: { userId: string }) {
  const { data: summary, isLoading: sl, error: se } = useUserProfile(userId);
  const { data: intel, isLoading: il, error: ie } = useUserIntelligence(userId);
  const { data: ids, isLoading: idl, error: ide } = useUserIdentifiers(userId);
  const { data: platforms, isLoading: pl } = useUserPlatforms(userId);
  const { data: rewardsData, isLoading: rl } = useUserRewards(userId);

  const s = asRecord(summary);
  const i = asRecord(intel);
  const idData = asRecord(ids);
  const pList = asList(asRecord(platforms).platforms ?? platforms);
  const r = asRecord(rewardsData);

  return (
    <div className="space-y-6">
      {/* Scores */}
      <Section title="Intelligence scores" loading={il} error={ie}>
        <div className="grid grid-cols-3 gap-3">
          {scoreBadge(i.trust_score as number, 'Trust')}
          {scoreBadge(i.risk_score as number, 'Risk', true)}
          {scoreBadge(i.anomaly_score as number, 'Anomaly', true)}
        </div>
      </Section>

      {/* Summary stats */}
      <Section title="Activity summary" loading={sl} error={se}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label="Sessions (7d)" value={fmt(s.sessions_7d)} />
          <Stat label="Sessions (30d)" value={fmt(s.sessions_30d)} />
          <Stat label="Recency" value={fmt(s.last_seen_at ? relTime(s.last_seen_at as string) : undefined)} />
          <Stat label="Churn risk" value={
            s.churn_risk
              ? <Badge variant={s.churn_risk === 'low' ? 'success' : s.churn_risk === 'churned' ? 'danger' : 'warning'} size="sm">{fmt(s.churn_risk)}</Badge>
              : '—'
          } />
          <Stat label="First seen" value={relTime(s.first_seen_at as string | undefined)} />
          <Stat label="Avg session" value={fmtDuration(s.avg_session_duration_ms as number | undefined)} />
          <Stat label="Active days (30d)" value={fmt(s.active_days_30d)} />
          <Stat label="Events (30d)" value={fmt(s.events_30d)} />
        </div>
      </Section>

      {/* Loyalty */}
      <Section title="Loyalty & rewards" loading={rl}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label="Tier" value={r.tier ? <Badge variant="warning" size="sm">{fmt(r.tier)}</Badge> : '—'} />
          <Stat label="Points" value={fmt(r.points_balance)} />
          <Stat label="Rewards earned" value={fmt(r.rewards_earned)} />
          <Stat label="Campaigns" value={fmt(r.campaigns_participated)} />
        </div>
      </Section>

      {/* Platforms */}
      <Section title="Platforms" loading={pl}>
        <div className="flex flex-wrap gap-2">
          {pList.length === 0
            ? <p className="text-xs text-text-muted">No platform data</p>
            : pList.map((p, i) => {
                const pr = asRecord(p);
                const name = fmt(pr.platform ?? p);
                return (
                  <div key={i} className="bg-surface-raised border border-border-default rounded-md px-3 py-2 text-xs">
                    <span className="font-medium text-text-primary">{name}</span>
                    {pr.session_count !== undefined && (
                      <span className="text-text-secondary ml-2">{fmt(pr.session_count)} sessions</span>
                    )}
                  </div>
                );
              })
          }
        </div>
      </Section>

      {/* Identifiers */}
      <Section title="Identifiers" loading={idl} error={ide}>
        <div className="space-y-2">
          {(['wallets', 'emails', 'devices', 'sessions', 'social_handles', 'customer_ids'] as const).map(kind => {
            const items = asList(idData[kind]);
            if (items.length === 0) return null;
            return (
              <div key={kind} className="flex items-start gap-2">
                <span className="text-xs text-text-secondary w-24 flex-shrink-0 capitalize">{kind.replace('_', ' ')}</span>
                <div className="flex flex-wrap gap-1">
                  {items.slice(0, 6).map((v, i) => (
                    <code key={i} className="text-xs bg-surface-overlay border border-border-default rounded px-1.5 py-0.5 text-text-primary break-all">{fmt(v)}</code>
                  ))}
                  {items.length > 6 && <span className="text-xs text-text-muted">+{items.length - 6} more</span>}
                </div>
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

// ── Sessions tab ──────────────────────────────────────────────────────────────

function SessionsTab({ userId }: { userId: string }) {
  const { data, isLoading, error } = useUserSessions(userId, 30);
  const { data: devicesData, isLoading: dl } = useUserDevices(userId);

  const sessions = asList(asRecord(data).sessions ?? data);
  const devices = asList(asRecord(devicesData).devices ?? devicesData);

  type SessionRow = Record<string, unknown>;

  return (
    <div className="space-y-6">
      <Section title="Recent sessions" loading={isLoading} error={error}>
        <DataTable<SessionRow>
          keyExtractor={s => String(s.session_id ?? 'session')}
          data={sessions as SessionRow[]}
          emptyMessage="No sessions recorded"
          columns={[
            { key: 'platform', header: 'Platform', render: s => <Badge variant="default" size="sm">{fmt(asRecord(s.device ?? s).type ?? s.platform)}</Badge> },
            { key: 'os', header: 'OS / Browser', render: s => {
              const d = asRecord(s.device ?? s);
              return <span className="text-text-secondary">{fmt(d.os)} / {fmt(d.browser)}</span>;
            }},
            { key: 'geo', header: 'Location', render: s => {
              const g = asRecord(s.geo ?? s);
              const vpn = g.is_vpn ? <Badge variant="warning" size="sm">VPN</Badge> : null;
              const tor = g.is_tor ? <Badge variant="danger" size="sm">Tor</Badge> : null;
              return <span className="flex items-center gap-1">{fmt(g.city ?? g.country_code)} {vpn}{tor}</span>;
            }},
            { key: 'duration', header: 'Duration', render: s => fmtDuration(s.duration_ms as number) },
            { key: 'pages', header: 'Pages', render: s => fmt(s.page_views) },
            { key: 'entry', header: 'Entry', render: s => <span className="text-text-muted text-xs truncate max-w-32 block">{fmt(s.entry_url)}</span> },
            { key: 'campaign', header: 'Campaign', render: s => {
              const c = asRecord(s.campaign ?? s);
              return c.campaign ? <Badge variant="default" size="sm">{fmt(c.campaign)}</Badge> : <span className="text-text-muted">—</span>;
            }},
            { key: 'when', header: 'When', render: s => relTime(s.started_at as string) },
          ]}
        />
      </Section>

      <Section title="Observed devices" loading={dl}>
        <DataTable<SessionRow>
          keyExtractor={d => String(d.device_id ?? 'device')}
          data={devices as SessionRow[]}
          emptyMessage="No device data"
          columns={[
            { key: 'type', header: 'Type', render: d => <Badge variant="default" size="sm">{fmt(d.type)}</Badge> },
            { key: 'os', header: 'OS', render: d => <span className="text-text-secondary">{fmt(d.os)} {fmt(d.os_version)}</span> },
            { key: 'browser', header: 'Browser', render: d => <span className="text-text-secondary">{fmt(d.browser)} {fmt(d.browser_version)}</span> },
            { key: 'sessions', header: 'Sessions', render: d => fmt(d.session_count) },
            { key: 'det', header: 'Match', render: d => <Badge variant={d.is_deterministic ? 'success' : 'warning'} size="sm">{d.is_deterministic ? 'Login' : 'Fingerprint'}</Badge> },
            { key: 'last', header: 'Last seen', render: d => relTime(d.last_seen_at as string) },
          ]}
        />
      </Section>
    </div>
  );
}

// ── Journeys tab ──────────────────────────────────────────────────────────────

function JourneysTab({ userId }: { userId: string }) {
  const { data, isLoading, error } = useUserJourneys(userId);
  const journeys = asList(asRecord(data).journeys ?? data);

  type JourneyRow = Record<string, unknown>;

  return (
    <Section title="Cross-session journeys" loading={isLoading} error={error}>
      {journeys.length === 0
        ? <EmptyState title="No journeys" description="No multi-step journeys have been tracked yet." />
        : journeys.map((j, ji) => {
            const jr = asRecord(j);
            const steps = asList(jr.steps);
            const pct = Math.round(Number(jr.completion_rate ?? 0) * 100);
            return (
              <Card key={ji} className="mb-4">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-text-primary">Journey {ji + 1}</span>
                      {!!jr.converted && <Badge variant="success" size="sm">Converted</Badge>}
                      {!!jr.entry_channel && <Badge variant="default" size="sm">{fmt(jr.entry_channel)}</Badge>}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-text-secondary">
                      <span>{pct}% complete</span>
                      <span>{fmtDuration(jr.total_time_ms as number)}</span>
                      <span>{relTime(jr.started_at as string)}</span>
                    </div>
                  </div>
                  {/* Completion bar */}
                  <div className="h-1 bg-surface-overlay rounded-full mt-2">
                    <div className="h-1 bg-accent rounded-full transition-all" style={{ width: `${pct}%` }} />
                  </div>
                </CardHeader>
                <CardContent>
                  <DataTable<JourneyRow>
                    keyExtractor={s => `step-${ji}-${String(s._stepNum ?? s.step_name ?? s.event_type ?? 'step')}`}
                    data={steps.map((s, idx) => ({ ...asRecord(s), _stepNum: idx + 1 })) as JourneyRow[]}
                    emptyMessage="No steps"
                    columns={[
                      { key: 'n', header: '#', render: s => <span className="text-text-muted">{fmt(s._stepNum)}</span> },
                      { key: 'name', header: 'Step', render: s => <span className="font-medium text-text-primary">{fmt(s.step_name ?? s.event_type)}</span> },
                      { key: 'channel', header: 'Channel', render: s => s.channel ? <Badge variant="default" size="sm">{fmt(s.channel)}</Badge> : <span className="text-text-muted">—</span> },
                      { key: 'campaign', header: 'Campaign', render: s => s.campaign_name ? <span className="text-text-secondary text-xs">{fmt(s.campaign_name)}</span> : <span className="text-text-muted">—</span> },
                      { key: 'time', header: 'Time on step', render: s => fmtDuration(s.time_on_step_ms as number) },
                      { key: 'status', header: 'Status', render: s => {
                        if (s.is_abandonment) return <Badge variant="danger" size="sm">Abandoned</Badge>;
                        if (s.is_drop_off) return <Badge variant="warning" size="sm">Drop-off</Badge>;
                        if (s.completed) return <Badge variant="success" size="sm">Completed</Badge>;
                        return <Badge variant="default" size="sm">In progress</Badge>;
                      }},
                    ]}
                  />
                </CardContent>
              </Card>
            );
          })
      }
    </Section>
  );
}

// ── Wallets tab ────────────────────────────────────────────────────────────────

function WalletsTab({ userId }: { userId: string }) {
  const { data, isLoading, error } = useUserWallets(userId);
  const wallets = asList(asRecord(data).wallets ?? data);

  type Row = Record<string, unknown>;

  return (
    <Section title="Web3 wallets" loading={isLoading} error={error}>
      {wallets.length === 0
        ? <EmptyState title="No wallets" description="No wallets linked to this user." />
        : wallets.map((w, wi) => {
            const wr = asRecord(w);
            const tokens = asList(wr.token_balances);
            const txs = asList(wr.recent_transactions);
            const protocols = asList(wr.protocol_interactions);
            const web3Loyalty = asRecord(wr.web3_loyalty);
            const portfolio = wr.total_portfolio_usd;
            return (
              <Card key={wi} className="mb-4">
                <CardHeader>
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div>
                      <code className="text-xs font-mono text-text-primary">{fmt(wr.wallet_address)}</code>
                      {!!wr.ens_name && <span className="ml-2 text-sm text-accent">{fmt(wr.ens_name)}</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="default" size="sm">{fmt(wr.wallet_type)}</Badge>
                      {!!wr.is_sanctioned && <Badge variant="danger" size="sm">Sanctioned</Badge>}
                      {wr.risk_score !== undefined && (
                        <Badge variant={Number(wr.risk_score) > 0.6 ? 'danger' : Number(wr.risk_score) > 0.3 ? 'warning' : 'success'} size="sm">
                          {`Risk ${fmtScore(wr.risk_score)}`}
                        </Badge>
                      )}
                      {portfolio !== undefined && (
                        <span className="text-sm font-medium text-text-primary">
                          ${Number(portfolio).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </span>
                      )}
                    </div>
                  </div>
                  {/* Risk flags */}
                  {asList(wr.risk_flags).length > 0 && (
                    <div className="flex gap-1 flex-wrap mt-2">
                      {asList(wr.risk_flags).map((f, i) => <Badge key={i} variant="danger" size="sm">{fmt(f)}</Badge>)}
                    </div>
                  )}
                  {/* Web3 loyalty signals */}
                  {web3Loyalty.wallet_age_days !== undefined && (
                    <div className="grid grid-cols-4 gap-2 mt-3">
                      <Stat label="Wallet age" value={`${fmt(web3Loyalty.wallet_age_days)}d`} />
                      <Stat label="Chains" value={fmt(web3Loyalty.total_chains_active)} />
                      <Stat label="Protocols" value={fmt(web3Loyalty.unique_protocols_used)} />
                      <Stat label="Web3 score" value={<Badge variant="default" size="sm">{fmtScore(web3Loyalty.web3_engagement_score)}</Badge>} />
                    </div>
                  )}
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Token balances */}
                  {tokens.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-text-secondary mb-2">Token balances</h4>
                      <DataTable<Row>
                        keyExtractor={t => String(t.symbol ?? t.contract_address ?? 'token')}
                        data={tokens.slice(0, 10) as Row[]}
                        columns={[
                          { key: 'token', header: 'Token', render: t => <span className="font-medium text-text-primary">{fmt(t.symbol)}</span> },
                          { key: 'type', header: 'Type', render: t => <Badge variant="default" size="sm">{fmt(t.token_type)}</Badge> },
                          { key: 'chain', header: 'Chain', render: t => <span className="text-text-secondary">{fmt(t.chain_id)}</span> },
                          { key: 'balance', header: 'Balance', render: t => <span className="font-mono text-text-primary">{Number(t.balance ?? 0).toLocaleString(undefined, { maximumFractionDigits: 4 })}</span> },
                          { key: 'value', header: 'Value (USD)', render: t => t.value_usd !== undefined ? <span className="text-text-primary">${Number(t.value_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span> : <span className="text-text-muted">—</span> },
                          { key: 'price_chg', header: '24h', render: t => {
                            const chg = t.price_change_24h as number | undefined;
                            if (chg === undefined) return <span className="text-text-muted">—</span>;
                            return <span className={chg >= 0 ? 'text-success' : 'text-danger'}>{chg >= 0 ? '+' : ''}{chg.toFixed(2)}%</span>;
                          }},
                        ]}
                      />
                    </div>
                  )}

                  {/* Protocol interactions */}
                  {protocols.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-text-secondary mb-2">Protocol interactions</h4>
                      <DataTable<Row>
                        keyExtractor={p => String(p.protocol_id ?? p.protocol_name ?? 'protocol')}
                        data={protocols as Row[]}
                        columns={[
                          { key: 'protocol', header: 'Protocol', render: p => <span className="font-medium text-text-primary">{fmt(p.protocol_name)}</span> },
                          { key: 'category', header: 'Category', render: p => <Badge variant="default" size="sm">{fmt(p.category)}</Badge> },
                          { key: 'chain', header: 'Chain', render: p => <span className="text-text-secondary">{fmt(p.chain_id)}</span> },
                          { key: 'count', header: 'Interactions', render: p => fmt(p.interaction_count) },
                          { key: 'volume', header: 'Volume', render: p => p.volume_usd !== undefined ? <span>${Number(p.volume_usd).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span> : <span className="text-text-muted">—</span> },
                          { key: 'position', header: 'Position', render: p => p.current_position_usd !== undefined ? <span className="text-success">${Number(p.current_position_usd).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span> : <span className="text-text-muted">—</span> },
                          { key: 'last', header: 'Last', render: p => relTime(p.last_interaction_at as string) },
                        ]}
                      />
                    </div>
                  )}

                  {/* Recent transactions */}
                  {txs.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-text-secondary mb-2">Recent transactions</h4>
                      <DataTable<Row>
                        keyExtractor={t => String(t.tx_hash ?? 'tx')}
                        data={txs.slice(0, 10) as Row[]}
                        columns={[
                          { key: 'hash', header: 'Tx', render: t => <code className="text-xs text-text-muted">{fmt(t.tx_hash).slice(0, 10)}…</code> },
                          { key: 'type', header: 'Type', render: t => <Badge variant="default" size="sm">{fmt(t.transaction_type)}</Badge> },
                          { key: 'protocol', header: 'Protocol', render: t => fmt(t.protocol_name) },
                          { key: 'method', header: 'Method', render: t => <span className="text-text-secondary">{fmt(t.method_name)}</span> },
                          { key: 'value', header: 'Value', render: t => t.value_usd !== undefined ? <span>${Number(t.value_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span> : <span className="text-text-muted">—</span> },
                          { key: 'status', header: 'Status', render: t => <Badge variant={t.success ? 'success' : 'danger'} size="sm">{t.success ? 'OK' : 'Failed'}</Badge> },
                          { key: 'when', header: 'When', render: t => relTime(t.timestamp as string) },
                        ]}
                      />
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })
      }
    </Section>
  );
}

// ── Financials tab ────────────────────────────────────────────────────────────

function FinancialsTab({ userId }: { userId: string }) {
  const { data, isLoading, error } = useUserFinancials(userId);
  const f = asRecord(data);
  const web2 = asRecord(f.web2);
  const web3 = asRecord(f.web3);
  const counterparties = asList(f.top_counterparties ?? web3.top_counterparties ?? web2.top_counterparties);
  type Row = Record<string, unknown>;

  return (
    <Section title="Financial profile (Web2 + Web3)" loading={isLoading} error={error}>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        <Stat label="Lifetime value" value={f.lifetime_value_usd !== undefined ? `$${Number(f.lifetime_value_usd).toLocaleString()}` : '—'} />
        <Stat label="Total inflow" value={f.total_inflow_usd !== undefined ? `$${Number(f.total_inflow_usd).toLocaleString()}` : web3.total_inflow_usd !== undefined ? `$${Number(web3.total_inflow_usd).toLocaleString()}` : '—'} />
        <Stat label="Total outflow" value={f.total_outflow_usd !== undefined ? `$${Number(f.total_outflow_usd).toLocaleString()}` : web3.total_outflow_usd !== undefined ? `$${Number(web3.total_outflow_usd).toLocaleString()}` : '—'} />
        <Stat label="Web2 payments" value={fmt(web2.payment_count)} />
        <Stat label="Subscriptions" value={fmt(web2.subscription_count)} />
        <Stat label="On-chain tx" value={fmt(web3.transaction_count)} />
      </div>
      {counterparties.length > 0 && (
        <>
          <h4 className="text-xs font-medium text-text-secondary mb-2">Top counterparties</h4>
          <DataTable<Row>
            keyExtractor={c => String(c.entity_id ?? c.address ?? 'counterparty')}
            data={counterparties as Row[]}
            columns={[
              { key: 'entity', header: 'Entity', render: c => <code className="text-xs text-text-primary">{fmt(c.entity_id ?? c.address)}</code> },
              { key: 'type', header: 'Type', render: c => <Badge variant="default" size="sm">{fmt(c.kind ?? c.type)}</Badge> },
              { key: 'volume', header: 'Volume', render: c => c.volume_usd !== undefined ? <span>${Number(c.volume_usd).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span> : <span className="text-text-muted">—</span> },
              { key: 'tx', header: 'Transactions', render: c => fmt(c.transaction_count ?? c.count) },
              { key: 'dir', header: 'Direction', render: c => c.direction ? <Badge variant="default" size="sm">{fmt(c.direction)}</Badge> : <span className="text-text-muted">—</span> },
            ]}
          />
        </>
      )}
    </Section>
  );
}

// ── Behavioral "Why" tab ──────────────────────────────────────────────────────

function BehavioralTab({ userId }: { userId: string }) {
  const { data: behavData, isLoading: bl, error: be } = useUserBehavioral(userId);
  const { data: whyData, isLoading: wl, error: we } = useUserWhyExplain(userId);
  const signals = asList(asRecord(behavData).signals ?? (behavData as unknown[]));
  const why = asRecord(whyData);
  const topSignals = asList(why.top_signals);

  const severityVariant = (sev: string): 'danger' | 'warning' | 'success' | 'default' => {
    if (sev === 'critical') return 'danger';
    if (sev === 'high') return 'warning';
    if (sev === 'medium') return 'default';
    return 'default';
  };

  type Row = Record<string, unknown>;

  return (
    <div className="space-y-6">
      {/* Why explanation */}
      <Section title="Why is this entity notable?" loading={wl} error={we}>
        {!!why.behavioral_context && (
          <p className="text-sm text-text-secondary mb-3">{fmt(why.behavioral_context)}</p>
        )}
        {why.overall_confidence !== undefined && (
          <p className="text-xs text-text-muted mb-3">Overall confidence: {Math.round(Number(why.overall_confidence) * 100)}%</p>
        )}
        {topSignals.length === 0
          ? <p className="text-xs text-text-muted">No anomalies detected.</p>
          : topSignals.map((sig, i) => {
              const s = asRecord(sig);
              return (
                <div key={i} className="border border-border-default rounded-md p-3 space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge variant={severityVariant(fmt(s.severity))} size="sm">{fmt(s.severity)}</Badge>
                    <Badge variant="default" size="sm">{fmt(s.signal_type)}</Badge>
                    {!!s.family && <Badge variant="default" size="sm">{fmt(s.family)}</Badge>}
                    <span className="text-xs text-text-muted ml-auto">Confidence: {Math.round(Number(s.confidence ?? 0) * 100)}%</span>
                  </div>
                  <p className="text-sm text-text-primary">{fmt(s.explanation)}</p>
                  {s.expected !== undefined && (
                    <p className="text-xs text-text-muted">Expected: {fmt(s.expected)} → Observed: {fmt(s.observed)}</p>
                  )}
                </div>
              );
            })
        }
        {!!why.expectation_gaps && asList(why.expectation_gaps).length > 0 && (
          <div className="mt-3">
            <h4 className="text-xs font-medium text-text-secondary mb-1">Expectation gaps</h4>
            <ul className="space-y-1">
              {asList(why.expectation_gaps).map((g, i) => <li key={i} className="text-xs text-text-secondary">• {fmt(g)}</li>)}
            </ul>
          </div>
        )}
      </Section>

      {/* All behavioral signals */}
      <Section title="All behavioral signals" loading={bl} error={be}>
        <DataTable<Row>
          keyExtractor={s => String(s.signal_id ?? s.signal_type ?? 'signal')}
          data={signals as Row[]}
          emptyMessage="No behavioral signals"
          columns={[
            { key: 'type', header: 'Signal', render: s => <span className="font-medium text-text-primary">{fmt(s.signal_type)}</span> },
            { key: 'family', header: 'Family', render: s => s.family ? <Badge variant="default" size="sm">{fmt(s.family)}</Badge> : <span className="text-text-muted">—</span> },
            { key: 'severity', header: 'Severity', render: s => <Badge variant={severityVariant(fmt(s.severity))} size="sm">{fmt(s.severity)}</Badge> },
            { key: 'conf', header: 'Confidence', render: s => `${Math.round(Number(s.confidence ?? 0) * 100)}%` },
            { key: 'source_silence', header: 'Silent?', render: s => s.is_source_silence ? <Badge variant="warning" size="sm">Silent</Badge> : <span className="text-text-muted">No</span> },
            { key: 'explanation', header: 'Explanation', render: s => <span className="text-text-secondary text-xs">{fmt(s.explanation)}</span> },
          ]}
        />
      </Section>
    </div>
  );
}

// ── Attribution "Where" tab ───────────────────────────────────────────────────

function AttributionTab({ userId }: { userId: string }) {
  const { data, isLoading, error } = useUserAttributionJourney(userId);
  const touchpoints = asList(asRecord(data).touchpoints ?? (data as unknown[]));

  type Row = Record<string, unknown>;

  return (
    <Section title="Attribution journey (where conversions came from)" loading={isLoading} error={error}>
      <DataTable<Row>
        keyExtractor={tp => String(tp.touchpoint_id ?? 'touchpoint')}
        data={touchpoints as Row[]}
        emptyMessage="No touchpoints recorded"
        columns={[
          { key: 'channel', header: 'Channel', render: tp => <Badge variant="default" size="sm">{fmt(tp.channel)}</Badge> },
          { key: 'source', header: 'Source', render: tp => <span className="text-text-secondary">{fmt(tp.source)}</span> },
          { key: 'campaign', header: 'Campaign', render: tp => tp.campaign ? <span className="text-text-primary">{fmt(tp.campaign)}</span> : <span className="text-text-muted">—</span> },
          { key: 'event', header: 'Event type', render: tp => fmt(tp.event_type) },
          { key: 'when', header: 'When', render: tp => relTime(tp.timestamp as string) },
        ]}
      />
    </Section>
  );
}

// ── Relationships / Graph tab ─────────────────────────────────────────────────

function RelationshipsTab({ userId }: { userId: string }) {
  const { data: graphData, isLoading: gl, error: ge } = useUserGraph(userId);
  const { data: clusterData, isLoading: cl } = useUserCluster(userId);

  const g = asRecord(graphData);
  const edges = asList(g.edges);
  const nodes = asList(g.nodes);
  const cluster = asRecord(clusterData);
  const clusterMembers = asList(cluster.members);

  type Row = Record<string, unknown>;

  const interactionColor = (cls: string): 'default' | 'success' | 'warning' | 'danger' => {
    if (cls === 'H2H') return 'success';
    if (cls === 'H2A') return 'warning';
    if (cls === 'A2H') return 'default';
    if (cls === 'A2A') return 'danger';
    return 'default';
  };

  return (
    <div className="space-y-6">
      {/* Identity cluster */}
      <Section title="Identity cluster (same real-world actor)" loading={cl}>
        {clusterMembers.length === 0
          ? <p className="text-xs text-text-muted">No cluster detected — entity appears unique.</p>
          : (
            <>
              <div className="grid grid-cols-3 gap-3 mb-3">
                <Stat label="Cluster size" value={fmt(cluster.cluster_size)} />
                <Stat label="Behavioral similarity" value={cluster.behavioral_similarity !== undefined ? `${Math.round(Number(cluster.behavioral_similarity) * 100)}%` : '—'} />
                <Stat label="Confidence" value={cluster.confidence !== undefined ? `${Math.round(Number(cluster.confidence) * 100)}%` : '—'} />
              </div>
              <DataTable<Row>
                keyExtractor={m => String(m.entity_id ?? 'member')}
                data={clusterMembers as Row[]}
                columns={[
                  { key: 'entity', header: 'Entity', render: m => <code className="text-xs text-text-primary">{fmt(m.entity_id)}</code> },
                  { key: 'kind', header: 'Kind', render: m => <Badge variant="default" size="sm">{fmt(m.kind)}</Badge> },
                  { key: 'links', header: 'Link types', render: m => (
                    <div className="flex gap-1 flex-wrap">
                      {asList(m.link_types).slice(0, 3).map((l, i) => <Badge key={i} variant="default" size="sm">{fmt(l)}</Badge>)}
                    </div>
                  )},
                  { key: 'conf', header: 'Membership', render: m => `${Math.round(Number(m.membership_confidence ?? 0) * 100)}%` },
                ]}
              />
              {/* Formation signals */}
              {asList(cluster.formation_signals).length > 0 && (
                <div className="flex gap-1 flex-wrap mt-2">
                  <span className="text-xs text-text-secondary">Linked by:</span>
                  {asList(cluster.formation_signals).map((s, i) => <Badge key={i} variant="default" size="sm">{fmt(s)}</Badge>)}
                </div>
              )}
            </>
          )
        }
      </Section>

      {/* Relationship edges */}
      <Section title="Relationship edges (H2H / H2A / A2H / A2A)" loading={gl} error={ge}>
        <DataTable<Row>
          keyExtractor={e => String(e.edge_id ?? `${String(e.from_entity_id)}-${String(e.to_entity_id)}`)}
          data={edges as Row[]}
          emptyMessage="No relationships found"
          columns={[
            { key: 'class', header: 'Class', render: e => <Badge variant={interactionColor(fmt(e.interaction_class))} size="sm">{fmt(e.interaction_class)}</Badge> },
            { key: 'type', header: 'Relation', render: e => <span className="text-text-primary">{fmt(e.relation_type)}</span> },
            { key: 'to', header: 'Counterparty', render: e => <code className="text-xs text-text-secondary">{fmt(e.to_entity_id ?? e.from_entity_id)}</code> },
            { key: 'toKind', header: 'Kind', render: e => <Badge variant="default" size="sm">{fmt(e.to_kind ?? e.from_kind)}</Badge> },
            { key: 'weight', header: 'Weight', render: e => `${Math.round(Number(e.weight ?? 0) * 100)}%` },
            { key: 'conf', header: 'Confidence', render: e => `${Math.round(Number(e.confidence ?? 0) * 100)}%` },
            { key: 'inferred', header: 'Source', render: e => <Badge variant={e.is_inferred ? 'warning' : 'success'} size="sm">{e.is_inferred ? 'Inferred' : 'Explicit'}</Badge> },
            { key: 'volume', header: 'Volume', render: e => e.volume_usd !== undefined ? <span>${Number(e.volume_usd).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span> : <span className="text-text-muted">—</span> },
          ]}
        />
      </Section>

      {/* Graph nodes (nearby entities) */}
      {nodes.length > 0 && (
        <Section title="Connected entities">
          <DataTable<Row>
            keyExtractor={n => String(n.entity_id ?? n.id ?? 'node')}
            data={nodes as Row[]}
            columns={[
              { key: 'id', header: 'Entity', render: n => <code className="text-xs text-text-primary">{fmt(n.entity_id ?? n.id)}</code> },
              { key: 'kind', header: 'Kind', render: n => <Badge variant="default" size="sm">{fmt(n.kind ?? n.type)}</Badge> },
              { key: 'actor', header: 'Actor class', render: n => n.actor_class ? <Badge variant="default" size="sm">{fmt(n.actor_class)}</Badge> : <span className="text-text-muted">—</span> },
              { key: 'trust', header: 'Trust', render: n => n.trust_score !== undefined ? <Badge variant={Number(n.trust_score) > 0.6 ? 'success' : 'warning'} size="sm">{fmtScore(n.trust_score)}</Badge> : <span className="text-text-muted">—</span> },
              { key: 'inbound', header: 'Inbound', render: n => fmt(n.inbound_count) },
              { key: 'outbound', header: 'Outbound', render: n => fmt(n.outbound_count) },
            ]}
          />
        </Section>
      )}
    </div>
  );
}

// ── Profile page ──────────────────────────────────────────────────────────────

export function UserProfilePage() {
  const { id: userId = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: summary, isLoading: headerLoading } = useUserProfile(userId);
  const s = asRecord(summary);

  if (!userId) {
    return <ErrorState title="No user ID" message="Please select a user from the list." />;
  }

  return (
    <div className="p-8 space-y-6">
      {/* Back + header */}
      <div className="flex items-start gap-4">
        <Button variant="ghost" size="sm" onClick={() => navigate('/users')}>← Users</Button>
        <div className="flex-1">
          {headerLoading ? (
            <Skeleton className="h-6 w-48" />
          ) : (
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-semibold text-text-primary font-mono">{userId}</h1>
              {!!s.loyalty_tier && s.loyalty_tier !== 'none' && (
                <Badge variant="warning">{fmt(s.loyalty_tier)}</Badge>
              )}
              {!!s.churn_risk && (
                <Badge variant={s.churn_risk === 'low' ? 'success' : s.churn_risk === 'churned' ? 'danger' : 'warning'}>
                  {`${fmt(s.churn_risk)} churn risk`}
                </Badge>
              )}
              {s.trust_score !== undefined && (
                <Badge variant={Number(s.trust_score) > 0.6 ? 'success' : 'warning'}>
                  Trust {fmtScore(s.trust_score)}
                </Badge>
              )}
              {s.risk_score !== undefined && (
                <Badge variant={Number(s.risk_score) > 0.5 ? 'danger' : 'success'}>
                  Risk {fmtScore(s.risk_score)}
                </Badge>
              )}
            </div>
          )}
          {!!s.last_seen_at && (
            <p className="text-sm text-text-secondary mt-0.5">Last seen {relTime(s.last_seen_at as string)}</p>
          )}
        </div>
      </div>

      {/* Tabbed content */}
      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="sessions">Sessions & Devices</TabsTrigger>
          <TabsTrigger value="journeys">Journeys</TabsTrigger>
          <TabsTrigger value="wallets">Web3 Wallets</TabsTrigger>
          <TabsTrigger value="financials">Financials</TabsTrigger>
          <TabsTrigger value="behavioral">Behavior</TabsTrigger>
          <TabsTrigger value="attribution">Attribution</TabsTrigger>
          <TabsTrigger value="relationships">Graph</TabsTrigger>
        </TabsList>

        <TabsContent value="overview"><OverviewTab userId={userId} /></TabsContent>
        <TabsContent value="sessions"><SessionsTab userId={userId} /></TabsContent>
        <TabsContent value="journeys"><JourneysTab userId={userId} /></TabsContent>
        <TabsContent value="wallets"><WalletsTab userId={userId} /></TabsContent>
        <TabsContent value="financials"><FinancialsTab userId={userId} /></TabsContent>
        <TabsContent value="behavioral"><BehavioralTab userId={userId} /></TabsContent>
        <TabsContent value="attribution"><AttributionTab userId={userId} /></TabsContent>
        <TabsContent value="relationships"><RelationshipsTab userId={userId} /></TabsContent>
      </Tabs>
    </div>
  );
}
