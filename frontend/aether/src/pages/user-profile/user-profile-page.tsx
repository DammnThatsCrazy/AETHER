import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader,
  DataTable, EmptyState, ErrorState, EvidenceDrawer, FreshnessIndicator,
  GlyphIcon, LoadingState, Modal, ModalBody, ModalFooter, ModalHeader,
  Skeleton, StatusIndicator, Tabs, TabsContent, TabsList, TabsTrigger,
  TerminalSeparator, TimeWindowSelector, formatUSD, formatCount, formatDecimal, useTimeContext, useToast,
} from '@aether/ui';
import type { TimeWindow } from '@aether/ui';
import { TruthBanner } from '@aether/ui/exploration';
import {
  useUserProfile, useUserSessions, useUserDevices, useUserPlatforms,
  useUserJourneys, useUserWallets, useUserFinancials, useUserRewards,
  useUserIdentifiers, useUserIntelligence, useUserBehavioral,
  useUserWhyExplain, useUserGraph, useUserCluster, useUserSemantic,
  useUserSocialIntelligence, useUserRecommendations,
  useUserTier, useUserAssetComposition, useUserPnl, useUserTradingProfile,
  useUserFunnel, useUserTimeToConvert, useUserJourneyEconomics, useUserDevicePerformance,
  useUserProtocolMetrics, useUserGovernanceActivity,
  useUserQuality, useUserDataFreshness, useUserWeb2Profile,
} from '@aether-app/features/users/use-user-profile';
import { useUnifiedJourney, TouchpointEvidenceInspector } from '@aether-app/features/journey';
import { api } from '@aether-app/lib/api/endpoints';
import {
  sourceClassLabel,
  humanizeRegistryValue,
  touchpointEvidenceSummary,
} from '@aether-app/lib/traffic-source';
import { OutcomeLedgerPanel } from '@aether-app/components/outcome-ledger-panel';
import { ProfileExplorationPanel } from '@aether-app/features/profile360';

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

function humanizeFamily(v: unknown): string {
  return fmt(v, 'recommendation').replace(/_/g, ' ');
}

function fmtScore(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return `${Math.round(Number(v) * 100)}`;
}

// Honest ratio→percentage: an absent confidence/weight is unknown, not 0%.
// Render "—" instead of coercing a missing rate into a misleading "0%".
function fmtPct(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return `${Math.round(n * 100)}%`;
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

// ── Communications tab (Communications Intelligence) ─────────────────────────

function CommunicationsTab({ userId }: { userId: string }) {
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [counts, setCounts] = useState<Record<string, unknown>>({});
  const [state, setState] = useState<Record<string, unknown> | null>(null);
  const [humanOnly, setHumanOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      api.comms.entityCommunications(userId, humanOnly ? { human_qualified: true, limit: 50 } : { limit: 50 }),
      api.comms.entityCommunicationState(userId),
    ])
      .then(([comms, commState]) => {
        if (!active) return;
        const c = asRecord(comms);
        setItems(asList(c.items) as Record<string, unknown>[]);
        setCounts(asRecord(c.counts));
        setState(asRecord(asRecord(commState).communication_state));
      })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [userId, humanOnly]);

  if (loading) return <LoadingState lines={6} />;
  if (error) return <ErrorState title="Communications unavailable" message={error} />;

  const s = state ?? {};

  return (
    <div className="space-y-6">
      <Section title="Communication summary">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <Stat label="Communications" value={fmt(counts.communications ?? 0)} />
          <Stat label="Email campaigns" value={fmt(counts.email_campaigns ?? 0)} />
          <Stat label="Human clicks" value={fmt(counts.human_clicks ?? 0)} />
          <Stat label="Replies" value={fmt(counts.replies ?? 0)} />
          <Stat label="Outcomes" value={fmt(counts.communication_outcomes ?? 0)} />
        </div>
      </Section>

      <Section title="Communication state (email)">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label="Subscription" value={
            <Badge variant={s.subscription_status === 'subscribed' ? 'success' : s.subscription_status === 'unknown' ? 'default' : 'warning'} size="sm">
              {fmt(s.subscription_status)}
            </Badge>
          } />
          <Stat label="Deliverability" value={
            <Badge variant={s.deliverability_status === 'deliverable' ? 'success' : s.deliverability_status === 'hard_bounced' ? 'danger' : 'default'} size="sm">
              {fmt(s.deliverability_status)}
            </Badge>
          } />
          <Stat label="Delivered" value={fmt(s.total_delivered ?? 0)} />
          <Stat label="Human clicks" value={fmt(s.total_human_clicks ?? 0)} />
          <Stat label="Replies" value={fmt(s.total_replies ?? 0)} />
          <Stat label="Last engagement" value={s.last_human_engagement_at ? relTime(String(s.last_human_engagement_at)) : '—'} />
          <Stat label="Last reply" value={s.last_reply_at ? relTime(String(s.last_reply_at)) : '—'} />
          <Stat label="Suppression" value={s.suppression_scope ? <Badge variant="warning" size="sm">{fmt(s.suppression_scope)}</Badge> : 'none'} />
        </div>
      </Section>

      <Section title="Communications timeline">
        <label className="flex items-center gap-2 text-xs text-text-secondary w-fit cursor-pointer">
          <input
            type="checkbox"
            checked={humanOnly}
            onChange={e => setHumanOnly(e.target.checked)}
            aria-label="Show human-qualified engagement only"
          />
          Human-qualified engagement only
        </label>
        {!items.length
          ? <EmptyState title="No communications" description="No communication events observed for this entity yet." />
          : (
            <DataTable
              data={items}
              keyExtractor={r => String(r.communication_fact_id)}
              columns={[
                { key: 'event_type', header: 'Event', render: r => String(r.event_type ?? '—') },
                { key: 'channel', header: 'Channel', render: r => String(r.channel ?? '—') },
                { key: 'message_category', header: 'Category', render: r => String(r.message_category ?? '—') },
                { key: 'external_message_id', header: 'Message', render: r => String(r.external_message_id ?? '—') },
                {
                  key: 'suspected_machine_activity', header: 'Engagement',
                  render: r => r.suspected_machine_activity
                    ? <Badge variant="warning" size="sm">suspected machine</Badge>
                    : r.engagement_strength
                      ? <Badge variant="success" size="sm">{String(r.engagement_strength)}</Badge>
                      : <span className="text-text-muted text-xs">—</span>,
                },
                { key: 'provider', header: 'Provider', render: r => String(r.provider ?? '—') },
                { key: 'occurred_at', header: 'When', render: r => r.occurred_at ? relTime(String(r.occurred_at)) : '—' },
              ]}
            />
          )
        }
      </Section>
    </div>
  );
}

