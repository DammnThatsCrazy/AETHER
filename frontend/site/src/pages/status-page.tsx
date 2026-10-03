/**
 * Built from design/designs/Status.dc.html (layout, copy and styles). Live
 * state comes from VITE_STATUS_API_URL and history from
 * VITE_STATUS_HISTORY_URL. Without a source the page says so; it never shows
 * green by default. Pilot-only builds say status is shared with pilot partners.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { asset, css, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { pilotOnly } from '@site/site/access';
import { SkipLink } from '@site/components/skip-link';
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
import './status-page.css';

const DAYS = 90;
const REFRESH_MS = 60_000;
/** The optional history feed gets this long before the page stops waiting. */
const HISTORY_TIMEOUT_MS = 10_000;

const BAR: Record<DayStatus, string> = { operational: '#6b9a7c', degraded: '#c9975a', outage: '#b5564a', no_data: '#d8d6d0' };
const DAY_LABEL: Record<DayStatus, string> = { operational: 'operational', degraded: 'degraded', outage: 'outage', no_data: 'no data' };
const DAY_INK: Record<DayStatus, string> = { operational: '#4f7a5e', degraded: '#8a6433', outage: '#a3473c', no_data: '#6b6a65' };

const TONE: Record<HealthState, [glyph: string, label: string, ink: string, bg: string]> = {
  operational: ['●', 'Operational', '#4f7a5e', 'rgba(107,154,124,0.14)'],
  degraded: ['▲', 'Degraded', '#8a6433', 'rgba(201,151,90,0.16)'],
  outage: ['■', 'Outage', '#a3473c', 'rgba(181,86,74,0.12)'],
  unknown: ['○', 'Not checked', '#6b6a65', 'rgba(156,155,149,0.16)'],
};

type Overall = [glyph: string, title: string, detail: string, color: string, pill: string];

function overallFor(snapshot: HealthSnapshot | null, pilot: boolean): Overall {
  if (!snapshot) return ['○', 'Checking the service', 'Waiting for the check to finish. Nothing is assumed until it does.', '#9c9b95', 'Checking'];
  if (snapshot.source === 'unconfigured' && pilot)
    return ['○', 'Status is shared with pilot partners', 'Pilot partners receive service status from their Olympus Labs contact.', '#9c9b95', 'Private pilot'];
  if (snapshot.source === 'unconfigured') return ['○', 'Status not checked yet', 'Live monitoring isn’t connected to this page yet.', '#9c9b95', 'Not connected'];
  if (snapshot.source === 'unreachable')
    return ['■', 'Can’t reach the status check', 'The check couldn’t be reached. This may be an outage, or a network problem between this page and Aether.', '#b5564a', 'Unreachable'];
  switch (snapshot.state) {
    case 'operational':
      return ['●', 'All systems operational', 'Everything we monitor is working normally.', '#6b9a7c', 'Operational'];
    case 'degraded':
      return ['▲', 'Degraded performance', 'Aether is reachable, but one or more parts are running slowly.', '#c9975a', 'Degraded'];
    case 'outage':
      return ['■', 'Service outage', 'Aether reports that one or more parts are down.', '#b5564a', 'Outage'];
    default:
      return ['○', 'Status not verified', snapshot.detail, '#9c9b95', 'Not verified'];
  }
}

const GROUPS: Array<[ComponentGroup, string, string, string]> = [
  ['product', 'The product', '◈', '#3a6896'],
  ['connections', 'Data in and out', '↔', '#8a6433'],
  ['supporting', 'Behind the scenes', '⚙', '#7d6538'],
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
      <div role="img" aria-label={`${label}: ${DAYS}-day history, ${summary}`} style={css('display: flex; gap: 2px; height: 30px; align-items: stretch;')} onMouseLeave={() => setHover(null)}>
        {days.map((d, i) => (
          <span
            key={d.date}
            onMouseEnter={() => setHover(i)}
            style={css('flex: 1 1 0; min-width: 2px; border-radius: 2px; cursor: default; background: ' + BAR[d.status] + '; opacity: ' + (hover !== null && hover !== i ? '0.55' : '1') + '; transition: opacity 120ms;')}
          />
        ))}
      </div>
      <div style={css('display: flex; justify-content: space-between; gap: 12px; font-size: 11px; color: #9c9b95; font-family: var(--font-mono);')}>
        <span>{DAYS} days ago</span>
        <span style={css('color: ' + (hovered ? DAY_INK[hovered.status] : '#9c9b95') + ';')}>
          {hovered ? `${formatDay(hovered.date)} · ${DAY_LABEL[hovered.status]}` : summary}
        </span>
        <span>today</span>
      </div>
    </>
  );
}

