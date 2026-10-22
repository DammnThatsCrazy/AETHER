import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Icon, formatCount, useTimeContext } from '@aether/ui';
import { BrandMark } from '@aether-app/components/brand-mark';
import { ChoiceChip, InlineNotice, LinkButton, MetricTile, TonePill } from '@aether-app/components/ae-ui';
import {
  AreaChart,
  Heatmap,
  SectionEmpty,
  SectionLoading,
  SectionUnavailable,
  StackBar,
  ValueCard,
  seriesColor,
} from './value-charts';
import { VALUE_EVENT_READ_LIMIT, useCampaignValues, useOutcomeLedgerRead, useValueEvents } from './value-data';
import {
  HOUR_BANDS,
  WEEKDAYS,
  asList,
  asRecord,
  compactMoney,
  inOneCurrency,
  concentration,
  dailySeries,
  entityValues,
  groupEvents,
  humanize,
  ledgerFunnel,
  num,
  pct,
  str,
  treemap,
  weekdayHeat,
  type CampaignValue,
  type Row,
  type ValueEvent,
} from './value-model';

const GRID_2 = { gridTemplateColumns: 'repeat(auto-fit, minmax(min(340px, 100%), 1fr))' } as const;
const KPI_GRID = { gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' } as const;

function shortDay(day: string): string {
  const [y, m, d] = day.split('-').map(Number);
  if (!y || !m || !d) return day;
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function when(date: Date | null): string {
  return date ? date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : 'not recorded';
}

function EventCoverage({ events }: { readonly events: readonly ValueEvent[] }) {
  return (
    <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>
      {events.length} value event{events.length === 1 ? '' : 's'}
      {events.length >= VALUE_EVENT_READ_LIMIT ? ` · the read returns at most ${VALUE_EVENT_READ_LIMIT}, so this is not the full history` : ''}
    </span>
  );
}

// ── Overview ──────────────────────────────────────────────────────────────────

function OpenList({ title, items }: { readonly title: string; readonly items: readonly string[] }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-[12px] font-medium">{title}</span>
      {items.length ? (
        <ul className="flex flex-col gap-1">
          {items.map(item => (
            <li key={item} className="flex items-start gap-2 text-[13px] leading-snug">
              <span className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full" style={{ background: 'var(--ae-blue)' }} />
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>No open items.</span>
      )}
    </div>
  );
}

export function OverviewTab({ tenant, review }: { readonly tenant: string; readonly review: Row }) {
  const timeCtx = useTimeContext();
  const events = useValueEvents(tenant);
  const [cell, setCell] = useState<{ day: number; band: number } | null>(null);
  const cur = useMemo(() => inOneCurrency(events.data ?? []), [events.data]);
  const rows = cur.events;
  const series = useMemo(() => dailySeries(rows), [rows]);
  const heat = useMemo(() => weekdayHeat(rows), [rows]);
  const bySource = useMemo(() => groupEvents(rows, e => e.sourceType), [rows]);
  const byType = useMemo(() => groupEvents(rows, e => e.valueType), [rows]);
  const anyAmount = rows.some(e => e.amount !== null);

  const money = (key: string) => {
    const v = num(review[key]);
    return v === null ? 'not reported' : `$${formatCount(v, timeCtx)}`;
  };
  const count = (key: string) => {
    const v = num(review[key]);
    return v === null ? 'not reported' : formatCount(v, timeCtx);
  };
  const capture = num(review['outcome_capture_rate']);
  const playbookNames = (Array.isArray(review['top_playbooks']) ? (review['top_playbooks'] as unknown[]) : [])
    .map(p => {
      const rec = asRecord(p);
      return p && typeof p === 'object' ? String(rec['name'] ?? rec['playbook_id'] ?? '') : String(p ?? '');
    })
    .filter(Boolean);
  const strings = (key: string) => (Array.isArray(review[key]) ? (review[key] as unknown[]).map(String) : []);

  const cellEvents = cell
    ? rows
        .filter(e => e.occurredAt && (e.occurredAt.getDay() + 6) % 7 === cell.day && Math.floor(e.occurredAt.getHours() / 3) === cell.band)
        .sort((a, b) => (b.amount ?? 0) - (a.amount ?? 0))
    : [];

  return (
    <div className="flex flex-col gap-[18px]" data-testid="value-overview">
      <CurrencyNotice money={cur} />
      <div className="grid gap-2.5" style={KPI_GRID} data-testid="value-kpis">
        <MetricTile label="Value created" value={money('observed_value')} sub="from observed outcomes" tone="sage" />
        <MetricTile label="Expected value" value={money('expected_value')} sub="from recommendations" />
        <MetricTile label="Pending value" value={money('pending_value')} sub="awaiting an outcome" />
        <MetricTile label="Outcome capture" value={capture === null ? 'not reported' : pct(capture)} sub="recommendations with an outcome" />
        <MetricTile label="Recommendations acted upon" value={count('recommendations_acted_upon')} sub="decisions recorded" />
        <MetricTile label="Outcomes observed" value={count('outcomes_observed')} sub="closed loops" />
        <MetricTile label="Incomplete loops" value={count('incomplete_loops')} sub="no outcome yet" {...(num(review['incomplete_loops']) ? { tone: 'amber' as const } : {})} />
      </div>

      <div className="grid gap-[18px]" style={GRID_2}>
        <ValueCard title="Value over time" aside={events.data ? <EventCoverage events={rows} /> : null} testId="value-timeline">
          {events.error ? (
            <SectionUnavailable what="Value events are" detail={events.error} />
          ) : !events.data ? (
            <SectionLoading label="Loading value events" />
          ) : series.length === 0 ? (
            <SectionEmpty>No value events recorded yet. Value appears here as outcomes, playbooks and integration actions report it.</SectionEmpty>
          ) : (
            <AreaChart
              values={series.map(p => (anyAmount ? p.total : p.events))}
              labels={series.map(p => shortDay(p.day))}
              format={v => (anyAmount ? compactMoney(v, cur.currency) : `${v} event${v === 1 ? '' : 's'}`)}
              ariaLabel={anyAmount ? 'Value per day' : 'Value events per day'}
            />
          )}
        </ValueCard>

        <ValueCard title="When value arrives" aside={<span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>weekday and time of day, your local time</span>} testId="value-heatmap">
          {events.error ? (
            <SectionUnavailable what="Value events are" detail={events.error} />
          ) : !events.data ? (
            <SectionLoading label="Loading value events" />
          ) : rows.every(e => !e.occurredAt) ? (
            <SectionEmpty>No timed value events yet.</SectionEmpty>
          ) : (
            <>
              <Heatmap cells={heat} selected={cell} onSelect={setCell} metric={anyAmount ? 'total' : 'events'} />
              {cell ? (
                <div className="flex flex-col gap-1 border-t pt-2.5" style={{ borderColor: 'var(--ae-edge)' }}>
                  <span className="text-[12px] font-medium">
                    {WEEKDAYS[cell.day]} {HOUR_BANDS[cell.band]}:00 to {String(cell.band * 3 + 3).padStart(2, '0')}:00 · {cellEvents.length} event{cellEvents.length === 1 ? '' : 's'}
                  </span>
                  {cellEvents.length === 0 ? (
                    <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Nothing arrived in this slot.</span>
                  ) : (
                    cellEvents.slice(0, 5).map(e => (
                      <span key={e.id} className="flex justify-between gap-3 text-[12px]">
                        <span className="truncate">{humanize(e.valueType)} · {humanize(e.sourceType)}</span>
                        <span className="ae-mono">{e.amount === null ? 'no amount' : compactMoney(e.amount, cur.currency)}</span>
                      </span>
                    ))
                  )}
                </div>
              ) : (
                <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>Select a cell to see what arrived then.</span>
              )}
            </>
          )}
        </ValueCard>
      </div>

      <div className="grid gap-[18px]" style={GRID_2}>
        <ValueCard title="Who produced it" testId="value-producers">
          {events.error ? (
            <SectionUnavailable what="Value events are" />
          ) : !events.data ? (
            <SectionLoading label="Loading value events" />
          ) : bySource.length === 0 ? (
            <SectionEmpty>No producers yet.</SectionEmpty>
          ) : (
            <StackBar
              segments={bySource.map(g => ({ key: g.key, label: humanize(g.key), value: anyAmount ? g.total : g.events, detail: `${g.events} event${g.events === 1 ? '' : 's'}` }))}
              format={v => (anyAmount ? compactMoney(v, cur.currency) : String(v))}
            />
          )}
        </ValueCard>
        <ValueCard title="What kind of value" testId="value-types">
          {events.error ? (
            <SectionUnavailable what="Value events are" />
          ) : !events.data ? (
            <SectionLoading label="Loading value events" />
          ) : byType.length === 0 ? (
            <SectionEmpty>No value types reported yet.</SectionEmpty>
          ) : (
            <StackBar
              segments={byType.map(g => ({ key: g.key, label: humanize(g.key), value: anyAmount ? g.total : g.events, ...(g.unpriced ? { detail: `${g.unpriced} without amount` } : {}) }))}
              format={v => (anyAmount ? compactMoney(v, cur.currency) : String(v))}
            />
          )}
        </ValueCard>
      </div>

      <ValueCard title="Before your next review" testId="value-next-steps">
        <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))' }}>
          <OpenList title="Recommended next steps" items={strings('recommended_next_steps')} />
          <OpenList title="Setup gaps" items={strings('setup_gaps')} />
          <OpenList title="Integration gaps" items={strings('integration_gaps')} />
          <OpenList title="Top playbooks" items={playbookNames} />
        </div>
      </ValueCard>
    </div>
  );
}

// ── Sources ───────────────────────────────────────────────────────────────────

type SourceSort = 'value' | 'events' | 'confidence';

export function SourcesTab({ tenant }: { readonly tenant: string }) {
  const events = useValueEvents(tenant);
  const [sort, setSort] = useState<SourceSort>('value');
  const [open, setOpen] = useState<string | null>(null);
  const cur = useMemo(() => inOneCurrency(events.data ?? []), [events.data]);
  const rows = cur.events;
  const groups = useMemo(() => {
    const list = groupEvents(rows, e => e.sourceType);
    if (sort === 'events') return [...list].sort((a, b) => b.events - a.events);
    if (sort === 'confidence') return [...list].sort((a, b) => (b.confidence ?? -1) - (a.confidence ?? -1));
    return list;
  }, [rows, sort]);
  const total = groups.reduce((a, g) => a + g.total, 0);

  return (
    <>
    <CurrencyNotice money={cur} />
    <ValueCard
      title="Observed value by producing source"
      aside={
        <span className="flex items-center gap-1.5 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          Sort
          {(['value', 'events', 'confidence'] as const).map(s => (
            <ChoiceChip key={s} size="sm" selected={sort === s} onClick={() => setSort(s)}>{humanize(s)}</ChoiceChip>
          ))}
        </span>
      }
      testId="value-sources"
    >
      {events.error ? (
        <SectionUnavailable what="Value events are" detail={events.error} />
      ) : !events.data ? (
        <SectionLoading label="Loading value sources" />
      ) : groups.length === 0 ? (
        <SectionEmpty>No source has reported value yet. Outcomes, playbooks, recommendation families and integration actions each report value here once they record it.</SectionEmpty>
      ) : (
        <div className="flex flex-col">
          <EventCoverage events={rows} />
          {groups.map((g, i) => {
            const isOpen = open === g.key;
            const members = rows.filter(e => e.sourceType === g.key);
            const types = groupEvents(members, e => e.valueType);
            const notes = members.map(e => e.notes).filter((n): n is string => !!n).slice(0, 3);
            return (
              <div key={g.key} className="border-t" style={{ borderColor: 'var(--ae-edge)' }}>
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? null : g.key)}
                  className="ae-focus grid w-full items-center gap-3 py-2.5 text-left text-[13px]"
                  style={{ gridTemplateColumns: 'minmax(0, 1.6fr) minmax(70px, 1fr) auto' }}
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span className="h-2.5 w-2.5 flex-none rounded-full" style={{ background: seriesColor(i) }} />
                    <span className="flex min-w-0 flex-col leading-tight">
                      <span className="truncate">{humanize(g.key)}</span>
                      <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>
                        {g.events} event{g.events === 1 ? '' : 's'} · confidence {g.confidence === null ? 'not reported' : pct(g.confidence)}
                      </span>
                    </span>
                  </span>
                  <span className="flex flex-col gap-1">
                    <span className="block h-1 overflow-hidden rounded-sm" style={{ background: 'var(--ae-edge-soft)' }}>
                      <span className="block h-full" style={{ width: `${total > 0 ? (g.total / total) * 100 : 0}%`, background: seriesColor(i) }} />
                    </span>
                    <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{total > 0 ? `${Math.round((g.total / total) * 100)}% of total` : 'no amounts'}</span>
                  </span>
                  <span className="ae-mono text-right">{compactMoney(g.total, cur.currency)}</span>
                </button>
                {isOpen && (
                  <div className="flex flex-col gap-2.5 pb-3 pl-5">
                    <StackBar segments={types.map(t => ({ key: t.key, label: humanize(t.key), value: t.total, detail: `${t.events} event${t.events === 1 ? '' : 's'}` }))} format={v => compactMoney(v, cur.currency)} />
                    <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                      Last value {when(g.last)}{g.unpriced ? ` · ${g.unpriced} event${g.unpriced === 1 ? '' : 's'} reported without an amount` : ''}
                    </span>
                    {notes.map(note => (
                      <span key={note} className="text-[12px] leading-snug">“{note}”</span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </ValueCard>
    </>
  );
}

// ── Campaigns ─────────────────────────────────────────────────────────────────

function CampaignBubbles({
  items,
  selected,
  onSelect,
}: {
  readonly items: readonly CampaignValue[];
  readonly selected: string | null;
  readonly onSelect: (id: string) => void;
}) {
  const plotted = items.filter(c => c.overview && (c.overview.spend ?? 0) > 0 && c.overview.gross !== null);
  const maxX = Math.max(...plotted.map(c => c.overview!.spend ?? 0), 0);
  const maxY = Math.max(...plotted.map(c => c.overview!.gross ?? 0), 0);
  const top = Math.max(maxX, maxY) * 1.1 || 1;
  const maxNet = Math.max(...plotted.map(c => Math.max(0, c.overview!.net ?? 0)), 0);
  if (plotted.length === 0) {
    return <SectionEmpty>No campaign reported spend in this window, so there is nothing to plot. Campaigns without spend still appear in the list below.</SectionEmpty>;
  }
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex gap-2">
        <div className="ae-mono flex flex-col justify-between py-1 text-right text-[10px]" style={{ color: 'var(--ae-faint)', minWidth: 40 }}>
          {[1, 0.5, 0].map(f => <span key={f}>{compactMoney(top * f)}</span>)}
        </div>
        <div className="relative flex-1 rounded-xl" style={{ height: 240, background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
            <line x1="0" y1="100" x2="100" y2="0" style={{ stroke: 'var(--ae-line)' }} strokeWidth="1" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
          </svg>
          {plotted.map(c => {
            const o = c.overview!;
            const x = ((o.spend ?? 0) / top) * 100;
            const y = ((o.gross ?? 0) / top) * 100;
            const size = 14 + (maxNet > 0 ? Math.sqrt(Math.max(0, o.net ?? 0) / maxNet) * 30 : 0);
            const above = (o.gross ?? 0) >= (o.spend ?? 0);
            const isSel = selected === c.id;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => onSelect(c.id)}
                aria-label={`${c.name}: spend ${compactMoney(o.spend)}, attributed revenue ${compactMoney(o.gross)}`}
                aria-pressed={isSel}
                className="ae-focus absolute rounded-full"
                style={{
                  left: `calc(${x}% - ${size / 2}px)`,
                  bottom: `calc(${y}% - ${size / 2}px)`,
                  width: size,
                  height: size,
                  background: above ? 'var(--ae-sage)' : 'var(--ae-amber)',
                  opacity: isSel ? 0.95 : 0.6,
                  outline: isSel ? '2px solid var(--ae-ink)' : undefined,
                }}
              />
            );
          })}
        </div>
      </div>
      <div className="ae-mono flex justify-between pl-12 text-[10px]" style={{ color: 'var(--ae-faint)' }}>
        <span>$0 spend</span>
        <span>{compactMoney(top)} spend</span>
      </div>
      <span className="flex flex-wrap gap-3 text-[11px]" style={{ color: 'var(--ae-mute)' }}>
        <span><span style={{ color: 'var(--ae-sage)' }}>●</span> revenue at or above spend</span>
        <span><span style={{ color: 'var(--ae-amber)' }}>●</span> revenue below spend</span>
        <span>dashed line is 1x return · bubble size is net attributed revenue</span>
      </span>
    </div>
  );
}

export function CampaignsTab({ tenant, days }: { readonly tenant: string; readonly days: number }) {
  const navigate = useNavigate();
  const read = useCampaignValues(tenant, days);
  const [picked, setPicked] = useState<string | null>(null);
  const items = read.data?.items ?? [];
  const selected = items.find(c => c.id === picked) ?? null;
  const failed = items.filter(c => !c.overview).length;

  if (read.error) return <ValueCard title="Spend against value"><SectionUnavailable what="Campaigns are" detail={read.error} /></ValueCard>;
  if (!read.data) return <ValueCard title="Spend against value"><SectionLoading label={`Loading campaign spend for the last ${days} days`} /></ValueCard>;
  if (items.length === 0) {
    return (
      <ValueCard title="Spend against value" testId="value-campaigns">
        <SectionEmpty>No campaigns yet. Aether imports campaigns from connected ad, email and commerce systems; it never creates them.</SectionEmpty>
        <LinkButton onClick={() => void navigate('/settings/integrations')}>Connect a source →</LinkButton>
      </ValueCard>
    );
  }

  return (
    <div className="flex flex-col gap-[18px]" data-testid="value-campaigns">
      <ValueCard
        title="Spend against value"
        aside={<span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>spend for the last {days} days · attributed revenue as reported by the campaign overview</span>}
      >
        <CampaignBubbles items={items} selected={picked} onSelect={setPicked} />
        {failed > 0 && <SectionUnavailable what={`${failed} campaign overview${failed === 1 ? ' is' : 's are'}`} />}
      </ValueCard>

      {selected?.overview && (
        <ValueCard
          title={selected.name}
          aside={<LinkButton onClick={() => void navigate(`/campaigns/${encodeURIComponent(selected.id)}`)}>Open campaign →</LinkButton>}
          testId="value-campaign-detail"
        >
          <div className="grid gap-2.5" style={KPI_GRID}>
            <MetricTile label="Spend" value={compactMoney(selected.overview.spend)} sub={`last ${days} days`} />
            <MetricTile label="Gross attributed" value={selected.overview.gross === null ? 'not reported' : compactMoney(selected.overview.gross)} />
            <MetricTile label="Net attributed" value={selected.overview.net === null ? 'not reported' : compactMoney(selected.overview.net)} />
            <MetricTile
              label="Return on spend"
              value={selected.overview.roas === null ? 'not reported' : `${selected.overview.roas.toFixed(1)}x`}
              {...(selected.overview.roas !== null ? { tone: selected.overview.roas >= 1 ? 'sage' as const : 'amber' as const } : {})}
            />
            <MetricTile label="Attributed conversions" value={selected.overview.attributed === null ? 'not reported' : String(selected.overview.attributed)} sub={selected.overview.converted === null ? undefined : `of ${selected.overview.converted} converted`} />
          </div>
        </ValueCard>
      )}

      <ValueCard title={read.data.partial ? `First ${read.data.total} campaigns (more exist; not compared here)` : `${read.data.total} campaign${read.data.total === 1 ? '' : 's'} imported`} aside={<span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>select a row to inspect it</span>}>
        <div className="overflow-x-auto">
          <div className="flex min-w-[560px] flex-col">
            <div className="ae-eyebrow grid gap-3 px-1 pb-1.5" style={{ gridTemplateColumns: 'minmax(160px,1.8fr) 90px 90px 90px 70px' }}>
              <span>Campaign</span>
              <span className="text-right">Spend</span>
              <span className="text-right">Gross</span>
              <span className="text-right">Net</span>
              <span className="text-right">ROAS</span>
            </div>
            {items.map((c, index) => (
              <button
                key={c.id || index}
                type="button"
                onClick={() => setPicked(c.id)}
                aria-pressed={picked === c.id}
                className="ae-focus grid items-center gap-3 border-t px-1 py-[7px] text-left text-[13px] hover:bg-[var(--ae-glass-card)]"
                style={{
                  gridTemplateColumns: 'minmax(160px,1.8fr) 90px 90px 90px 70px',
                  borderColor: 'var(--ae-edge)',
                  background: picked === c.id ? 'var(--ae-blue-tint)' : undefined,
                }}
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <BrandMark token={c.platform ?? 'aether'} label={c.platform ?? 'Aether'} size={22} markSize={14} />
                  <span className="flex min-w-0 flex-col leading-tight">
                    <span className="truncate">{c.name}</span>
                    <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{c.platform ?? 'source unknown'}{c.status ? ` · ${c.status}` : ''}</span>
                  </span>
                </span>
                {c.overview ? (
                  <>
                    <span className="ae-mono text-right text-[12px]">{compactMoney(c.overview.spend)}</span>
                    <span className="ae-mono text-right text-[12px]">{compactMoney(c.overview.gross)}</span>
                    <span className="ae-mono text-right text-[12px]">{compactMoney(c.overview.net)}</span>
                    <span className="ae-mono text-right text-[12px]">{c.overview.roas === null ? '—' : `${c.overview.roas.toFixed(1)}x`}</span>
                  </>
                ) : (
                  <span className="col-span-4 text-right text-[12px]" style={{ color: 'var(--ae-amber)' }}>overview unavailable</span>
                )}
              </button>
            ))}
          </div>
        </div>
      </ValueCard>
    </div>
  );
}

// ── Agents ────────────────────────────────────────────────────────────────────

export function AgentsValueTab() {
  const navigate = useNavigate();
  return (
    <ValueCard title="Agent-completed value" testId="value-agents">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-full" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge)', color: 'var(--ae-violet)' }}>
          <Icon name="bot" decorative size="sm" />
        </span>
        <div className="flex flex-col gap-1.5">
          <SectionEmpty>
            Value is not yet attributed to individual agents. Value events report the outcome, playbook, recommendation family or integration action
            that produced them, so orders against granted ceilings cannot be plotted here without inventing them.
          </SectionEmpty>
          <LinkButton onClick={() => void navigate('/agent-access')}>See observed agents and their authority →</LinkButton>
        </div>
      </div>
    </ValueCard>
  );
}

// ── Customers ─────────────────────────────────────────────────────────────────

export function CustomersTab({ tenant }: { readonly tenant: string }) {
  const ledger = useOutcomeLedgerRead(tenant);
  const entities = useMemo(() => entityValues(ledger.data ?? {}), [ledger.data]);
  const valued = entities.filter(e => e.observed > 0);
  const cells = useMemo(() => treemap(valued.slice(0, 24).map(e => ({ key: e.key, value: e.observed }))), [valued]);
  const curve = useMemo(() => concentration(valued.map(e => e.observed)), [valued]);
  const total = valued.reduce((a, e) => a + e.observed, 0);
  const topFifth = curve.find(p => p.x >= 0.2) ?? null;

  if (ledger.error) return <ValueCard title="Value by customer"><SectionUnavailable what="The outcome ledger is" detail={ledger.error} /></ValueCard>;
  if (!ledger.data) return <ValueCard title="Value by customer"><SectionLoading label="Loading the outcome ledger" /></ValueCard>;
  if (valued.length === 0) {
    return (
      <ValueCard title="Value by customer" testId="value-customers">
        <SectionEmpty>No customer has observed value yet. Customers appear here when an outcome with a value is recorded against them.</SectionEmpty>
      </ValueCard>
    );
  }

  return (
    <div className="flex flex-col gap-[18px]" data-testid="value-customers">
      <LedgerPartialNotice ledger={ledger.data} />
      <div className="grid gap-[18px]" style={GRID_2}>
        <ValueCard title="Value map" aside={<span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>area is observed value</span>}>
          <div className="relative w-full overflow-hidden rounded-xl" style={{ height: 260 }}>
            {cells.map((c, i) => {
              const linkable = c.key !== 'unknown';
              const body = (
                <span className="flex h-full flex-col justify-between p-2 text-[11px] leading-tight">
                  <span className="truncate font-medium">{linkable ? c.key : 'Not attributed'}</span>
                  <span className="ae-mono">{compactMoney(c.value)} · {Math.round((c.value / total) * 100)}%</span>
                </span>
              );
              const style = {
                left: `${c.x}%`,
                top: `${c.y}%`,
                width: `${c.w}%`,
                height: `${c.h}%`,
                background: 'var(--ae-glass-card)',
                boxShadow: `inset 0 0 0 1px var(--ae-edge), inset 0 3px 0 ${seriesColor(i)}`,
              };
              return linkable ? (
                <Link key={c.key} to={`/users/${encodeURIComponent(c.key)}`} className="ae-focus absolute overflow-hidden rounded-lg hover:opacity-90" style={style}>{body}</Link>
              ) : (
                <span key={c.key} className="absolute overflow-hidden rounded-lg" style={style}>{body}</span>
              );
            })}
          </div>
          {valued.length > 24 && <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>Showing the top 24 of {valued.length} customers with value.</span>}
        </ValueCard>

        <ValueCard title="Concentration" aside={<span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>share of value held by top customers</span>}>
          <div className="relative" style={{ height: 200 }}>
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" role="img" aria-label="Cumulative share of observed value by customer rank">
              <line x1="0" y1="100" x2="100" y2="0" style={{ stroke: 'var(--ae-line)' }} strokeDasharray="3 3" strokeWidth="1" vectorEffect="non-scaling-stroke" />
              <path d={`${curve.map((p, i) => `${i ? 'L' : 'M'}${(p.x * 100).toFixed(2)} ${(100 - p.y * 100).toFixed(2)}`).join(' ')} L100 100 L0 100 Z`} style={{ fill: 'var(--ae-blue)', opacity: 0.1 }} />
              <path d={curve.map((p, i) => `${i ? 'L' : 'M'}${(p.x * 100).toFixed(2)} ${(100 - p.y * 100).toFixed(2)}`).join(' ')} fill="none" style={{ stroke: 'var(--ae-blue)' }} strokeWidth="2" vectorEffect="non-scaling-stroke" />
            </svg>
          </div>
          <div className="ae-mono flex justify-between text-[10px]" style={{ color: 'var(--ae-faint)' }}>
            <span>top customer</span>
            <span>all {valued.length}</span>
          </div>
          <span className="text-[13px]">
            {topFifth && valued.length >= 5
              ? `The top 20% of customers hold ${pct(topFifth.y)} of observed value.`
              : `The top customer holds ${pct(curve[1]?.y ?? null)} of observed value.`}
          </span>
        </ValueCard>
      </div>

      <ValueCard title="Customers by observed value">
        <div className="overflow-x-auto">
          <div className="flex min-w-[520px] flex-col">
            <div className="ae-eyebrow grid gap-3 px-1 pb-1.5" style={{ gridTemplateColumns: 'minmax(160px,1.8fr) 90px 90px 90px 90px' }}>
              <span>Customer</span>
              <span className="text-right">Observed</span>
              <span className="text-right">Expected</span>
              <span className="text-right">Outcomes</span>
              <span className="text-right">Recs</span>
            </div>
            {entities.slice(0, 25).map(e => (
              <div key={e.key} className="grid items-center gap-3 border-t px-1 py-[7px] text-[13px]" style={{ gridTemplateColumns: 'minmax(160px,1.8fr) 90px 90px 90px 90px', borderColor: 'var(--ae-edge)' }}>
                {e.key === 'unknown' ? (
                  <span style={{ color: 'var(--ae-mute)' }}>Not attributed to a customer</span>
                ) : (
                  <Link to={`/users/${encodeURIComponent(e.key)}`} className="ae-focus truncate hover:underline">{e.key}</Link>
                )}
                <span className="ae-mono text-right text-[12px]">{compactMoney(e.observed)}</span>
                <span className="ae-mono text-right text-[12px]">{compactMoney(e.expected)}</span>
                <span className="ae-mono text-right text-[12px]">{e.outcomes ?? '—'}</span>
                <span className="ae-mono text-right text-[12px]">{e.recommendations ?? '—'}</span>
              </div>
            ))}
          </div>
        </div>
      </ValueCard>
    </div>
  );
}

// ── Outcomes ──────────────────────────────────────────────────────────────────

export function OutcomesTab({ tenant }: { readonly tenant: string }) {
  const ledger = useOutcomeLedgerRead(tenant);
  const [step, setStep] = useState<number | null>(null);
  const summary = asRecord(ledger.data?.['summary']);
  const funnel = ledgerFunnel(summary);
  const top = funnel[0]?.count ?? null;
  const byType = asList(ledger.data?.['by_recommendation_type']);

  if (ledger.error) return <ValueCard title="From recommendation to outcome"><SectionUnavailable what="The outcome ledger is" detail={ledger.error} /></ValueCard>;
  if (!ledger.data) return <ValueCard title="From recommendation to outcome"><SectionLoading label="Loading the outcome ledger" /></ValueCard>;
  if (!top) {
    return (
      <ValueCard title="From recommendation to outcome" testId="value-outcomes">
        <SectionEmpty>No recommendations have been generated yet, so there is no loop to follow. Outcomes appear here once recommendations are acted on and observed.</SectionEmpty>
      </ValueCard>
    );
  }

  const sel = step !== null ? funnel[step] : null;
  const prev = step !== null && step > 0 ? funnel[step - 1] : null;
  const mix = [
    { key: 'success', label: 'Success', value: num(summary['success_rate']) ?? 0 },
    { key: 'neutral', label: 'Neutral', value: num(summary['neutral_rate']) ?? 0 },
    { key: 'failure', label: 'Failure', value: num(summary['failure_rate']) ?? 0 },
  ];

  return (
    <div className="flex flex-col gap-[18px]" data-testid="value-outcomes">
      <LedgerPartialNotice ledger={ledger.data} />
      <ValueCard title="From recommendation to outcome" aside={<span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>select a step for detail</span>}>
        <div className="flex flex-col gap-1.5">
          {funnel.map((s, i) => {
            const width = s.count === null || !top ? 0 : (s.count / top) * 100;
            const from = i > 0 ? funnel[i - 1]!.count : null;
            const rate = s.count !== null && from ? s.count / from : null;
            return (
              <button
                key={s.key}
                type="button"
                aria-pressed={step === i}
                onClick={() => setStep(step === i ? null : i)}
                className="ae-focus grid items-center gap-3 rounded-lg px-1 py-1 text-left text-[13px] hover:bg-[var(--ae-glass-card)]"
                style={{ gridTemplateColumns: 'minmax(110px, 180px) minmax(0, 1fr) 70px', background: step === i ? 'var(--ae-blue-tint)' : undefined }}
              >
                <span className="flex flex-col leading-tight">
                  <span>{s.label}</span>
                  <span className="ae-mono text-[11px]" style={{ color: 'var(--ae-mute)' }}>{s.count ?? 'not reported'}</span>
                </span>
                <span className="block h-5 overflow-hidden rounded-md" style={{ background: 'var(--ae-edge-soft)' }}>
                  <span className="block h-full rounded-md" style={{ width: `${width}%`, background: 'var(--ae-blue)', opacity: 0.35 + (1 - i / funnel.length) * 0.55 }} />
                </span>
                <span className="ae-mono text-right text-[11px]" style={{ color: 'var(--ae-mute)' }}>{i === 0 ? '100%' : pct(rate)}</span>
              </button>
            );
          })}
        </div>
        {sel && (
          <div className="grid gap-2.5 border-t pt-3" style={{ ...KPI_GRID, borderColor: 'var(--ae-edge)' }}>
            <MetricTile label="Reached this step" value={sel.count ?? 'not reported'} sub={sel.label} />
            <MetricTile label="Share of generated" value={sel.count === null ? 'not reported' : pct(sel.count / top, 1)} />
            <MetricTile
              label="From previous step"
              value={prev ? (sel.count !== null && prev.count ? pct(sel.count / prev.count) : 'not reported') : 'first step'}
              {...(prev?.count && sel.count !== null && sel.count / prev.count < 0.4 ? { tone: 'amber' as const } : {})}
            />
          </div>
        )}
      </ValueCard>

      <div className="grid gap-[18px]" style={GRID_2}>
        <ValueCard title="How outcomes landed">
          {num(summary['outcomes_observed']) ? (
            <StackBar segments={mix} format={v => pct(v)} />
          ) : (
            <SectionEmpty>No outcomes observed yet.</SectionEmpty>
          )}
        </ValueCard>
        <ValueCard title="Loop health">
          <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))' }}>
            <MetricTile label="Stale" value={num(summary['stale_loops']) ?? 'not reported'} {...(num(summary['stale_loops']) ? { tone: 'amber' as const } : {})} />
            <MetricTile label="Incomplete" value={num(summary['incomplete_loops']) ?? 'not reported'} />
            <MetricTile label="Failed" value={num(summary['failed_loops']) ?? 'not reported'} {...(num(summary['failed_loops']) ? { tone: 'ember' as const } : {})} />
          </div>
        </ValueCard>
      </div>

      <ValueCard title="By recommendation type">
        {byType.length === 0 ? (
          <SectionEmpty>No recommendation types reported.</SectionEmpty>
        ) : (
          <div className="flex flex-col">
            {byType.map(row => {
              const key = str(row['key']) ?? 'unknown';
              return (
                <div key={key} className="grid items-center gap-3 border-t py-[7px] text-[13px]" style={{ gridTemplateColumns: 'minmax(0,1.6fr) auto auto', borderColor: 'var(--ae-edge)' }}>
                  <span className="truncate">{humanize(key)}</span>
                  <TonePill tone="mute">{num(row['outcomes']) ?? 0} of {num(row['recommendations']) ?? 0} with outcome</TonePill>
                  <span className="ae-mono text-right text-[12px]">{compactMoney(num(row['observed_value']))}</span>
                </div>
              );
            })}
          </div>
        )}
      </ValueCard>
    </div>
  );
}

/**
 * The outcome ledger reads each collection up to a server limit and reports
 * which ones hit it; totals and rates computed from a capped read are partial.
 */
function LedgerPartialNotice({ ledger }: { readonly ledger: Record<string, unknown> }) {
  const completeness = asRecord(ledger['completeness']);
  if (completeness['complete'] !== false) return null;
  const capped = Object.entries(asRecord(completeness['truncated'])).filter(([, hit]) => hit === true).map(([name]) => name);
  const limit = num(completeness['limit']);
  return (
    <InlineNotice tone="amber">
      Partial read: the outcome ledger returned the first {limit ?? 'capped'} {capped.length ? capped.join(', ') : 'records'}, so the totals and rates below cover only those records.
    </InlineNotice>
  );
}

/** Shown when value events in other currencies were counted but not summed. */
function CurrencyNotice({ money }: { readonly money: ReturnType<typeof inOneCurrency> }) {
  if (money.setAside === 0) return null;
  return (
    <InlineNotice tone="amber">
      Amounts are shown in {money.currency ?? 'the reporting currency'} only. {money.setAside} event{money.setAside === 1 ? '' : 's'} in {money.otherCurrencies.join(', ')} {money.setAside === 1 ? 'is' : 'are'} counted but not added, because no exchange rate is applied.
    </InlineNotice>
  );
}
