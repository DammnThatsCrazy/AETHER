import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { SkipLink } from '@site/components/page-shell';
import { Glyph } from '@site/components/ui';
import { useSite } from '@site/site/site-context';
import {
  COMPONENT_LABELS,
  checkHealth,
  fetchHistory,
  fillDays,
  groupOf,
  uptime,
  type ComponentGroup,
  type DayStatus,
  type HealthSnapshot,
  type HealthState,
  type StatusHistory,
} from '@site/site/status';
import { BrandMark } from '@site/components/brand-mark';
import { pilotOnly } from '@site/site/access';

/**
 * Status.dc.html at /status. Live state from VITE_STATUS_API_URL, history from
 * VITE_STATUS_HISTORY_URL. Without a source the page says so; it never shows
 * green by default.
 */

const DAYS = 90;
const REFRESH_MS = 60_000;
/** The optional history feed gets this long before the page stops waiting. */
const HISTORY_TIMEOUT_MS = 10_000;

const BAR: Record<DayStatus, string> = { operational: '#6b9a7c', degraded: '#c9975a', outage: '#b5564a', no_data: '#d8d6d0' };
const DAY_LABEL: Record<DayStatus, string> = { operational: 'operational', degraded: 'degraded', outage: 'outage', no_data: 'no data' };

const TONE: Record<HealthState, [glyph: string, label: string, ink: string, bg: string]> = {
  operational: ['●', 'Operational', '#4f8466', 'rgba(107,154,124,0.14)'],
  degraded: ['▲', 'Degraded', '#8a6433', 'rgba(201,151,90,0.16)'],
  outage: ['■', 'Outage', '#9c4439', 'rgba(181,86,74,0.12)'],
  unknown: ['○', 'Not verified', '#6b6a65', 'rgba(156,155,149,0.16)'],
};

type Overall = [glyph: string, title: string, pill: string, color: string];

function overallFor(snapshot: HealthSnapshot | null, pilot = false): Overall {
  if (!snapshot) return ['○', 'Checking the monitored service', 'Checking', '#9c9b95'];
  if (snapshot.source === 'unconfigured' && pilot) return ['○', 'Status is shared with pilot partners', 'Private pilot', '#9c9b95'];
  if (snapshot.source === 'unconfigured') return ['○', 'Status not yet verified', 'Not configured', '#9c9b95'];
  if (snapshot.source === 'unreachable') return ['■', 'Status endpoint unreachable', 'Unreachable', '#b5564a'];
  switch (snapshot.state) {
    case 'operational':
      return ['●', 'All systems operational', 'Operational', '#6b9a7c'];
    case 'degraded':
      return ['▲', 'Degraded performance', 'Degraded', '#c9975a'];
    case 'outage':
      return ['■', 'Service outage', 'Outage', '#b5564a'];
    default:
      return ['○', 'Status not verified', 'Not verified', '#9c9b95'];
  }
}

const GROUPS: Array<[ComponentGroup, string, string, string]> = [
  ['product', 'Customer-visible product', '◈', '#3a6896'],
  ['connections', 'APIs and connections', '↔', '#8a6433'],
  ['supporting', 'Supporting systems', '⚙', '#7d6538'],
];

const RANGES: Array<[number, string]> = [
  [7, '7 days'],
  [30, '30 days'],
  [90, '90 days'],
];

