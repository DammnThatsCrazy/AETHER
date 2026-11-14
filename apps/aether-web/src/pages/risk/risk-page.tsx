import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { GlassPage } from '@aether-app/components/app-shell';
import {
  Eyebrow, InlineNotice, LinkButton, MetricTile, PrimaryButton, SecondaryButton, TonePill, toneColor,
} from '@aether-app/components/ae-ui';
import {
  EmptySlot, GlassSection, LoadingRow, OutlineChip, SegmentedTabs,
} from '@aether-app/components/ae-campaigns-geo-ui';
import { useCapabilityRiskFindings } from '@aether-app/features/agent-access';
import { useAuth } from '@aether-app/features/auth';
import {
  useRiskCases, useRiskDataQuality, useTransitionCase, type CaseStatus, type InvestigationCase,
} from '@aether-app/features/risk/use-risk';
import {
  CATEGORY_LABEL, NEXT_STATUSES, SEVERITIES, SEVERITY_LABEL, SEVERITY_TONE, STATUS_LABEL, STATUS_TONE,
  buildRegister, matches, relativeAge, subjectHref, type Category, type RiskItem, type SeverityFilter,
} from './risk-model';

/**
 * Risk (Claude Design handoff: Aether Risk) — what could go wrong and what is
 * being done about it. Aether observes; it does not change agents or data.
 *
 * Sources, all existing tenant reads:
 *   - agent capability risk findings (observed risk level per finding);
 *   - investigation cases (status only — the backend does not rate cases, so
 *     they appear as "Not rated", never with an invented severity);
 *   - the data-quality overview (the backend's own quality score and open
 *     drift counts by severity; individual drift events are not tenant-listable).
 *
 * Omitted from the design because no backend read exists: a composite
 * "posture score" (never computed here), the 30-day open-risk trend,
 * likelihood × impact ratings, owners and "accept the risk".
 */

type View = 'overview' | 'register';

const MUTE = { color: 'var(--ae-mute)' } as const;

const ACTION_LABEL: Partial<Record<CaseStatus, string>> = {
  triage: 'Move to triage',
  active: 'Start mitigation',
  escalated: 'Escalate',
  closed: 'Close case',
};

function Dot({ color, size = 10 }: { readonly color: string; readonly size?: number }) {
  return <span aria-hidden="true" className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: color }} />;
}

function itemColor(item: RiskItem): string {
  if (item.severity) return toneColor(SEVERITY_TONE[item.severity]);
  return item.kind === 'case' ? toneColor(STATUS_TONE[item.case.status]) : 'var(--ae-mute)';
}

function itemMeta(item: RiskItem, now: number): string {
  if (item.kind === 'finding') return `${CATEGORY_LABEL.agent} · ${item.finding.code}`;
  return `${CATEGORY_LABEL.case} · ${STATUS_LABEL[item.case.status]} · opened ${relativeAge(item.case.createdAt, now)}`;
}

function Unavailable({ what, onRetry }: { readonly what: string; readonly onRetry: () => void }) {
  return (
    <InlineNotice tone="ember">
      {what} {what.endsWith('s') ? 'are' : 'is'} unavailable right now.{' '}
      <button type="button" className="ae-focus underline" onClick={onRetry}>Try again</button>
    </InlineNotice>
  );
}

function RiskRow({ item, now, selected, onClick }: { readonly item: RiskItem; readonly now: number; readonly selected?: boolean; readonly onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={selected ? 'true' : undefined}
      className="ae-focus flex w-full items-center gap-3 rounded-[14px] px-2.5 py-3 text-left transition-colors hover:bg-[color:var(--ae-edge-soft)]"
      style={{ background: selected ? 'var(--ae-blue-tint)' : undefined }}
      data-testid="risk-row"
      data-risk-key={item.key}
    >
      <Dot color={itemColor(item)} />
      <span className="flex min-w-0 flex-1 flex-col leading-[1.3]">
        <span className="truncate text-[14px]" style={{ fontWeight: selected ? 500 : 400 }}>{item.title}</span>
        <span className="truncate text-[12px]" style={MUTE}>{itemMeta(item, now)}</span>
      </span>
      <span className="ae-mono shrink-0 text-[11px]" style={{ color: itemColor(item) }}>
        {item.severity ? SEVERITY_LABEL[item.severity] : 'Not rated'}
      </span>
    </button>
  );
}

// ── Detail ────────────────────────────────────────────────────────────────────