// ── Semantic sentiment section (Profile360 semantic dimension) ────────────────

function stanceVariant(stance: string): 'success' | 'warning' | 'danger' | 'default' {
  if (stance.endsWith('supportive')) return 'success';
  if (stance.endsWith('opposed')) return 'danger';
  if (stance === 'mixed' || stance === 'uncertain') return 'warning';
  return 'default';
}

export function SemanticSentimentSection({ userId }: { userId: string }) {
  const { data, isLoading, error } = useUserSemantic(userId);
  const sem = data?.semantic;
  const computed = !!data?.computed && !!sem && sem.semantic_summary !== 'insufficient_data';
  const stances = computed
    ? Object.entries(sem.stance_distribution).sort(([, a], [, b]) => b - a)
    : [];

  return (
    <Section title="Semantic sentiment" loading={isLoading} error={error}>
      {!computed ? (
        <EmptyState
          title="No semantic signal yet"
          description="Not enough semantic observations have been ingested to compute a durable semantic state for this profile."
        />
      ) : (
        <div className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <Badge variant={sem.confidence >= 0.7 ? 'success' : sem.confidence >= 0.4 ? 'warning' : 'danger'} size="sm">
              {`Confidence ${Math.round(sem.confidence * 100)}%`}
            </Badge>
            <span className="text-xs text-text-muted">
              {sem.observation_count} observations · {sem.unique_source_count} sources
            </span>
            <FreshnessIndicator computedAt={sem.computed_at} className="ml-auto" />
          </div>

          <p className="text-sm text-text-primary">{sem.semantic_summary}</p>

          {sem.active_topics.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              <span className="text-xs text-text-secondary">Active topics:</span>
              {sem.active_topics.map(topic => (
                <Badge key={topic} variant="default" size="sm">{topic}</Badge>
              ))}
            </div>
          )}

          {stances.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-text-secondary mb-2">Stance distribution</h4>
              <div className="space-y-1.5">
                {stances.map(([stance, weight]) => {
                  const pct = Math.round(weight * 100);
                  return (
                    <div key={stance} className="flex items-center gap-3">
                      <span className="w-40 flex-shrink-0">
                        <Badge variant={stanceVariant(stance)} size="sm">{stance.replace(/_/g, ' ')}</Badge>
                      </span>
                      <div className="flex-1 bg-surface-raised rounded-full h-2">
                        <div className="bg-accent h-2 rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-xs text-text-secondary w-10 text-right">{pct}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
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
      <ProfileExplorationPanel entityId={userId} />

      {/* Scores */}
      <Section title="Intelligence scores" loading={il} error={ie}>
        <div className="grid grid-cols-3 gap-3">
          {scoreBadge(i.trust_score as number, 'Trust')}
          {scoreBadge(i.risk_score as number, 'Risk', true)}
          {scoreBadge(i.anomaly_score as number, 'Anomaly', true)}
        </div>
      </Section>

      {/* Semantic sentiment (Profile360 semantic dimension) */}
      <SemanticSentimentSection userId={userId} />

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

  const sessions = asList(asRecord(data).items ?? asRecord(data).sessions ?? data);
  const devices = asList(asRecord(devicesData).items ?? asRecord(devicesData).devices ?? devicesData);

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
  const journeys = asList(asRecord(data).items ?? asRecord(data).journeys ?? data);

  type JourneyRow = Record<string, unknown>;

  return (
    <Section title="Cross-session journeys" loading={isLoading} error={error}>
      {journeys.length === 0
        ? <EmptyState title="No journeys" description="No multi-step journeys have been tracked yet." />
        : journeys.map((j, ji) => {
            const jr = asRecord(j);
            const steps = asList(jr.timeline ?? jr.steps);
            const handoffs = asList(jr.handoffs);
            const pct = Math.round(Number(jr.completion_rate ?? 0) * 100);
            return (
              <Card key={ji} className="mb-4">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-text-primary">Journey {ji + 1}</span>
                      {!!jr.converted && <Badge variant="success" size="sm">Converted</Badge>}
                      {!!jr.entry_channel && <Badge variant="default" size="sm">{fmt(jr.entry_channel)}</Badge>}
                      {!!jr.status && <Badge variant={jr.status === 'completed' ? 'success' : jr.status === 'abandoned' ? 'danger' : 'warning'} size="sm">{fmt(jr.status)}</Badge>}
                      {jr.confidence !== undefined && <Badge variant={Number(jr.confidence) >= 0.8 ? 'success' : Number(jr.confidence) >= 0.6 ? 'warning' : 'danger'} size="sm">confidence {Math.round(Number(jr.confidence) * 100)}%</Badge>}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-text-secondary">
                      <span>{pct}% complete</span>
                      <span>{fmtDuration(jr.total_time_ms as number)}</span>
                      <span>{relTime(jr.started_at as string)}</span>
                      <span>{handoffs.length} handoffs</span>
                    </div>
                  </div>
                  {/* Completion bar */}
                  <div className="h-1 bg-surface-overlay rounded-full mt-2">
                    <div className="h-1 bg-accent rounded-full transition-all" style={{ width: `${pct}%` }} />
                  </div>
                </CardHeader>
                <CardContent>
                  {handoffs.length > 0 && (
                    <div className="mb-3 rounded-md border border-border-default bg-surface-raised p-3 text-xs text-text-secondary">
                      <div className="font-medium text-text-primary mb-1">Cross-device handoffs</div>
                      {handoffs.map((h, hi) => {
                        const hr = asRecord(h);
                        return <div key={hi} className="flex flex-wrap gap-2">
                          <span>{fmt(hr.from_device_type)} → {fmt(hr.to_device_type)}</span>
                          <span>sessions {fmt(hr.from_session_id)} → {fmt(hr.to_session_id)}</span>
                          <span>confidence {fmtPct(hr.confidence)}</span>
                          <span>{asList(hr.confidence_signals).join(' + ') || 'signals pending'}</span>
                        </div>;
                      })}
                    </div>
                  )}
                  <DataTable<JourneyRow>
                    keyExtractor={s => `step-${ji}-${String(s._stepNum ?? s.step_name ?? s.event_type ?? 'step')}`}
                    data={steps.map((s, idx) => ({ ...asRecord(s), _stepNum: idx + 1 })) as JourneyRow[]}
                    emptyMessage="No steps"
                    columns={[
                      { key: 'n', header: '#', render: s => <span className="text-text-muted">{fmt(s._stepNum)}</span> },
                      { key: 'name', header: 'Step', render: s => <span className="font-medium text-text-primary">{fmt(s.step_name ?? s.event_type)}</span> },
                      { key: 'device', header: 'Device', render: s => <span className="text-text-secondary text-xs">{fmt(s.device_type ?? s.platform)}</span> },
                      { key: 'signals', header: 'Signals', render: s => <span className="text-text-secondary text-xs">{asList(s.confidence_signals).join(' + ') || '—'}</span> },
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
  const timeCtx = useTimeContext();
  const { data, isLoading, error } = useUserWallets(userId);
  const wallets = asList(asRecord(data).items ?? asRecord(data).wallets ?? data);

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
                          ${formatDecimal(Number(portfolio), timeCtx, { maximumFractionDigits: 0 })}
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
                          { key: 'balance', header: 'Balance', render: t => <span className="font-mono text-text-primary">{formatDecimal(Number(t.balance ?? 0), timeCtx, { maximumFractionDigits: 4 })}</span> },
                          { key: 'value', header: 'Value (USD)', render: t => t.value_usd !== undefined ? <span className="text-text-primary">${formatDecimal(Number(t.value_usd), timeCtx, { maximumFractionDigits: 2 })}</span> : <span className="text-text-muted">—</span> },
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
                          { key: 'volume', header: 'Volume', render: p => p.volume_usd !== undefined ? <span>${formatDecimal(Number(p.volume_usd), timeCtx, { maximumFractionDigits: 0 })}</span> : <span className="text-text-muted">—</span> },
                          { key: 'position', header: 'Position', render: p => p.current_position_usd !== undefined ? <span className="text-success">${formatDecimal(Number(p.current_position_usd), timeCtx, { maximumFractionDigits: 0 })}</span> : <span className="text-text-muted">—</span> },
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
                          { key: 'value', header: 'Value', render: t => t.value_usd !== undefined ? <span>${formatDecimal(Number(t.value_usd), timeCtx, { maximumFractionDigits: 2 })}</span> : <span className="text-text-muted">—</span> },
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
  const timeCtx = useTimeContext();
  const { data, isLoading, error } = useUserFinancials(userId);
  const f = asRecord(data);
  const web2 = asRecord(f.web2);
  const web3 = asRecord(f.web3);
  const counterparties = asList(f.top_counterparties ?? web3.top_counterparties ?? web2.top_counterparties);
  type Row = Record<string, unknown>;

  return (
    <Section title="Financial profile (Web2 + Web3)" loading={isLoading} error={error}>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        <Stat label="Lifetime value" value={f.lifetime_value_usd !== undefined ? `$${formatCount(Number(f.lifetime_value_usd), timeCtx)}` : '—'} />
        <Stat label="Total inflow" value={f.total_inflow_usd !== undefined ? `$${formatCount(Number(f.total_inflow_usd), timeCtx)}` : web3.total_inflow_usd !== undefined ? `$${formatCount(Number(web3.total_inflow_usd), timeCtx)}` : '—'} />
        <Stat label="Total outflow" value={f.total_outflow_usd !== undefined ? `$${formatCount(Number(f.total_outflow_usd), timeCtx)}` : web3.total_outflow_usd !== undefined ? `$${formatCount(Number(web3.total_outflow_usd), timeCtx)}` : '—'} />
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
              { key: 'volume', header: 'Volume', render: c => c.volume_usd !== undefined ? <span>${formatDecimal(Number(c.volume_usd), timeCtx, { maximumFractionDigits: 0 })}</span> : <span className="text-text-muted">—</span> },
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
  const signals = asList(behavData?.signals);
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
      <TruthBanner
        status={bl ? 'loading' : be ? 'error' : 'ready'}
        surfaceLabel="Behavioral intelligence"
        error={be}
      />
      {/* Why explanation */}
      <Section title="Why is this entity notable?" loading={wl} error={we}>
        {!!why.behavioral_context && (
          <p className="text-sm text-text-secondary mb-3">{fmt(why.behavioral_context)}</p>
        )}
        {why.overall_confidence !== undefined && (
          <p className="text-xs text-text-muted mb-3">Overall confidence: {Math.round(Number(why.overall_confidence) * 100)}%</p>
        )}
        {topSignals.length === 0
          ? <p className="text-xs text-text-muted">No behavioral signals were returned.</p>
          : topSignals.map((sig, i) => (
              <SignalRowWithEvidence key={i} sig={asRecord(sig)} severityVariant={severityVariant} />
            ))
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
            { key: 'conf', header: 'Confidence', render: s => fmtPct(s.confidence) },
            { key: 'source_silence', header: 'Silent?', render: s => s.is_source_silence ? <Badge variant="warning" size="sm">Silent</Badge> : <span className="text-text-muted">No</span> },
            { key: 'explanation', header: 'Explanation', render: s => <span className="text-text-secondary text-xs">{fmt(s.explanation)}</span> },
          ]}
        />
      </Section>
    </div>
  );
}

// ── Evidence drawer wrapper for a signal row ─────────────────────────────────

function SignalRowWithEvidence({ sig, severityVariant }: {
  sig: Record<string, unknown>;
  severityVariant: (sev: string) => 'danger' | 'warning' | 'success' | 'default';
}) {
  const [open, setOpen] = useState(false);
  const evidenceRefs = (sig.evidence_refs as Array<{ event_id: string; description?: string; timestamp?: string }> | undefined) ?? [];

  return (
    <div>
      <div className="border border-border-default rounded-md p-3 space-y-1">
        <div className="flex items-center gap-2">
          <Badge variant={severityVariant(fmt(sig.severity))} size="sm">{fmt(sig.severity)}</Badge>
          <Badge variant="default" size="sm">{fmt(sig.signal_type)}</Badge>
          {!!sig.family && <Badge variant="default" size="sm">{fmt(sig.family)}</Badge>}
          <span className="text-xs text-text-muted ml-auto">Confidence: {fmtPct(sig.confidence)}</span>
          {evidenceRefs.length > 0 && (
            <button
              onClick={() => setOpen(v => !v)}
              className="text-xs font-mono text-accent hover:underline ml-2"
              aria-label="Show evidence"
            >
              {open ? '[−] hide' : '[>] evidence'}
            </button>
          )}
        </div>
        <p className="text-sm text-text-primary">{fmt(sig.explanation)}</p>
        {sig.expected !== undefined && (
          <p className="text-xs text-text-muted">Expected: {fmt(sig.expected)} → Observed: {fmt(sig.observed)}</p>
        )}
      </div>
      <EvidenceDrawer
        signalName={fmt(sig.signal_type)}
        evidence={evidenceRefs}
        open={open}
        onClose={() => setOpen(false)}
      />
    </div>
  );
}

// ── Attribution "Where" tab ───────────────────────────────────────────────────

function AttributionTab({ userId }: { userId: string }) {
  const { steps, loading, error } = useUnifiedJourney({ profileId: userId, limit: 100 });
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);

  type Row = Record<string, unknown>;
  const touchpoints = steps as unknown as Row[];

  // Steps arrive ordered by step_position (ascending). First-touch is the
  // earliest observed touch, latest-touch the most recent — used by the
  // evidence inspector to place a touchpoint in the journey.
  const firstTouchId = touchpoints.length > 0 ? String(touchpoints[0]?.step_id ?? '') : '';
  const latestTouchId = touchpoints.length > 0 ? String(touchpoints[touchpoints.length - 1]?.step_id ?? '') : '';
  const selectedId = selected ? String(selected.step_id ?? '') : '';

  return (
    <Section title="Attribution journey (where conversions came from)" loading={loading} error={error}>
      <p className="text-xs text-text-muted mb-2">Select a touchpoint to inspect its full classification evidence.</p>
      <DataTable<Row>
        keyExtractor={tp => String(tp.step_id ?? 'touchpoint')}
        data={touchpoints as Row[]}
        emptyMessage="No touchpoints recorded"
        onRowClick={tp => setSelected(tp)}
        columns={[
          { key: 'channel', header: 'Channel', render: tp => <Badge variant="default" size="sm">{fmt(tp.channel)}</Badge> },
          { key: 'source', header: 'Source', render: tp => <span className="text-text-secondary">{fmt(tp.source)}</span> },
          // Canonical registry label — legacy "direct" normalizes to
          // direct_unknown and renders "Direct / Unknown" (never "Typed URL").
          // Hovering the cell shows the evidence detail (entry method, proof,
          // verification, conflicts) where those optional fields are present.
          { key: 'source_class', header: 'Source class', render: tp => (
            <span title={touchpointEvidenceSummary(tp) || undefined}>{sourceClassLabel(tp.source_class)}</span>
          ) },
          { key: 'proof', header: 'Proof', render: tp => (
            tp.proof_level
              ? <Badge variant="default" size="sm">{humanizeRegistryValue(tp.proof_level)}</Badge>
              : <span className="text-text-muted">—</span>
          ) },
          { key: 'entry_method', header: 'Entry method', render: tp => (
            tp.entry_method
              ? <span className="text-text-secondary text-xs">{humanizeRegistryValue(tp.entry_method)}</span>
              : <span className="text-text-muted">—</span>
          ) },
          { key: 'ai', header: 'AI provider / product', render: tp => [tp.ai_provider, tp.ai_product].filter(Boolean).map(String).join(' / ') || '—' },
          { key: 'mediation', header: 'Mediation', render: tp => fmt(tp.referral_mediation_type) },
          { key: 'actor', header: 'Actor', render: tp => fmt(tp.actor_type) },
          { key: 'role', header: 'Journey role', render: tp => fmt(tp.journey_role) },
          { key: 'verification', header: 'Verification', render: tp => (
            <span>{fmt(tp.verification_level)}{tp.evidence_confidence != null ? ` · ${Math.round(Number(tp.evidence_confidence) * 100)}%` : ''}</span>
          ) },
          { key: 'campaign', header: 'Campaign', render: tp => tp.campaign_id ? <span className="text-text-primary">{fmt(tp.campaign_id)}</span> : <span className="text-text-muted">—</span> },
          { key: 'event', header: 'Event type', render: tp => fmt(tp.activity_type) },
          { key: 'revenue', header: 'Net revenue', render: tp => formatUSD(tp.attributed_net_revenue as string | number | null | undefined, { fallback: '—' }) },
          { key: 'when', header: 'When', render: tp => relTime(tp.occurred_at as string) },
          { key: 'evidence', header: 'Evidence', render: tp => (
            <button
              type="button"
              onClick={e => { e.stopPropagation(); setSelected(tp); }}
              className="text-xs font-mono text-accent hover:underline"
              aria-label="Inspect touchpoint evidence"
            >
              [&gt;] inspect
            </button>
          ) },
        ]}
      />
      <TouchpointEvidenceInspector
        touchpoint={selected}
        open={selected !== null}
        onClose={() => setSelected(null)}
        isFirstTouch={selectedId !== '' && selectedId === firstTouchId}
        isLatestTouch={selectedId !== '' && selectedId === latestTouchId}
      />
    </Section>
  );
}

// ── Relationships / Graph tab ─────────────────────────────────────────────────

function RelationshipsTab({ userId }: { userId: string }) {
  const timeCtx = useTimeContext();
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
          ? <p className="text-xs text-text-muted">No identity-cluster evidence was returned.</p>
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
                  { key: 'conf', header: 'Membership', render: m => fmtPct(m.membership_confidence) },
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
            { key: 'weight', header: 'Weight', render: e => fmtPct(e.weight) },
            { key: 'conf', header: 'Confidence', render: e => fmtPct(e.confidence) },
            { key: 'inferred', header: 'Source', render: e => <Badge variant={e.is_inferred ? 'warning' : 'success'} size="sm">{e.is_inferred ? 'Inferred' : 'Explicit'}</Badge> },
            { key: 'volume', header: 'Volume', render: e => e.volume_usd !== undefined ? <span>${formatDecimal(Number(e.volume_usd), timeCtx, { maximumFractionDigits: 0 })}</span> : <span className="text-text-muted">—</span> },
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

// ── Social Intelligence tab ────────────────────────────────────────────────────

const SOCIAL_PLATFORMS = [
  'twitter', 'youtube', 'instagram', 'tiktok', 'reddit',
  'linkedin', 'spotify', 'telegram', 'discord', 'github', 'farcaster', 'lens',
] as const;

const PLATFORM_LABELS: Record<string, string> = {
  twitter: 'Twitter / X', youtube: 'YouTube', instagram: 'Instagram',
  tiktok: 'TikTok', reddit: 'Reddit', linkedin: 'LinkedIn',
  spotify: 'Spotify', telegram: 'Telegram', discord: 'Discord',
  github: 'GitHub', farcaster: 'Farcaster', lens: 'Lens',
};

function SocialTab({ userId, window }: { userId: string; window: TimeWindow }) {
  const timeCtx = useTimeContext();
  const { data, isLoading, error } = useUserSocialIntelligence(userId, window);

  if (isLoading) return <LoadingState lines={6} />;
  if (error) return <ErrorState message="Failed to load social intelligence" />;

  const influenceVariant = data?.influence_level === 'high' ? 'accent' : 'default';

  const platformMap = new Map(
    (data?.platforms ?? []).map(p => [p.platform, p])
  );

  return (
    <div className="space-y-4">
      {/* Influence summary */}
      <div className="flex items-center gap-4 flex-wrap">
        {data?.influence_level && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted font-mono">Influence</span>
            <Badge variant={influenceVariant} size="sm">{data.influence_level.toUpperCase()}</Badge>
          </div>
        )}
        {data?.total_followers_deduped != null && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted font-mono">Total reach (deduped)</span>
            <span className="text-xl font-mono text-accent">{formatCount(data.total_followers_deduped, timeCtx)}</span>
          </div>
        )}
        {data?.computed_at && (
          <FreshnessIndicator computedAt={data.computed_at} className="ml-auto" />
        )}
      </div>

      {/* 12-platform grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {SOCIAL_PLATFORMS.map(platform => {
          const p = platformMap.get(platform);
          const linked = !!p?.handle;
          return (
            <div
              key={platform}
              className={`border rounded-md p-3 ${linked ? 'border-border-default bg-surface-raised' : 'border-border-subtle bg-surface-base opacity-50'}`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-text-primary">{PLATFORM_LABELS[platform]}</span>
                {p?.verified && <Badge variant="success" size="sm">✓</Badge>}
              </div>
              {linked ? (
                <div className="space-y-1">
                  <p className="text-xs font-mono text-accent">@{p.handle}</p>
                  {p.followers != null && (
                    <p className="text-xs text-text-secondary">
                      {formatCount(p.followers, timeCtx)} followers
                      {p.engagement_rate != null && ` · ${(p.engagement_rate * 100).toFixed(1)}% eng.`}
                    </p>
                  )}
                  {p.content_count != null && (
                    <p className="text-xs text-text-muted">{formatCount(p.content_count, timeCtx)} posts</p>
                  )}
                </div>
              ) : (
                <p className="text-xs text-text-muted font-mono">Not linked</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Recommendation cards ───────────────────────────────────────────────────────

function RecommendationCards({ userId }: { userId: string }) {
  const { toast } = useToast();
  const { data, isLoading } = useUserRecommendations(userId);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [actionLoading, setActionLoading] = useState(false);

  // Backend envelope: { items: [...] } — filter to only pending_review items
  const recs = (data?.items ?? []).filter(r => r.status === 'pending_review');
  if (isLoading) return <LoadingState lines={3} />;
  if (recs.length === 0) return null;

  async function handleApprove(id: string) {
    setActionLoading(true);
    try {
      await api.recommendations.approve(id, userId);
      toast.success('Recommendation approved');
      setConfirmId(null);
    } catch {
      toast.error('Approval failed — please try again');
    } finally {
      setActionLoading(false);
    }
  }

  async function handleReject(id: string, reason: string) {
    if (!reason.trim()) { toast.error('Please enter a reason for rejection'); return; }
    setActionLoading(true);
    try {
      await api.recommendations.reject(id, userId, reason.trim());
      toast.success('Recommendation rejected');
      setRejectId(null);
      setRejectReason('');
    } catch {
      toast.error('Rejection failed — please try again');
    } finally {
      setActionLoading(false);
    }
  }

  return (
    <div className="space-y-3 mb-6">
      <TerminalSeparator label="pending recommendations" />
      {recs.map(rec => (
        <div key={rec.id} className="border border-accent/30 bg-surface-raised rounded-md p-4 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <GlyphIcon glyph="[>]" className="text-accent" />
              <span className="text-sm font-medium text-text-primary">{rec.action} on {rec.platform}</span>
              <Badge variant="default" size="sm">{humanizeFamily(asRecord(rec).recommendation_type ?? asRecord(rec).family)}</Badge>
            </div>
            <Badge variant="accent" size="sm">{Math.round(rec.confidence * 100)}% confidence</Badge>
          </div>
          {rec.creative_theme && (
            <p className="text-xs text-text-secondary">Theme: {rec.creative_theme}</p>
          )}
          {rec.estimated_bid != null && (
            <p className="text-xs text-text-muted font-mono">Est. bid: ${rec.estimated_bid.toFixed(2)} CPA</p>
          )}
          {rec.reasoning.length > 0 && (
            <ul className="space-y-0.5">
              {rec.reasoning.map((r, i) => (
                <li key={i} className="text-xs text-text-secondary flex items-start gap-1.5">
                  <GlyphIcon glyph="[·]" className="text-text-muted mt-0.5 flex-shrink-0" />
                  {r}
                </li>
              ))}
            </ul>
          )}
          <div className="flex gap-2 pt-1">
            <Button variant="danger" size="sm" onClick={() => setRejectId(rec.id)} disabled={actionLoading}>
              Reject
            </Button>
            <Button variant="primary" size="sm" onClick={() => setConfirmId(rec.id)} disabled={actionLoading}>
              Approve
            </Button>
          </div>
        </div>
      ))}

      {/* Confirm approve modal */}
      {confirmId && (
        <Modal open onClose={() => setConfirmId(null)}>
          <ModalHeader>
            <h2 className="text-sm font-medium font-mono">Confirm approval</h2>
          </ModalHeader>
          <ModalBody>
            <p className="text-sm text-text-secondary">
              This recommendation will be submitted for execution. This action cannot be undone.
            </p>
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setConfirmId(null)} disabled={actionLoading}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={() => void handleApprove(confirmId)} disabled={actionLoading}>
              {actionLoading ? '[···]' : 'Confirm approve'}
            </Button>
          </ModalFooter>
        </Modal>
      )}

      {/* Reject modal with required reason field */}
      {rejectId && (
        <Modal open onClose={() => { setRejectId(null); setRejectReason(''); }}>
          <ModalHeader>
            <h2 className="text-sm font-medium font-mono">Reject recommendation</h2>
          </ModalHeader>
          <ModalBody>
            <p className="text-sm text-text-secondary mb-3">
              Provide a reason for rejection. This will be recorded with the decision.
            </p>
            <input
              className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
              placeholder="Reason for rejection…"
              value={rejectReason}
              onChange={e => setRejectReason(e.target.value)}
              autoFocus
            />
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => { setRejectId(null); setRejectReason(''); }} disabled={actionLoading}>Cancel</Button>
            <Button variant="danger" size="sm" onClick={() => void handleReject(rejectId, rejectReason)} disabled={actionLoading || !rejectReason.trim()}>
              {actionLoading ? '[···]' : 'Confirm rejection'}
            </Button>
          </ModalFooter>
        </Modal>
      )}
    </div>
  );
}

// ── DeFi tab ───────────────────────────────────────────────────────────────────

type SimpleRow = Record<string, unknown>;

function DeFiTab({ userId, window }: { userId: string; window: string }) {
  const { data: tier, isLoading: tl, error: te } = useUserTier(userId, window);
  const { data: assets, isLoading: al, error: ae } = useUserAssetComposition(userId, window);
  const { data: pnl, isLoading: pl, error: pe } = useUserPnl(userId, window);
  const { data: trading, isLoading: ql, error: qe } = useUserTradingProfile(userId, window);

  const tierSummary = asRecord(asRecord(tier).summary ?? tier);
  const pnlSummary = asRecord(asRecord(pnl).summary ?? pnl);
  const assetList = asList(asRecord(assets).items ?? assets) as SimpleRow[];
  const tradingList = asList(asRecord(trading).items ?? trading) as SimpleRow[];

  return (
    <div className="space-y-6">
      <Section title="DeFi tier" loading={tl} error={te}>
        <div className="flex items-center gap-4">
          {tierSummary.tier
            ? <Badge variant="warning" size="sm">{fmt(tierSummary.tier)}</Badge>
            : <EmptyState title="No tier data" />}
          {tierSummary.percentile !== undefined && (
            <span className="text-xs text-text-secondary">Top {Math.round((1 - Number(tierSummary.percentile)) * 100)}%</span>
          )}
        </div>
      </Section>

      <Section title="Asset composition" loading={al} error={ae}>
        {assetList.length === 0
          ? <EmptyState title="No asset data" />
          : <DataTable<SimpleRow>
              keyExtractor={r => fmt(r.category) || String(Math.random())}
              data={assetList}
              emptyMessage="No assets"
              columns={[
                { key: 'category', header: 'Category', render: r => fmt(r.category) },
                { key: 'value_usd', header: 'USD Value', render: r => fmt(r.value_usd) },
                { key: 'percentage', header: '% Share', render: r => r.percentage != null ? `${Math.round(Number(r.percentage) * 100)}%` : '—' },
              ]}
            />
        }
      </Section>

      <Section title="PNL" loading={pl} error={pe}>
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Realized PNL" value={fmt(pnlSummary.realized_pnl_usd ?? pnlSummary.total_realized_pnl)} />
          <Stat label="Unrealized PNL" value={fmt(pnlSummary.unrealized_pnl_usd ?? pnlSummary.total_unrealized_pnl)} />
          <Stat label="TVL delta" value={fmt(pnlSummary.tvl_delta_usd ?? (asList(asRecord(pnl).items ?? pnl) as SimpleRow[])[0]?.tvl_delta)} />
        </div>
      </Section>

      <Section title="Trading profile" loading={ql} error={qe}>
        {tradingList.length === 0
          ? <EmptyState title="No trading data" />
          : <DataTable<SimpleRow>
              keyExtractor={r => `trading-${fmt(r.avg_slippage)}-${fmt(r.trade_count)}`}
              data={tradingList}
              emptyMessage="No trading data"
              columns={[
                { key: 'favorite_pairs', header: 'Pairs', render: r => {
                  const v = r.favorite_pairs;
                  if (Array.isArray(v)) {
                    return v.map((p: unknown) => {
                      if (p && typeof p === 'object') return (p as Record<string, unknown>).pair as string ?? '?';
                      return String(p);
                    }).filter(Boolean).join(', ') || '—';
                  }
                  return fmt(v);
                }},
                { key: 'protocol_loyalty', header: 'Protocol Loyalty', render: r => {
                  const v = r.protocol_loyalty;
                  if (Array.isArray(v)) {
                    return v.map((p: unknown) => {
                      if (p && typeof p === 'object') {
                        const { protocol_name, volume_pct } = p as Record<string, unknown>;
                        return `${protocol_name} ${Math.round(Number(volume_pct) * 100)}%`;
                      }
                      return String(p);
                    }).join(', ') || '—';
                  }
                  if (v && typeof v === 'object') {
                    const top = Object.entries(v as Record<string, unknown>).sort(([,a],[,b]) => Number(b) - Number(a)).slice(0,3);
                    return top.map(([k, pct]) => `${k} ${Math.round(Number(pct)*100)}%`).join(', ') || '—';
                  }
                  return fmt(v);
                }},
                { key: 'gas_strategy', header: 'Gas Strategy', render: r => {
                  const v = r.gas_strategy;
                  if (v && typeof v === 'object' && !Array.isArray(v)) {
                    return Object.entries(v as Record<string, unknown>).map(([k, val]) => `${k}: ${fmt(val)}`).join(', ') || '—';
                  }
                  return fmt(v);
                }},
                { key: 'avg_slippage', header: 'Slippage', render: r => fmt(r.avg_slippage) },
              ]}
            />
        }
      </Section>
    </div>
  );
}

// ── Funnel tab ─────────────────────────────────────────────────────────────────

function FunnelTab({ userId, window }: { userId: string; window: string }) {
  const { data: funnel, isLoading: fl, error: fe } = useUserFunnel(userId, window);
  const { data: ttc, isLoading: tl, error: te } = useUserTimeToConvert(userId, window);
  const { data: economics, isLoading: el, error: ee } = useUserJourneyEconomics(userId, window);
  const { data: devices, isLoading: dl, error: de } = useUserDevicePerformance(userId, window);

  const funnelEnv = asRecord(funnel);
  const stages = (asList(funnelEnv.items ?? funnel) as SimpleRow[]).filter(s => Number(s.count ?? 0) > 0);
  const ttcList = asList(asRecord(ttc).items ?? ttc) as SimpleRow[];
  const econList = asList(asRecord(economics).items ?? economics) as SimpleRow[];
  const deviceList = asList(asRecord(devices).items ?? devices) as SimpleRow[];

  return (
    <div className="space-y-6">
      <Section title="Conversion funnel" loading={fl} error={fe}>
        {stages.length === 0
          ? <EmptyState title="No funnel data" />
          : <div className="space-y-2">
              {stages.map((s, i) => {
                const pct = s.conversion_rate == null ? (i === 0 ? 100 : 0) : Number(s.conversion_rate) * 100;
                return (
                  <div key={i} className="flex items-center gap-3">
                    <span className="text-xs text-text-secondary w-24 shrink-0">{fmt(s.stage)}</span>
                    <div className="flex-1 bg-surface-raised rounded-full h-2">
                      <div className="bg-accent h-2 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-xs text-text-secondary w-12 text-right">{Math.round(pct)}%</span>
                    {s.drop_off_pct !== undefined && (
                      <span className="text-xs text-danger w-16 text-right">-{fmt(s.drop_off_pct)}%</span>
                    )}
                  </div>
                );
              })}
            </div>
        }
      </Section>

      <Section title="Time to convert" loading={tl} error={te}>
        {ttcList.length === 0
          ? <EmptyState title="No conversion time data" />
          : <DataTable<SimpleRow>
              keyExtractor={r => `${fmt(r.from_stage)}-${fmt(r.to_stage)}` || String(Math.random())}
              data={ttcList}
              emptyMessage="No data"
              columns={[
                { key: 'from_stage', header: 'From', render: r => fmt(r.from_stage) },
                { key: 'to_stage', header: 'To', render: r => fmt(r.to_stage) },
                { key: 'median_seconds', header: 'Median (s)', render: r => fmt(r.median_seconds) },
                { key: 'p90_seconds', header: 'P90 (s)', render: r => fmt(r.p90_seconds) },
              ]}
            />
        }
      </Section>

      <Section title="Journey economics" loading={el} error={ee}>
        {econList.length === 0
          ? <EmptyState title="No journey economics data" />
          : <DataTable<SimpleRow>
              keyExtractor={r => fmt(r.journey_id) || String(Math.random())}
              data={econList}
              emptyMessage="No data"
              columns={[
                { key: 'journey_id', header: 'Journey', render: r => fmt(r.journey_id) },
                { key: 'roas', header: 'ROAS', render: r => fmt(r.roas) },
                { key: 'cpa', header: 'CPA', render: r => fmt(r.cpa) },
                { key: 'ltv', header: 'LTV', render: r => fmt(r.ltv) },
                { key: 'retarget_score', header: 'Retarget', render: r => fmt(r.retarget_score) },
              ]}
            />
        }
      </Section>

      <Section title="Device performance" loading={dl} error={de}>
        {deviceList.length === 0
          ? <EmptyState title="No device performance data" />
          : <DataTable<SimpleRow>
              keyExtractor={r => fmt(r.device_type) || String(Math.random())}
              data={deviceList}
              emptyMessage="No data"
              columns={[
                { key: 'device_type', header: 'Device', render: r => fmt(r.device_type) },
                { key: 'conversion_rate', header: 'Conv. Rate', render: r => fmt(r.conversion_rate) },
                { key: 'avg_conversion_value', header: 'Avg Value', render: r => fmt(r.avg_conversion_value) },
              ]}
            />
        }
      </Section>
    </div>
  );
}

// ── Protocols tab ──────────────────────────────────────────────────────────────

function ProtocolsTab({ userId, window }: { userId: string; window: string }) {
  const { data: protocols, isLoading: pl, error: pe } = useUserProtocolMetrics(userId, window);
  const { data: governance, isLoading: gl, error: ge } = useUserGovernanceActivity(userId, window);

  const protocolList = asList(asRecord(protocols).items ?? protocols) as SimpleRow[];
  const govList = asList(asRecord(governance).items ?? governance) as SimpleRow[];

  return (
    <div className="space-y-6">
      <Section title="Protocol metrics" loading={pl} error={pe}>
        {protocolList.length === 0
          ? <EmptyState title="No protocol data" />
          : <DataTable<SimpleRow>
              keyExtractor={r => fmt(r.date) || String(Math.random())}
              data={protocolList}
              emptyMessage="No data"
              columns={[
                { key: 'date', header: 'Date', render: r => fmt(r.date) },
                { key: 'tvl_usd', header: 'TVL', render: r => fmt(r.tvl_usd) },
                { key: 'volume_usd', header: 'Volume', render: r => fmt(r.volume_usd) },
                { key: 'fee_revenue_usd', header: 'Fees', render: r => fmt(r.fee_revenue_usd) },
              ]}
            />
        }
      </Section>

      <Section title="Governance activity" loading={gl} error={ge}>
        {govList.length === 0
          ? <EmptyState title="No governance data" />
          : <DataTable<SimpleRow>
              keyExtractor={r => fmt(r.proposal_id) || String(Math.random())}
              data={govList}
              emptyMessage="No data"
              columns={[
                { key: 'proposal_id', header: 'Proposal', render: r => fmt(r.proposal_id) },
                { key: 'protocol', header: 'Protocol', render: r => fmt(r.protocol) },
                { key: 'vote', header: 'Vote', render: r => fmt(r.vote) },
                { key: 'voting_power', header: 'Voting Power', render: r => fmt(r.voting_power) },
              ]}
            />
        }
      </Section>
    </div>
  );
}

// ── Insights tab ───────────────────────────────────────────────────────────────

function InsightsTab({ userId, window }: { userId: string; window: string }) {
  const { data: quality, isLoading: ql, error: qe } = useUserQuality(userId);
  const { data: freshness, isLoading: fl, error: fe } = useUserDataFreshness(userId);
  const { data: web2, isLoading: wl, error: we } = useUserWeb2Profile(userId, window);

  const q = asRecord(quality);
  const dimensions = asList(asRecord(freshness).dimensions ?? freshness) as SimpleRow[];
  const w = asRecord(web2);
  const qualityDimensions = asList(asRecord(quality).dimensions ?? []) as SimpleRow[];

  const isConsentDenied = (we && (String(we).includes('403') || String(we).toLowerCase().includes('forbidden') || String(we).toLowerCase().includes('consent')))
    || (!we && !!asRecord(asRecord(web2).summary).consent_required);

  return (
    <div className="space-y-6">
      <Section title="Data quality" loading={ql} error={qe}>
        <div className="flex items-center gap-4 mb-3">
          {q.completeness !== undefined && (
            <Badge variant={Number(q.completeness) >= 0.7 ? 'success' : Number(q.completeness) >= 0.4 ? 'warning' : 'danger'}>
              Completeness {fmtScore(q.completeness)}%
            </Badge>
          )}
          {!!q.readiness_status && (
            <Badge variant={q.readiness_status === 'ready' ? 'success' : 'warning'}>
              {fmt(q.readiness_status)}
            </Badge>
          )}
        </div>
        {qualityDimensions.length > 0 && (
          <DataTable<SimpleRow>
            keyExtractor={r => fmt(r.name ?? r.dimension) || String(Math.random())}
            data={qualityDimensions}
            emptyMessage="No dimensions"
            columns={[
              { key: 'dimension', header: 'Dimension', render: r => fmt(r.name ?? r.dimension) },
              { key: 'score', header: 'Score', render: r => fmt(r.score) },
            ]}
          />
        )}
      </Section>

      <Section title="Data freshness" loading={fl} error={fe}>
        {dimensions.length === 0
          ? <EmptyState title="No freshness data" />
          : <DataTable<SimpleRow>
              keyExtractor={r => fmt(r.dimension ?? r.name) || String(Math.random())}
              data={dimensions}
              emptyMessage="No data"
              columns={[
                { key: 'dimension', header: 'Dimension', render: r => fmt(r.dimension ?? r.name) },
                { key: 'last_updated', header: 'Last Updated', render: r => r.last_updated ? relTime(r.last_updated as string) : '—' },
                { key: 'stale', header: 'Stale?', render: r => r.stale ? <Badge variant="danger" size="sm">Stale</Badge> : <Badge variant="success" size="sm">Fresh</Badge> },
              ]}
            />
        }
      </Section>

      <Section title="Web2 credit intelligence" loading={wl}>
        {isConsentDenied ? (
          <Card>
            <CardContent className="py-6 text-center space-y-2">
              <p className="text-sm font-medium text-text-primary">Credit consent required</p>
              <p className="text-xs text-text-secondary">Contact your administrator to grant access to credit intelligence data.</p>
            </CardContent>
          </Card>
        ) : we ? (
          <p className="text-xs text-danger">{String(we)}</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {(asList(w.items ?? []) as SimpleRow[]).map((item, i) => (
              Object.entries(item).filter(([k]) => !k.startsWith('_')).map(([k, v]) => (
                <Stat key={`${i}-${k}`} label={k.replace(/_/g, ' ')} value={fmt(v)} />
              ))
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

export function UserProfilePage() {
  const { id: userId = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [window, setWindow] = useState<TimeWindow>('30d');
  const { data: summary, isLoading: headerLoading, error: headerError } = useUserProfile(userId);
  const s = asRecord(summary);

  if (!userId) {
    return <ErrorState title="No user ID" message="Please select a user from the list." />;
  }

  if (headerError) {
    return <ErrorState title="Failed to load user profile" message={headerError} className="p-8" />;
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
              <TimeWindowSelector value={window} onChange={setWindow} className="ml-auto" />
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
          <TabsTrigger value="communications">Communications</TabsTrigger>
          <TabsTrigger value="social">Social</TabsTrigger>
          <TabsTrigger value="wallets">Web3 Wallets</TabsTrigger>
          <TabsTrigger value="financials">Financials</TabsTrigger>
          <TabsTrigger value="behavioral">Behavior</TabsTrigger>
          <TabsTrigger value="attribution">Attribution</TabsTrigger>
          <TabsTrigger value="relationships">Graph</TabsTrigger>
          <TabsTrigger value="outcomes">Outcomes</TabsTrigger>
          <TabsTrigger value="defi">DeFi</TabsTrigger>
          <TabsTrigger value="funnel">Funnel</TabsTrigger>
          <TabsTrigger value="protocols">Protocols</TabsTrigger>
          <TabsTrigger value="insights">Insights</TabsTrigger>
        </TabsList>

        <TabsContent value="overview"><OverviewTab userId={userId} /></TabsContent>
        <TabsContent value="sessions"><SessionsTab userId={userId} /></TabsContent>
        <TabsContent value="journeys">
          <RecommendationCards userId={userId} />
          <JourneysTab userId={userId} />
        </TabsContent>
        <TabsContent value="communications"><CommunicationsTab userId={userId} /></TabsContent>
        <TabsContent value="social"><SocialTab userId={userId} window={window} /></TabsContent>
        <TabsContent value="wallets"><WalletsTab userId={userId} /></TabsContent>
        <TabsContent value="financials"><FinancialsTab userId={userId} /></TabsContent>
        <TabsContent value="behavioral"><BehavioralTab userId={userId} /></TabsContent>
        <TabsContent value="attribution"><AttributionTab userId={userId} /></TabsContent>
        <TabsContent value="relationships"><RelationshipsTab userId={userId} /></TabsContent>
        <TabsContent value="outcomes"><OutcomeLedgerPanel entityId={userId} /></TabsContent>
        <TabsContent value="defi"><DeFiTab userId={userId} window={window} /></TabsContent>
        <TabsContent value="funnel"><FunnelTab userId={userId} window={window} /></TabsContent>
        <TabsContent value="protocols"><ProtocolsTab userId={userId} window={window} /></TabsContent>
        <TabsContent value="insights"><InsightsTab userId={userId} window={window} /></TabsContent>
      </Tabs>
    </div>
  );
}