const formatDay = (date: string) =>
  new Date(`${date}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });

const formatTime = (iso: string) =>
  new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }) + ' UTC';

function Bars({ label, days }: { label: string; days: ReturnType<typeof fillDays> }) {
  const [hover, setHover] = useState<number | null>(null);
  const pct = uptime(days);
  const summary = pct === null ? 'no history yet' : `${pct.toFixed(2)}% uptime`;
  const hovered = hover === null ? null : days[hover];
  return (
    <>
      <div role="img" aria-label={`${label}: ${DAYS}-day history, ${summary}`} className="flex h-[30px] items-stretch gap-0.5" onMouseLeave={() => setHover(null)}>
        {days.map((d, i) => (
          <span
            key={d.date}
            onMouseEnter={() => setHover(i)}
            className="min-w-0.5 flex-1 rounded-sm transition-opacity duration-120"
            style={{ background: BAR[d.status], opacity: hover !== null && hover !== i ? 0.55 : 1 }}
          />
        ))}
      </div>
      <div className="flex justify-between gap-3 font-mono text-[11px] text-ash">
        <span>{DAYS} days ago</span>
        <span style={hovered ? { color: TONE[hovered.status === 'no_data' ? 'unknown' : hovered.status][2] } : undefined}>
          {hovered ? `${formatDay(hovered.date)} · ${DAY_LABEL[hovered.status]}` : summary}
        </span>
        <span>today</span>
      </div>
    </>
  );
}

export function StatusPage({ now = () => new Date() }: { now?: () => Date }) {
  const { href } = useSite();
  // A pilot-only build has no public service to monitor yet, whatever API it
  // will use once production opens.
  const pilot = pilotOnly();
  const apiUrl = pilot ? '' : (import.meta.env.VITE_STATUS_API_URL?.trim() ?? '');
  const historyUrl = pilot ? '' : (import.meta.env.VITE_STATUS_HISTORY_URL?.trim() ?? '');
  const [snapshot, setSnapshot] = useState<HealthSnapshot | null>(null);
  const [history, setHistory] = useState<StatusHistory | null>(null);
  const [checking, setChecking] = useState(true);
  const [range, setRange] = useState(90);
  const abort = useRef<AbortController | null>(null);

  const loadHistory = useCallback(
    async (signal: AbortSignal) => {
      const timeout = new AbortController();
      const timer = setTimeout(() => timeout.abort(), HISTORY_TIMEOUT_MS);
      const stop = () => timeout.abort();
      signal.addEventListener('abort', stop);
      try {
        const hist = await fetchHistory(historyUrl, DAYS, fetch, timeout.signal);
        if (!signal.aborted) setHistory(hist);
      } catch {
        // Aborted or timed out: keep what is already shown.
      } finally {
        clearTimeout(timer);
        signal.removeEventListener('abort', stop);
      }
    },
    [historyUrl],
  );

  const refresh = useCallback(async () => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setChecking(true);
    // History is optional: it loads on its own clock with a timeout, so a slow
    // or hung feed never holds back the live state.
    void loadHistory(controller.signal);
    try {
      setSnapshot(await checkHealth(apiUrl, fetch, controller.signal));
    } catch {
      return; // aborted by a newer check
    }
    setChecking(false);
  }, [apiUrl, loadHistory]);

  useEffect(() => {
    document.title = 'Status — Aether';
    void refresh();
    const timer = apiUrl ? setInterval(() => void refresh(), REFRESH_MS) : undefined;
    return () => {
      clearInterval(timer);
      abort.current?.abort();
    };
  }, [refresh, apiUrl]);

  const [glyph, title, pill, color] = checking && !snapshot ? overallFor(null) : overallFor(snapshot, pilot);
  // Pin "today" per fetch so the bars and incident range agree within a render.
  const today = useMemo(() => now(), [now, history, snapshot]);

  const components = useMemo(() => {
    const byKey = new Map((snapshot?.components ?? []).map((c) => [c.key, c]));
    for (const key of Object.keys(history?.components ?? {})) {
      if (!byKey.has(key)) byKey.set(key, { key, label: COMPONENT_LABELS[key] ?? key.replace(/_/g, ' '), state: 'unknown', detail: '' });
    }
    return [...byKey.values()];
  }, [snapshot, history]);

  const incidents = useMemo(() => {
    const cutoff = today.getTime() - range * 86_400_000;
    return (history?.incidents ?? []).filter((i) => new Date(i.startedAt).getTime() >= cutoff);
  }, [history, range, today]);

  return (
    <div className="min-h-screen bg-stone-50 font-sans text-ink">
      <SkipLink />
      <header className="border-b border-line bg-stone-50">
        <div className="mx-auto flex h-14 max-w-[920px] items-center justify-between gap-4 px-6">
          <a href={href('aether', '/status')} className="flex items-center gap-2 text-ink no-underline">
            <BrandMark brand="aether" className="h-5 w-5" />
            <span className="text-[15px] font-medium">Aether</span>
            <span className="text-[15px] text-slate">Status</span>
          </a>
          <nav aria-label="Status resources" className="flex items-center gap-1 text-body-sm">
            <a href={href('aether', '/docs')} className="p-2 text-slate no-underline hover:text-ink">
              Docs
            </a>
            <a href={href('aether', '/')} className="p-2 text-slate no-underline hover:text-ink">
              Aether
            </a>
            <a
              href={href('aether', '/contact?type=developer')}
              className="inline-flex min-h-9 items-center gap-2 whitespace-nowrap rounded-control border border-ink bg-ink px-3.5 text-body-sm font-medium text-stone-50 no-underline hover:bg-[#2e2e34] hover:text-stone-50"
            >
              Contact support<Glyph className="text-ochre">→</Glyph>
            </a>
          </nav>
        </div>
      </header>

      <main id="main" tabIndex={-1} className="mx-auto flex max-w-[920px] flex-col gap-6 px-6 pb-16 focus:outline-none pt-[clamp(28px,5vw,48px)]">
        <section
          aria-labelledby="overall"
          className="flex flex-col gap-4 rounded-lg border border-t-4 p-[clamp(20px,3vw,28px)]"
          style={{ borderColor: `${color}66`, borderTopColor: color, background: `${color}14` }}
        >
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex flex-col gap-2">
              <span className="text-label uppercase text-slate">System status</span>
              <h1 id="overall" role="status" className="m-0 flex items-center gap-3 text-[clamp(22px,3vw,30px)] font-medium tracking-[-0.5px]">
                <Glyph className="text-[22px]">
                  <span style={{ color }}>{glyph}</span>
                </Glyph>
                {title}
              </h1>
              <p className="m-0 max-w-[580px] text-[14px] leading-[1.6] text-graphite-body">
                {pilot && snapshot?.source === 'unconfigured'
                  ? 'Pilot partners receive service status from their Olympus Labs contact.'
                  : (snapshot?.detail ?? 'Contacting the status endpoint. No state is assumed before the check returns.')}
              </p>
            </div>
            <div className="flex flex-col items-end gap-2">
              <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1 text-caption font-medium text-stone-50" style={{ background: color }}>
                <Glyph>{glyph}</Glyph>
                {pill}
              </span>
              {apiUrl && (
                <button
                  type="button"
                  onClick={() => void refresh()}
                  disabled={checking}
                  className="inline-flex min-h-[34px] cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-control border border-line bg-stone-50 px-3 text-body-sm font-medium text-ink hover:border-line-strong hover:bg-stone-200 disabled:cursor-wait disabled:opacity-60"
                >
                  <Glyph>↻</Glyph>
                  {checking ? 'Checking…' : 'Check again'}
                </button>
              )}
            </div>
          </div>
          <div className="flex flex-wrap justify-between gap-3 border-t border-ink/[0.08] pt-3.5">
            <span className="font-mono text-caption text-slate">
              {snapshot?.checkedAt ? `Last checked ${formatTime(snapshot.checkedAt)}` : snapshot?.source === 'unconfigured' ? (pilot ? 'Aether is in private pilot' : 'No check has run · monitor not configured') : 'Checking…'}
            </span>
            <div className="flex flex-wrap gap-3.5 text-caption text-graphite-body">
              {(['operational', 'degraded', 'outage', 'no_data'] as DayStatus[]).map((s) => (
                <span key={s} className="inline-flex items-center gap-1.5">
                  <span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm" style={{ background: BAR[s] }} />
                  {s === 'no_data' ? 'No data' : TONE[s][1]}
                </span>
              ))}
            </div>
          </div>
        </section>

        {components.length === 0 ? (
          <div className="flex flex-col items-start gap-1.5 rounded-lg border border-dashed border-line-strong bg-stone-100 p-6">
            <span className="text-[14px] font-medium">
              {snapshot?.source === 'unconfigured' ? (pilot ? 'Shared directly with pilot partners' : 'No component data') : checking ? 'Waiting for the check' : 'No components reported'}
            </span>
            <span className="max-w-[560px] text-body-sm leading-[1.55] text-slate">
              {snapshot?.source === 'unconfigured' && pilot
                ? 'Aether runs in private pilots, and each pilot partner receives service status from its Olympus Labs contact. A public status page opens with general availability.'
                : snapshot?.source === 'unconfigured'
                ? 'VITE_STATUS_API_URL is not set for this build, so no component can be verified. Nothing is shown as operational by default.'
                : 'Components appear once the endpoint reports them.'}
            </span>
          </div>
        ) : (
          GROUPS.map(([group, name, groupGlyph, groupColor]) => {
            const items = components.filter((c) => groupOf(c.key) === group);
            if (!items.length) return null;
            const affected = items.filter((c) => c.state !== 'operational').length;
            return (
              <details key={group} open className="group overflow-hidden rounded-card border border-line bg-stone-50">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-2 border-b border-line bg-stone-100 px-[18px] py-3 hover:bg-stone-200 [&::-webkit-details-marker]:hidden">
                  <span className="flex items-center gap-2.5 text-label uppercase text-graphite-body">
                    <span aria-hidden="true" className="w-3 -rotate-90 font-mono text-caption text-slate transition-transform group-open:rotate-0">
                      ⌄
                    </span>
                    <Glyph className="text-caption">
                      <span style={{ color: groupColor }}>{groupGlyph}</span>
                    </Glyph>
                    {name}
                  </span>
                  <span className={`font-mono text-[11px] ${affected ? 'text-ochre-ink' : 'text-sage-ink'}`}>
                    {affected ? `${affected} of ${items.length} not operational` : `all ${items.length} operational`}
                  </span>
                </summary>
                {items.map((c) => {
                  const [g, label, ink, bg] = TONE[c.state];
                  const days = fillDays(history?.components[c.key], DAYS, today);
                  const pct = uptime(days);
                  return (
                    <div key={c.key} className="flex flex-col gap-2 border-b border-stone-200 px-[18px] py-3.5 last:border-b-0">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <span className="flex min-w-0 items-baseline gap-2.5">
                          <span className="text-[14px] font-medium">{c.label}</span>
                          <span className="font-mono text-[11px] text-ash">component:{c.key}</span>
                        </span>
                        <span className="flex items-center gap-2.5">
                          <span className={`font-mono text-caption ${pct === null ? 'text-ash' : pct > 99.9 ? 'text-sage-ink' : pct > 99.7 ? 'text-ochre-ink' : 'text-ember-ink'}`}>
                            {pct === null ? '—' : `${pct.toFixed(2)}%`}
                          </span>
                          <span
                            className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-[3px] text-caption font-medium"
                            style={{ color: ink, background: bg, borderColor: `${ink}33` }}
                            title={c.detail || undefined}
                          >
                            <Glyph>{g}</Glyph>
                            {label}
                          </span>
                        </span>
                      </div>
                      <Bars label={c.label} days={days} />
                    </div>
                  );
                })}
              </details>
            );
          })
        )}

        <section aria-labelledby="hist" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="hist" className="m-0 text-[18px] font-medium">
              Past incidents
            </h2>
            <div role="radiogroup" aria-label="Range" className="inline-flex rounded-control border border-line bg-stone-100 p-0.5">
              {RANGES.map(([days, label]) => (
                <button
                  key={days}
                  type="button"
                  role="radio"
                  aria-checked={range === days}
                  onClick={() => setRange(days)}
                  className={`cursor-pointer rounded border-0 px-2.5 py-[5px] text-caption font-medium ${range === days ? 'bg-stone-50 text-ink shadow-[0_0_0_1px_#d8d6d0]' : 'bg-transparent text-slate'}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {incidents.length > 0 ? (
            <div className="overflow-hidden rounded-lg border border-line">
              {incidents.map((i) => (
                <details key={i.id} className="border-b border-l-[3px] border-b-stone-200 last:border-b-0" style={{ borderLeftColor: i.resolvedAt ? '#c9975a' : '#b5564a' }}>
                  <summary className="flex cursor-pointer list-none flex-wrap justify-between gap-3 px-[18px] py-3.5 hover:bg-stone-100 [&::-webkit-details-marker]:hidden">
                    <span className="flex items-baseline gap-2.5">
                      <span aria-hidden="true" className="font-mono text-caption text-slate">
                        ›
                      </span>
                      <span className="text-[14px] font-medium">{i.title}</span>
                    </span>
                    <span className={`font-mono text-caption ${i.resolvedAt ? 'text-sage-ink' : 'text-ember-ink'}`}>
                      ● {i.resolvedAt ? 'resolved' : i.status} · {formatDay(i.startedAt.slice(0, 10))}
                    </span>
                  </summary>
                  <div className="flex flex-col gap-1 pb-3.5 pl-10 pr-[18px]">
                    <span className="font-mono text-[11px] text-slate">
                      {formatTime(i.startedAt)}
                      {i.resolvedAt ? ` – ${formatTime(i.resolvedAt)}` : ' · ongoing'}
                      {i.components.length ? ` · ${i.components.join(', ')}` : ''}
                    </span>
                  </div>
                </details>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-line-strong p-5 text-body-sm leading-[1.55] text-slate">
              {history ? `No incidents reported in the last ${range} days.` : 'Incident history appears here once the history feed is connected.'}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-sage/[0.08] px-[18px] py-4">
            <span className="flex flex-col gap-[3px]">
              <span className="text-[14px] font-medium">
                <Glyph className="text-sage-ink">✉</Glyph> Follow updates
              </span>
              <span className="text-body-sm text-slate">Subscriptions aren&apos;t set up yet. For deployment-specific questions, contact support.</span>
            </span>
            <a
              href={href('aether', '/contact?type=developer')}
              className="inline-flex min-h-9 items-center gap-2 whitespace-nowrap rounded-control border border-sage-ink bg-sage-ink px-3.5 text-body-sm font-medium text-stone-50 no-underline hover:bg-[#41664e] hover:text-stone-50"
            >
              Contact support
            </a>
          </div>
        </section>
      </main>
    </div>
  );
}
