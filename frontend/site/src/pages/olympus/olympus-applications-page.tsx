/**
 * Built from design/designs/Olympus Applications.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useDesignState, useLink, useReducedMotion } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './olympus-applications-page.css';

import { useEffect } from 'react';

const EASE = 'cubic-bezier(0.22,1,0.36,1)';
const APPS: [label: string, g: string, c: string, t: string, b: string, sees: string[], href: string, cta: string][] = [
  ['Commercial', '◈', '#9fbad6', 'Know every customer, across every tool.', 'One person shows up as many records. Olympus technology puts them back together and shows what led to each sale.', ['identity', 'journeys', 'value'], 'Aether Customer Intelligence.dc.html', 'See the customer scenario'],
  ['People and AI', '⬡', '#dcb683', 'Keep track of who asked, and who did it.', 'When people hand work to AI agents, and agents to other agents, someone should still be able to see who allowed what.', ['authority', 'lineage', 'outcomes'], 'Aether Agents.dc.html', 'See agent tracking'],
  ['Autonomous', '◉', '#8fb0cc', 'Many systems acting at once, in sync.', 'Fleets of software and machines need a shared picture of what’s happening and what each one is doing.', ['coordination', 'activity', 'state'], 'Olympus Research.dc.html', 'Read the research'],
  ['Trust', '✓', '#9cc4a9', 'Prove what was allowed, and what happened.', 'Consent, rules, approvals, and records that hold up when someone asks.', ['consent', 'evidence', 'accountability'], 'Aether Trust.dc.html', 'See how trust works'],
  ['Operations', '○', '#c9b088', 'See what’s happening now, next to what happened before.', 'Activity from every system on one timeline, so change is visible while it matters.', ['activity', 'timeline', 'change'], 'Aether Applications.dc.html#operations', 'See operations'],
  ['Money', '↑', '#e09a8f', 'Follow the money to the people behind it.', 'Payments, refunds, and settlements mean different things in different systems. Connect them to the journeys that produced them.', ['payments', 'settlement', 'credit'], 'Aether Applications.dc.html#revenue', 'See revenue tracing'],
];

export function OlympusApplicationsPage() {
  const link = useLink();
  usePageMeta('olympus-applications');
  const [state, setState] = useDesignState({ k: 0, held: false });
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce || state.held) return undefined;
    const timer = setInterval(() => setState((s) => ({ k: (s.k + 1) % APPS.length })), 4200);
    return () => clearInterval(timer);
  }, [reduce, state.held, setState]);
  const k = state.k;
  const c = APPS[k]!;
  const tabs = APPS.map(([label], i) => {
    const on = i === k;
    return { label, sel: on ? 'true' : 'false', go: () => setState({ k: i, held: true }), style: 'font-family: inherit; min-height: 36px; padding: 0 14px; border-radius: 7px; border: 0; cursor: pointer; font-size: 13px; font-weight: 500; transition: background-color 120ms ' + EASE + ', color 120ms ' + EASE + '; ' + (on ? 'background: #e8e6e1; color: #111114;' : 'background: transparent; color: #a09f99;') };
  });
  const cur = { t: c[3], b: c[4], sees: c[5], href: c[6], cta: c[7], g: c[1], gStyle: 'font-family: var(--font-mono); font-size: 28px; color: ' + c[2] + ';' };
  return (
    <div className="dc pg-olympus-applications">
    <div data-page="olympus-applications" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="olympus" active="Applications" />
      <main id="main" tabIndex={-1}>
        <section>
          <div style={css("max-width: 1000px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(64px, 9vw, 112px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"Applications"}
            </span>
            <h1 style={css("font-size: clamp(48px, 7.6vw, 104px); font-weight: 500; line-height: 0.94; letter-spacing: -0.05em; margin: 0; max-width: 900px; text-wrap: balance;")}>
              {"One technology. Many kinds of work."}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 19px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 560px;")}>
              {"These aren’t six products. They’re six places the same technology is used. Pick one."}
            </p>
          </div>
        </section>
        <section data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1000px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; gap: 40px;")}>
            <div role="tablist" aria-label="Application areas" style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 4px; padding: 4px; border-radius: 10px; background: #1a1a1e; border: 1px solid #2a2a2f;")}>
              {(tabs).map((t: any, tIndex: number) => (
                <Fragment key={tIndex}>
                  <button type="button" role="tab" aria-selected={t.sel} onClick={t.go} style={css(t.style)}>
                    {t.label}
                  </button>
                </Fragment>
              ))}
            </div>
            <div style={css("width: 100%; max-width: 680px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 18px; min-height: 260px; animation: apIn 200ms cubic-bezier(0.22,1,0.36,1) both;")}>
              <span style={css(cur.gStyle)}>
                {cur.g}
              </span>
              <span style={css("font-size: clamp(26px, 3.4vw, 40px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.1; color: #e8e6e1; text-wrap: balance;")}>
                {cur.t}
              </span>
              <span style={css("font-size: 16px; line-height: 1.6; color: #a09f99;")}>
                {cur.b}
              </span>
              <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; margin-top: 6px;")}>
                {(cur.sees).map((s: any, sIndex: number) => (
                  <Fragment key={sIndex}>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; padding: 5px 10px; border: 1px solid #2a2a2f; border-radius: 6px; color: #a09f99;")}>
                      {s}
                    </span>
                  </Fragment>
                ))}
              </div>
              <a href={link(cur.href)} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #e8e6e1; text-decoration: none; margin-top: 8px;")} className="hv-6f6d4759">
                {cur.cta}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
            </div>
          </div>
        </section>
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 13vw, 168px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <h2 style={css("font-size: clamp(32px, 4.8vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; max-width: 720px; text-wrap: balance;")}>
              {"Seeing your own use case?"}
            </h2>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;")}>
              <a href={link("Contact.dc.html?brand=olympus&type=pilot")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {"Start a conversation"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Aether Applications.dc.html")} style={css("display: inline-flex; align-items: center; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-67a914b1">
                {"See Aether’s applications"}
              </a>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
