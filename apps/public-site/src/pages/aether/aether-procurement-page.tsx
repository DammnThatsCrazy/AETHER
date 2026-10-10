/**
 * Built from design/designs/Aether Procurement.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useDesignState, useLink, useReducedMotion } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-procurement-page.css';

import { useEffect } from 'react';

const EASE = 'cubic-bezier(0.22,1,0.36,1)';
const STEPS: [label: string, body: string, ask: string][] = [
  ['Introduction', 'The question you want answered, the tools involved, and the result that matters.', 'a short call, a written summary'],
  ['Security review', 'Architecture, data separation, consent, retention, and how Aether is run.', 'architecture notes, data-handling summary, subprocessor list'],
  ['Pilot scope', 'Which tools, how success is measured, the starting baseline, and the timeline — agreed in writing.', 'a written plan with a named contact'],
  ['Order', 'The plan, term, and billing. Self-service plans check out online through Stripe.', 'an order form or online checkout'],
  ['Onboarding', 'Connect your tools, confirm the first events arrive, and review the first results together.', 'a setup walkthrough'],
];
const TERMS = [['Plans', 'Alpha, Beta, Gamma, and Delta grow with how much Aether does for you. Larger plans are by agreement.'], ['Billing', 'Monthly subscriptions and invoices through Stripe. Enterprise terms are agreed in writing.'], ['Pilots', 'Limited in scope and time, with the success measures agreed up front.']].map(([k, v]) => ({ k, v }));

export function AetherProcurementPage() {
  const link = useLink();
  usePageMeta('aether-procurement');
  const [state, setState] = useDesignState({ step: 0, held: false });
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce || state.held) return undefined;
    const timer = setInterval(() => setState((s) => ({ step: (s.step + 1) % STEPS.length })), 4000);
    return () => clearInterval(timer);
  }, [reduce, state.held, setState]);
  const k = state.step;
  const tabs = STEPS.map(([l], i) => {
    const on = i === k;
    return { label: i + 1 + ' · ' + l, sel: on ? 'true' : 'false', go: () => setState({ step: i, held: true }), style: 'font-family: inherit; min-height: 36px; padding: 0 14px; border-radius: 7px; border: 0; cursor: pointer; font-size: 13px; font-weight: 500; transition: background-color 120ms ' + EASE + ', color 120ms ' + EASE + '; ' + (on ? 'background: #e8e6e1; color: #111114;' : 'background: transparent; color: #a09f99;') };
  });
  const cur = { n: '0' + (k + 1), t: STEPS[k]![0], b: STEPS[k]![1], ask: STEPS[k]![2] };
  const terms = TERMS;
  return (
    <div className="dc pg-aether-procurement">
    <div data-page="aether-procurement" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="" />
      <main id="main">
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(56px, 8vw, 96px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <span style={css("display: flex; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              <a href={link("Aether Trust.dc.html")} style={css("color: #6b6a65; text-decoration: none;")}>
                {"Trust"}
              </a>
              <span>
                {"/"}
              </span>
              <span style={css("color: #1a1a1e;")}>
                {"Procurement"}
              </span>
            </span>
            <h1 style={css("font-size: clamp(44px, 7vw, 96px); font-weight: 500; line-height: 0.95; letter-spacing: -0.048em; margin: 0; text-wrap: balance;")}>
              {"Everything your review will ask for."}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 19px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 560px;")}>
              {"How Aether is bought, billed, reviewed, and deployed — and what to ask for at each step."}
            </p>
          </div>
        </section>
        <section data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 880px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; gap: 36px;")}>
            <h2 style={css("font-size: clamp(28px, 3.6vw, 44px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.06; margin: 0; color: #e8e6e1; text-align: center;")}>
              {"Five steps from first call to live."}
            </h2>
            <div role="tablist" aria-label="Steps" style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 4px; padding: 4px; border-radius: 10px; background: #1a1a1e; border: 1px solid #2a2a2f;")}>
              {(tabs).map((t: any, tIndex: number) => (
                <Fragment key={tIndex}>
                  <button type="button" role="tab" aria-selected={t.sel} onClick={t.go} style={css(t.style)}>
                    {t.label}
                  </button>
                </Fragment>
              ))}
            </div>
            <div style={css("width: 100%; max-width: 640px; display: flex; flex-direction: column; gap: 14px; text-align: center; align-items: center; min-height: 180px; animation: pcIn 200ms cubic-bezier(0.22,1,0.36,1) both;")}>
              <span style={css("font-family: var(--font-mono); font-size: 12px; color: #8a8984;")}>
                {cur.n}{" of 05"}
              </span>
              <span style={css("font-size: clamp(24px, 3vw, 34px); font-weight: 500; letter-spacing: -0.02em; color: #e8e6e1;")}>
                {cur.t}
              </span>
              <span style={css("font-size: 16px; line-height: 1.6; color: #a09f99;")}>
                {cur.b}
              </span>
              <span style={css("font-family: var(--font-mono); font-size: 12px; color: #dcb683;")}>
                {"You can ask for: "}{cur.ask}
              </span>
            </div>
          </div>
        </section>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 880px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; gap: 36px;")}>
            <h2 style={css("font-size: clamp(28px, 3.6vw, 44px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.06; margin: 0; text-align: center;")}>
              {"Pricing, billing, and pilots."}
            </h2>
            <dl style={css("width: 100%; margin: 0; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              {(terms).map((x: any, xIndex: number) => (
                <Fragment key={xIndex}>
                  <div style={css("display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 20px; align-items: baseline; padding: 20px 0; border-bottom: 1px solid #d8d6d0;")}>
                    <dt style={css("font-size: 17px; font-weight: 500;")}>
                      {x.k}
                    </dt>
                    <dd style={css("margin: 0; font-size: 15px; line-height: 1.6; color: #4a4945;")}>
                      {x.v}
                    </dd>
                  </div>
                </Fragment>
              ))}
            </dl>
          </div>
        </section>
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 13vw, 160px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 20px;")}>
            <h2 style={css("font-size: clamp(32px, 4.8vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; text-wrap: balance;")}>
              {"Tell us what your process needs."}
            </h2>
            <p style={css("font-size: 16px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 460px;")}>
              {"It goes to the person who can answer."}
            </p>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;")}>
              <a href={link("Contact.dc.html?brand=aether&type=security")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {"Request a security review"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Aether Pricing.dc.html")} style={css("display: inline-flex; align-items: center; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-67a914b1">
                {"See pricing"}
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