export function StatusPage({ now = () => new Date() }: { now?: () => Date }) {
  const link = useLink();
  usePageMeta('status');
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
    void refresh();
    const timer = apiUrl ? setInterval(() => void refresh(), REFRESH_MS) : undefined;
    return () => {
      clearInterval(timer);
      abort.current?.abort();
    };
  }, [refresh, apiUrl]);

  const [glyph, title, detail, color, pill] = checking && !snapshot ? overallFor(null, pilot) : overallFor(snapshot, pilot);
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

  const unconfigured = snapshot?.source === 'unconfigured';
  const checkedText = snapshot?.checkedAt
    ? `Last updated ${formatTime(snapshot.checkedAt)}`
    : unconfigured
      ? pilot
        ? 'Aether is in private pilot'
        : 'No check has run · monitor not configured'
      : 'Checking…';

  return (
    <div className="dc pg-status">
      <div data-page="status" style={css('min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);')}>
        <SkipLink />
        <header style={css('border-bottom: 1px solid #d8d6d0; background: #f5f4f1;')}>
          <div style={css('max-width: 920px; margin: 0 auto; padding: 0 24px; height: 56px; display: flex; align-items: center; justify-content: space-between; gap: 16px;')}>
            <a href={link('Status.dc.html')} style={css('display: flex; align-items: center; gap: 8px; text-decoration: none; color: #1a1a1e;')}>
              <img src={asset('../assets/logo-aether-layers.svg')} alt="" style={css('width: 20px; height: 20px;')} />
              <span style={css('font-size: 15px; font-weight: 500;')}>Aether</span>
              <span style={css('font-size: 15px; color: #6b6a65;')}>Status</span>
            </a>
            <nav aria-label="Status resources" style={css('display: flex; gap: 4px; font-size: 13px; align-items: center;')}>
              <a href={link('Docs.dc.html')} style={css('color: #6b6a65; text-decoration: none; padding: 8px;')} className="hv-75877933 st-narrow-hide">
                Docs
              </a>
              <a href={link('Aether Home.dc.html')} style={css('color: #6b6a65; text-decoration: none; padding: 8px;')} className="hv-75877933 st-narrow-hide">
                Aether
              </a>
              <a
                href={link('Contact.dc.html?brand=aether&type=developer')}
                style={css('display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; min-height: 36px; padding: 0 14px; box-sizing: border-box; border-radius: 6px; font-size: 13px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1; border: 1px solid #2563eb;')}
                className="hv-7e3a2e7d"
              >
                Contact support
                <span style={css('font-family: var(--font-mono); color: #c9975a;')}>→</span>
              </a>
            </nav>
          </div>
        </header>
        <main id="main" tabIndex={-1} style={css('max-width: 920px; margin: 0 auto; padding: clamp(28px, 5vw, 48px) 24px 64px; display: flex; flex-direction: column; gap: 24px;')}>
          <section aria-labelledby="overall" style={css('padding: clamp(24px, 5vw, 56px) 0 8px; display: flex; flex-direction: column; gap: 20px;')}>
            <div style={css('display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 16px;')}>
              <div style={css('display: flex; flex-direction: column; gap: 8px;')}>
                <span style={css('font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;')}>System status</span>
                <h1 id="overall" role="status" style={css('font-size: clamp(22px, 3vw, 30px); font-weight: 500; letter-spacing: -0.5px; margin: 0; display: flex; align-items: center; gap: 12px; color: #1a1a1e;')}>
                  <span style={css('font-family: var(--font-mono); font-size: 22px; color: ' + color + ';')}>{glyph}</span>
                  {title}
                </h1>
                <p style={css('font-size: 14px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 580px;')}>{detail}</p>
              </div>
              <div style={css('display: flex; flex-direction: column; align-items: flex-end; gap: 8px;')}>
                <span style={css('display: inline-flex; gap: 6px; align-items: center; white-space: nowrap; font-size: 12px; font-weight: 500; padding: 4px 12px; border-radius: 999px; color: #f5f4f1; background: ' + color + ';')}>
                  <span style={css('font-family: var(--font-mono);')}>{glyph}</span>
                  {pill}
                </span>
                {apiUrl ? (
                  <button
                    type="button"
                    onClick={() => void refresh()}
                    disabled={checking}
                    style={css('font-family: inherit; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; min-height: 34px; padding: 0 12px; border-radius: 6px; font-size: 13px; font-weight: 500; color: #1a1a1e; background: #f5f4f1; border: 1px solid #d8d6d0; cursor: ' + (checking ? 'wait' : 'pointer') + '; opacity: ' + (checking ? '0.6' : '1') + ';')}
                    className="hv-4dee937b"
                  >
                    <span style={css('font-family: var(--font-mono);')}>↻</span>
                    {checking ? 'Checking…' : 'Check again'}
                  </button>
                ) : null}
              </div>
            </div>
            <div style={css('display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; padding-top: 14px; border-top: 1px solid rgba(26,26,30,0.08);')}>
              <span style={css('font-family: var(--font-mono); font-size: 12px; color: #6b6a65;')}>{checkedText}</span>
              <div style={css('display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: #4a4945;')}>
                {(['operational', 'degraded', 'outage', 'no_data'] as DayStatus[]).map((s) => (
                  <span key={s} style={css('display: inline-flex; gap: 6px; align-items: center;')}>
                    <span aria-hidden="true" style={css('width: 10px; height: 10px; border-radius: 2px; background: ' + BAR[s] + ';')} />
                    {s === 'no_data' ? 'No data' : TONE[s][1]}
                  </span>
                ))}
              </div>
            </div>
          </section>

          {components.length === 0 ? (
            <div style={css('border: 1px dashed #c9c7c0; border-radius: 8px; padding: 24px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; background: #eceae5;')}>
              <span style={css('font-size: 14px; font-weight: 500;')}>
                {unconfigured ? (pilot ? 'Shared directly with pilot partners' : 'No component data') : checking ? 'Waiting for the check' : 'No components reported'}
              </span>
              <span style={css('font-size: 13px; line-height: 1.55; color: #6b6a65; max-width: 560px;')}>
                {unconfigured && pilot
                  ? 'Aether runs in private pilots, and each pilot partner receives service status from its Olympus Labs contact. A public status page opens with general availability.'
                  : unconfigured
                    ? 'VITE_STATUS_API_URL is not set for this build, so no component can be verified. Nothing is shown as operational by default.'
                    : 'Components appear once the endpoint responds.'}
              </span>
            </div>
          ) : (
            GROUPS.map(([group, name, groupGlyph, groupColor]) => {
              const items = components.filter((c) => groupOf(c.key) === group);
              if (!items.length) return null;
              const affected = items.filter((c) => c.state !== 'operational').length;
              return (
                <details key={group} open style={css('border-top: 1px solid #d8d6d0;')}>
                  <summary style={css('list-style: none; cursor: pointer; padding: 14px 0; display: flex; justify-content: space-between; gap: 8px; align-items: center;')}>
                    <span style={css('display: flex; gap: 10px; align-items: center; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #4a4945;')}>
                      <span aria-hidden="true" style={css('font-family: var(--font-mono); font-size: 12px; color: #6b6a65; width: 12px;')}>
                        ⌄
                      </span>
                      <span style={css('font-family: var(--font-mono); color: ' + groupColor + ';')}>{groupGlyph}</span>
                      {name}
                    </span>
                    <span style={css('font-family: var(--font-mono); font-size: 11px; color: ' + (affected ? '#8a6433' : '#4f7a5e') + ';')}>
                      {affected ? `${affected} of ${items.length} affected` : `all ${items.length} operational`}
                    </span>
                  </summary>
                  {items.map((c) => {
                    const [g, label, ink, bg] = TONE[c.state];
                    const days = fillDays(history?.components[c.key], DAYS, today);
                    const pct = uptime(days);
                    return (
                      <div key={c.key} style={css('padding: 12px 0 16px; display: flex; flex-direction: column; gap: 8px;')}>
                        <div style={css('display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;')}>
                          <span style={css('display: flex; align-items: baseline; gap: 10px; min-width: 0;')}>
                            <span style={css('font-size: 14px; font-weight: 500;')}>{c.label}</span>
                            <span style={css('font-family: var(--font-mono); font-size: 11px; color: #9c9b95;')}>component:{c.key}</span>
                          </span>
                          <span style={css('display: flex; align-items: center; gap: 10px;')}>
                            <span style={css('font-family: var(--font-mono); font-size: 12px; color: ' + (pct === null ? '#9c9b95' : pct > 99.9 ? '#4f7a5e' : pct > 99.7 ? '#8a6433' : '#a3473c') + ';')}>
                              {pct === null ? '—' : `${pct.toFixed(2)}%`}
                            </span>
                            <span
                              title={c.detail || undefined}
                              style={css('display: inline-flex; gap: 6px; align-items: center; font-size: 12px; font-weight: 500; padding: 3px 10px; border-radius: 999px; white-space: nowrap; color: ' + ink + '; background: ' + bg + '; border: 1px solid ' + ink + '33;')}
                            >
                              <span style={css('font-family: var(--font-mono);')}>{g}</span>
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

          <section aria-labelledby="hist" style={css('display: flex; flex-direction: column; gap: 12px;')}>
            <div style={css('display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px;')}>
              <h2 id="hist" style={css('font-size: 18px; font-weight: 500; margin: 0; color: #1a1a1e;')}>
                Past incidents
              </h2>
              <div role="radiogroup" aria-label="Range" style={css('display: inline-flex; border: 1px solid #d8d6d0; border-radius: 6px; padding: 2px; background: #eceae5;')}>
                {RANGES.map(([days, label]) => (
                  <button
                    key={days}
                    type="button"
                    role="radio"
                    aria-checked={range === days}
                    onClick={() => setRange(days)}
                    style={css('font-family: inherit; font-size: 12px; font-weight: 500; padding: 5px 10px; border-radius: 4px; border: 0; cursor: pointer; ' + (range === days ? 'background: #f5f4f1; color: #1a1a1e; box-shadow: 0 0 0 1px #d8d6d0;' : 'background: transparent; color: #6b6a65;'))}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {incidents.length > 0 ? (
              <div style={css('border: 1px solid #d8d6d0; border-radius: 8px; overflow: hidden;')}>
                {incidents.map((i, n) => (
                  <details key={i.id} style={css((n < incidents.length - 1 ? 'border-bottom: 1px solid #e2e0da; ' : '') + 'border-left: 3px solid ' + (i.resolvedAt ? '#c9975a' : '#b5564a') + ';')}>
                    <summary style={css('list-style: none; cursor: pointer; padding: 14px 18px; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;')} className="hv-2a0af8aa">
                      <span style={css('display: flex; gap: 10px; align-items: baseline;')}>
                        <span aria-hidden="true" style={css('font-family: var(--font-mono); font-size: 12px; color: #6b6a65;')}>
                          ›
                        </span>
                        <span style={css('font-size: 14px; font-weight: 500;')}>{i.title}</span>
                      </span>
                      <span style={css('font-family: var(--font-mono); font-size: 12px; color: ' + (i.resolvedAt ? '#4f7a5e' : '#a3473c') + ';')}>
                        ● {i.resolvedAt ? 'resolved' : i.status} · {formatDay(i.startedAt.slice(0, 10))}
                      </span>
                    </summary>
                    <div style={css('padding: 0 18px 14px 40px; display: flex; flex-direction: column; gap: 4px;')}>
                      <span style={css('font-family: var(--font-mono); font-size: 11px; color: #6b6a65;')}>
                        {formatTime(i.startedAt)}
                        {i.resolvedAt ? ` – ${formatTime(i.resolvedAt)}` : ' · ongoing'}
                        {i.components.length ? ` · ${i.components.join(', ')}` : ''}
                      </span>
                    </div>
                  </details>
                ))}
              </div>
            ) : (
              <div style={css('border: 1px dashed #c9c7c0; border-radius: 8px; padding: 20px; font-size: 13px; line-height: 1.55; color: #6b6a65;')}>
                {history ? `No incidents reported in the last ${range} days.` : 'Incident history appears here once an incident feed is connected.'}
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}