function CaseDetail({ c, now, tenantId, onChanged }: { readonly c: InvestigationCase; readonly now: number; readonly tenantId: string; readonly onChanged: () => void }) {
  const navigate = useNavigate();
  const transition = useTransitionCase(tenantId);
  const [failed, setFailed] = useState(false);
  const next = NEXT_STATUSES[c.status];

  async function move(status: CaseStatus) {
    setFailed(false);
    const result = await transition.mutate({ id: c.id, status });
    if (result === null) setFailed(true);
    else onChanged();
  }

  return (
    <>
      <span className="flex flex-col gap-1.5">
        <span className="flex flex-wrap items-center gap-2">
          <TonePill tone={STATUS_TONE[c.status]}>{STATUS_LABEL[c.status]}</TonePill>
          <span className="text-[12px]" style={MUTE}>
            Investigation · opened {relativeAge(c.createdAt, now)}{c.createdBy ? ` by ${c.createdBy}` : ''}
          </span>
        </span>
        <h2 className="text-[18px] font-medium leading-[1.3]">{c.title}</h2>
        <span className="text-[12px]" style={MUTE}>Severity is not rated for investigation cases.</span>
      </span>

      <div className="flex flex-col gap-1.5 rounded-[16px] px-3.5 py-3" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
        <Eyebrow>Evidence</Eyebrow>
        {c.evidence.length === 0 ? (
          <span className="text-[13px]" style={MUTE}>No evidence attached yet.</span>
        ) : (
          c.evidence.map(e => (
            <span key={e.id} className="flex justify-between gap-3 text-[13px]">
              <span className="min-w-0 truncate">{e.source}</span>
              <span className="shrink-0 whitespace-nowrap" style={MUTE}>
                {e.type}{e.observedAt ? ` · ${relativeAge(e.observedAt, now)}` : ''}
              </span>
            </span>
          ))
        )}
        {c.annotationCount > 0 && (
          <span className="text-[12px]" style={MUTE}>{c.annotationCount} note{c.annotationCount === 1 ? '' : 's'} on this case</span>
        )}
      </div>

      {c.subjects.length > 0 && (
        <span className="flex flex-wrap items-center gap-1.5" data-testid="risk-subjects">
          <span className="text-[11px]" style={MUTE}>Affected</span>
          {c.subjects.map(s => {
            const href = subjectHref(s.kind, s.id);
            const label = s.label ?? s.id;
            const chip = 'rounded-full border px-2.5 py-0.5 text-[12px]';
            return href ? (
              <Link key={`${s.kind}:${s.id}`} to={href} className={`${chip} ae-focus hover:underline`} style={{ borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)' }}>
                {label}
              </Link>
            ) : (
              <span key={`${s.kind}:${s.id}`} className={chip} style={{ borderColor: 'var(--ae-edge-soft)', color: 'var(--ae-mute)' }}>
                {s.kind} · {label}
              </span>
            );
          })}
        </span>
      )}

      {failed && <InlineNotice tone="ember">The case status could not be changed. Try again.</InlineNotice>}

      <div className="flex flex-wrap items-center gap-2 border-t pt-3" style={{ borderColor: 'var(--ae-edge-soft)' }}>
        {next.includes('active') && (
          <PrimaryButton onClick={() => void move('active')} disabled={transition.isLoading} className="!px-4 !py-[7px] text-[12px]" data-testid="risk-case-active">
            {ACTION_LABEL.active}
          </PrimaryButton>
        )}
        {next.includes('escalated') && (
          <SecondaryButton onClick={() => void move('escalated')} disabled={transition.isLoading} className="!px-4 !py-[7px] text-[12px]" data-testid="risk-case-escalated">
            {ACTION_LABEL.escalated}
          </SecondaryButton>
        )}
        {next.includes('closed') && (
          <SecondaryButton onClick={() => void move('closed')} disabled={transition.isLoading} className="!px-4 !py-[7px] text-[12px]" data-testid="risk-case-closed">
            {ACTION_LABEL.closed}
          </SecondaryButton>
        )}
        <span className="flex-1" />
        <LinkButton onClick={() => void navigate('/explore')}>Open in Explore →</LinkButton>
      </div>
    </>
  );
}

function FindingDetail({ item }: { readonly item: Extract<RiskItem, { kind: 'finding' }> }) {
  const navigate = useNavigate();
  const f = item.finding;
  return (
    <>
      <span className="flex flex-col gap-1.5">
        <span className="flex flex-wrap items-center gap-2">
          {item.severity ? (
            <TonePill tone={SEVERITY_TONE[item.severity]}>{SEVERITY_LABEL[item.severity]}</TonePill>
          ) : (
            <TonePill tone="mute">{f.risk_level ?? 'Level not reported'}</TonePill>
          )}
          <span className="text-[12px]" style={MUTE}>{CATEGORY_LABEL.agent} · {f.code}</span>
        </span>
        <h2 className="text-[18px] font-medium leading-[1.3]">{item.title}</h2>
      </span>
      <div className="flex flex-col gap-1.5 rounded-[16px] px-3.5 py-3" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
        <Eyebrow>Evidence</Eyebrow>
        <span className="text-[13px] leading-[1.5]">{f.evidence ?? 'No evidence text recorded.'}</span>
        <span className="flex justify-between gap-3 text-[12px]">
          <span style={MUTE}>Source</span>
          <span className="truncate">{f.source ?? 'Not recorded'}</span>
        </span>
        <span className="flex justify-between gap-3 text-[12px]">
          <span style={MUTE}>Capability</span>
          <span className="ae-mono truncate">{f.capability_id ?? 'Not recorded'}</span>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t pt-3" style={{ borderColor: 'var(--ae-edge-soft)' }}>
        <span className="text-[12px]" style={MUTE}>Aether observes this access. It does not change the agent.</span>
        <span className="flex-1" />
        <LinkButton onClick={() => void navigate('/agent-access')}>Open Agents →</LinkButton>
      </div>
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function RiskPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const tenantId = user?.id ?? '';
  const [params, setParams] = useSearchParams();
  const view: View = params.get('view') === 'register' ? 'register' : 'overview';
  const selectedKey = params.get('item');
  const sevParam = params.get('severity');
  const severity: SeverityFilter =
    sevParam && (sevParam === 'unrated' || (SEVERITIES as readonly string[]).includes(sevParam)) ? (sevParam as SeverityFilter) : 'all';
  const [category, setCategory] = useState<'all' | Category>('all');

  const findings = useCapabilityRiskFindings();
  const cases = useRiskCases(tenantId);
  const quality = useRiskDataQuality(tenantId);
  const now = Date.now();

  const register = useMemo(
    () => buildRegister(findings.data?.items ?? [], cases.data ?? []),
    [findings.data, cases.data],
  );
  const filtered = register.filter(i => matches(i, severity, category));
  const selected = filtered.find(i => i.key === selectedKey) ?? filtered[0] ?? null;

  const findingCounts = findings.data?.counts.by_risk_level ?? {};
  const drift = quality.data?.driftBySeverity ?? {};
  const sevRows = SEVERITIES.map(s => {
    const agent = Object.entries(findingCounts).reduce((n, [k, v]) => (k.toLowerCase() === s ? n + v : n), 0);
    const dq = drift[s] ?? 0;
    return { s, agent, dq, total: agent + dq };
  });
  const maxSev = Math.max(1, ...sevRows.map(r => r.total));
  const openCases = (cases.data ?? []).filter(c => c.status !== 'closed');
  const closedCount = (cases.data ?? []).length - openCases.length;
  const allSettled = Boolean(findings.data && cases.data && quality.data);
  const findingsTotal = findings.data ? (findings.data.counts.total ?? findings.data.items.length) : 0;
  const openN = findingsTotal + openCases.length + (quality.data?.openDrift ?? 0);
  const critN = (sevRows.find(r => r.s === 'critical')?.total) ?? 0;
  const findingsPartial = findings.data && findings.data.counts.scope !== 'all_matching_findings';

  function update(next: Record<string, string | null>) {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: true });
  }

  const openItem = (key: string) => {
    setCategory('all');
    update({ view: 'register', item: key, severity: null });
  };

  const scorePct = quality.data?.score !== null && quality.data?.score !== undefined ? Math.round(quality.data.score * 100) : null;

  return (
    <GlassPage>
      <div className="flex flex-col gap-4" data-testid="aether-risk">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <span className="flex flex-col gap-1">
            <h1 className="text-[clamp(26px,4.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Risk</h1>
            <span className="max-w-[560px] text-[14px] leading-[1.45]" style={MUTE}>
              What could go wrong and what is being done about it. Aether observes. It does not change agents or data.
            </span>
          </span>
          {allSettled && (
            <span className="ae-mono text-[12px]" style={MUTE} data-testid="risk-counts">
              {openN} open · {critN} critical
            </span>
          )}
        </div>

        <SegmentedTabs
          label="Risk views"
          options={[
            { value: 'overview', label: 'Overview', testId: 'risk-tab-overview' },
            { value: 'register', label: 'Register', testId: 'risk-tab-register' },
          ]}
          value={view}
          onChange={v => update({ view: v })}
        />

        {!tenantId ? (
          <LoadingRow label="Loading workspace…" />
        ) : view === 'overview' ? (
          <div className="flex flex-col gap-3.5" data-testid="risk-overview">
            <div className="grid gap-3.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))' }}>
              <GlassSection testId="risk-severity">
                <Eyebrow>Open findings by severity</Eyebrow>
                {findings.error && <Unavailable what="Agent access findings" onRetry={findings.refetch} />}
                {quality.error && <Unavailable what="Data quality drift" onRetry={quality.refetch} />}
                {(!findings.data && !findings.error) || (!quality.data && !quality.error) ? (
                  <LoadingRow label="Loading findings…" />
                ) : findings.error && quality.error ? null : sevRows.every(r => r.total === 0) ? (
                  <EmptySlot testId="risk-severity-empty">No open findings at any severity.</EmptySlot>
                ) : (
                  sevRows.map(r => (
                    <button
                      key={r.s}
                      type="button"
                      onClick={() => update({ view: 'register', severity: r.s, item: null })}
                      className="ae-focus -mx-2 rounded-[10px] px-2 py-1.5 text-left hover:bg-[color:var(--ae-edge-soft)]"
                      data-testid={`risk-severity-${r.s}`}
                    >
                      <span className="flex items-center justify-between gap-2 text-[13px]">
                        <span className="flex items-center gap-2"><Dot color={toneColor(SEVERITY_TONE[r.s])} size={8} />{SEVERITY_LABEL[r.s]}</span>
                        <span className="ae-mono">{r.total}</span>
                      </span>
                      <span className="mt-1 block h-1.5 overflow-hidden rounded-full" style={{ background: 'var(--ae-edge-soft)' }}>
                        <span className="block h-full" style={{ width: `${(r.total / maxSev) * 100}%`, background: toneColor(SEVERITY_TONE[r.s]) }} />
                      </span>
                      <span className="mt-1 block text-[11px]" style={{ color: 'var(--ae-faint)' }}>
                        {r.agent} agent access · {r.dq} data quality
                      </span>
                    </button>
                  ))
                )}
                {findingsPartial && (
                  <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>Agent findings cover the scanned window only.</span>
                )}
              </GlassSection>

              <GlassSection testId="risk-quality">
                <Eyebrow>Data quality</Eyebrow>
                {quality.error ? (
                  <Unavailable what="Data quality" onRetry={quality.refetch} />
                ) : !quality.data ? (
                  <LoadingRow label="Loading data quality…" />
                ) : (
                  <div className="flex flex-wrap items-center gap-5">
                    <svg viewBox="0 0 36 36" className="h-[104px] w-[104px] flex-none" role="img" aria-label={scorePct === null ? 'Quality score not computed' : `Quality score ${scorePct}%`}>
                      <circle cx="18" cy="18" r="15.9155" fill="none" stroke="var(--ae-edge-soft)" strokeWidth="3" />
                      {scorePct !== null && (
                        <circle
                          cx="18" cy="18" r="15.9155" fill="none" stroke="var(--ae-blue)" strokeWidth="3" strokeLinecap="round"
                          strokeDasharray={`${scorePct} ${100 - scorePct}`} transform="rotate(-90 18 18)"
                        />
                      )}
                      <text x="18" y="20.5" textAnchor="middle" fontSize="8" fill="var(--ae-ink)" className="ae-mono">
                        {scorePct === null ? '—' : `${scorePct}%`}
                      </text>
                    </svg>
                    <span className="flex min-w-0 flex-[1_1_150px] flex-col gap-1.5">
                      <span className="text-[16px] font-medium leading-[1.3]">
                        {scorePct === null ? 'Quality score not computed yet' : 'Intelligence quality score'}
                      </span>
                      {quality.data.status && quality.data.status !== 'unknown' && (
                        <span><TonePill tone={/critical/i.test(quality.data.status) ? 'ember' : /degraded|watch/i.test(quality.data.status) ? 'amber' : /healthy/i.test(quality.data.status) ? 'sage' : 'mute'}>{quality.data.status}</TonePill></span>
                      )}
                      <span className="text-[12px] leading-[1.5]" style={MUTE}>
                        {quality.data.openDrift === null ? 'Open drift not reported.' : `${quality.data.openDrift} open drift event${quality.data.openDrift === 1 ? '' : 's'}.`}{' '}
                        Reported by Data Quality; not a risk score.
                      </span>
                      <span><LinkButton onClick={() => void navigate('/data-quality')}>Open Data Quality →</LinkButton></span>
                    </span>
                  </div>
                )}
              </GlassSection>
            </div>

            <div className="grid gap-3.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))' }}>
              <GlassSection testId="risk-top">
                <Eyebrow>Needs a decision first</Eyebrow>
                {!findings.data && !findings.error && !cases.data && !cases.error ? (
                  <LoadingRow label="Loading register…" />
                ) : register.length === 0 ? (
                  findings.error || cases.error ? (
                    <span className="text-[13px]" style={MUTE}>Some sources are unavailable, so this list may be incomplete.</span>
                  ) : (
                    <EmptySlot testId="risk-top-empty">Nothing open needs a decision.</EmptySlot>
                  )
                ) : (
                  register.slice(0, 3).map(item => <RiskRow key={item.key} item={item} now={now} onClick={() => openItem(item.key)} />)
                )}
              </GlassSection>

              <GlassSection testId="risk-cases">
                <span className="flex items-center justify-between gap-2">
                  <Eyebrow>Investigations</Eyebrow>
                  {closedCount > 0 && <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>{closedCount} closed</span>}
                </span>
                {cases.error ? (
                  <Unavailable what="Investigations" onRetry={cases.refetch} />
                ) : !cases.data ? (
                  <LoadingRow label="Loading investigations…" />
                ) : (
                  <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))' }}>
                    {(['open', 'triage', 'active', 'escalated'] as const).map(s => (
                      <MetricTile key={s} label={STATUS_LABEL[s]} value={(cases.data ?? []).filter(c => c.status === s).length} {...(s === 'escalated' ? { tone: 'ember' as const } : {})} />
                    ))}
                  </div>
                )}
              </GlassSection>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3" data-testid="risk-register">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="flex flex-wrap gap-1.5" aria-label="Severity">
                <OutlineChip selected={severity === 'all'} onClick={() => update({ severity: null, item: null })}>All</OutlineChip>
                {SEVERITIES.map(s => (
                  <OutlineChip key={s} selected={severity === s} onClick={() => update({ severity: s, item: null })}>
                    <span className="inline-flex items-center gap-1.5"><Dot color={toneColor(SEVERITY_TONE[s])} size={7} />{SEVERITY_LABEL[s]}</span>
                  </OutlineChip>
                ))}
                <OutlineChip selected={severity === 'unrated'} onClick={() => update({ severity: 'unrated', item: null })}>Not rated</OutlineChip>
              </span>
              <span className="flex flex-wrap gap-1.5" aria-label="Category">
                {(['all', 'agent', 'case'] as const).map(c => (
                  <OutlineChip key={c} selected={category === c} onClick={() => { setCategory(c); update({ item: null }); }}>
                    {c === 'all' ? 'All sources' : CATEGORY_LABEL[c]}
                  </OutlineChip>
                ))}
              </span>
            </div>

            {findings.error && <Unavailable what="Agent access findings" onRetry={findings.refetch} />}
            {cases.error && <Unavailable what="Investigations" onRetry={cases.refetch} />}
            {severity !== 'all' && severity !== 'unrated' && (drift[severity] ?? 0) > 0 && (
              <InlineNotice tone="blue">
                {drift[severity]} {SEVERITY_LABEL[severity].toLowerCase()} data-quality drift event{drift[severity] === 1 ? ' is' : 's are'} listed in{' '}
                <button type="button" className="ae-focus underline" onClick={() => void navigate('/data-quality')}>Data Quality</button>.
              </InlineNotice>
            )}

            {(!findings.data && !findings.error) || (!cases.data && !cases.error) ? (
              <LoadingRow label="Loading register…" />
            ) : (
              <div className="grid items-start gap-3.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(360px, 100%), 1fr))' }}>
                <GlassSection className="!gap-0 !px-2.5 !py-2">
                  {filtered.length === 0 ? (
                    <span className="p-4 text-[13px]" style={MUTE} data-testid="risk-register-empty">
                      {register.length === 0 ? 'Nothing open in the register.' : 'No risks match these filters.'}
                    </span>
                  ) : (
                    filtered.map(item => (
                      <RiskRow key={item.key} item={item} now={now} selected={selected?.key === item.key} onClick={() => update({ item: item.key })} />
                    ))
                  )}
                </GlassSection>
                {selected && (
                  <GlassSection className="!gap-3.5 !px-5 !py-5" testId="risk-detail">
                    {selected.kind === 'case' ? (
                      <CaseDetail key={selected.key} c={selected.case} now={now} tenantId={tenantId} onChanged={cases.refetch} />
                    ) : (
                      <FindingDetail key={selected.key} item={selected} />
                    )}
                  </GlassSection>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </GlassPage>
  );
}

