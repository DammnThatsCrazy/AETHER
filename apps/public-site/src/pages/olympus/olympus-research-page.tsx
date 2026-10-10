/**
 * Built from design/designs/Olympus Research.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useDesignState, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './olympus-research-page.css';

const AREAS = [
  ['identity', 'Knowing it’s the same person', 'Records from different tools often describe the same person. Joining them is easy to get wrong.', 'When is the evidence strong enough to say two records are the same person — and how do you undo it if not?'],
  ['temporal', 'Journeys over time', 'People pause, switch devices, come back weeks later, and hand off to AI agents.', 'How do you keep one journey together across all of that?'],
  ['attribution', 'Fair credit', 'An ad, an email, an AI agent, and a person’s approval all lead to one sale.', 'How much credit does an agent deserve for a result a person approved?'],
  ['agents', 'People and AI agents, together', 'A person asks an agent, which starts other agents, which act on real systems.', 'How do you keep track of who allowed what, all the way down the chain?'],
  ['economic', 'Following the money', 'Payments, refunds, and settlements mean different things in different systems.', 'How do you connect them to the people and journeys behind them without losing their meaning?'],
  ['assurance', 'Proving it’s safe', 'Some organizations need Aether in their own environment, sometimes fully offline.', 'What evidence actually proves a boundary held?'],
];
const GATES = ['An owner', 'A clear contract', 'Tests', 'Proof it works in real deployments'].map((t, i) => ({ t, n: '0' + (i + 1) }));

export function OlympusResearchPage() {
  const link = useLink();
  usePageMeta('olympus-research');
  const [state, setState] = useDesignState<{ open: string | null }>({ open: 'identity' });
  const areas = AREAS.map(([k, t, b, q]) => {
    const open = state.open === k;
    return { t, b, q, open, exp: open ? 'true' : 'false', sign: open ? '−' : '+', go: () => setState({ open: open ? null : k! }) };
  });
  const gates = GATES;
  return (
    <div className="dc pg-olympus-research">
    <div data-page="olympus-research" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="olympus" active="Research" />
      <main id="main" tabIndex={-1}>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(64px, 9vw, 112px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"Research"}
            </span>
            <h1 style={css("font-size: clamp(48px, 7.6vw, 104px); font-weight: 500; line-height: 0.94; letter-spacing: -0.05em; margin: 0; max-width: 960px; text-wrap: balance;")}>
              {"Hard questions, worked on in the open."}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 19px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 560px;")}>
              {"Problems existing technology hasn’t solved cleanly. Research here is a direction, not a promise — it ships only when it’s proven."}
            </p>
          </div>
        </section>
        <section style={css("border-top: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1000px; margin: 0 auto; padding: 0 24px clamp(80px, 11vw, 144px);")}>
            <div style={css("display: flex; flex-direction: column;")}>
              {(areas).map((a: any, aIndex: number) => (
                <Fragment key={aIndex}>
                  <button type="button" onClick={a.go} aria-expanded={a.exp} style={css("font-family: inherit; text-align: left; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px; align-items: baseline; padding: clamp(24px, 3.4vw, 36px) 0; border: 0; border-bottom: 1px solid #d8d6d0; background: transparent; color: #1a1a1e; cursor: pointer;")}>
                    <span style={css("display: flex; flex-direction: column; gap: 10px;")}>
                      <span style={css("font-size: clamp(22px, 2.8vw, 32px); font-weight: 500; letter-spacing: -0.022em;")}>
                        {a.t}
                      </span>
                      <span style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; max-width: 620px;")}>
                        {a.b}
                      </span>
                      {(a.open) ? (
                        <>
                          <span style={css("font-size: clamp(17px, 1.8vw, 20px); line-height: 1.45; color: #1a1a1e; padding-left: 16px; border-left: 2px solid #1a1a1e; max-width: 620px;")}>
                            {a.q}
                          </span>
                        </>
                      ) : null}
                    </span>
                    <span style={css("font-family: var(--font-mono); font-size: 16px; color: #6b6a65;")}>
                      {a.sign}
                    </span>
                  </button>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: clamp(40px, 6vw, 96px); align-items: start;")}>
            <h2 style={css("font-size: clamp(30px, 3.8vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; color: #e8e6e1; text-wrap: balance;")}>
              {"Before anything ships, it needs four things."}
            </h2>
            <ol style={css("list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border-top: 1px solid #2a2a2f;")}>
              {(gates).map((g: any, gIndex: number) => (
                <Fragment key={gIndex}>
                  <li style={css("display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 16px; align-items: baseline; padding: 20px 0; border-bottom: 1px solid #2a2a2f;")}>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #8a8984;")}>
                      {g.n}
                    </span>
                    <span style={css("font-size: 19px; font-weight: 500; color: #e8e6e1;")}>
                      {g.t}
                    </span>
                  </li>
                </Fragment>
              ))}
            </ol>
          </div>
        </section>
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 13vw, 168px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <h2 style={css("font-size: clamp(32px, 4.8vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; max-width: 720px; text-wrap: balance;")}>
              {"Working on one of these?"}
            </h2>
            <a href={link("Contact.dc.html?brand=olympus&type=research")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
              {"Collaborate"}
              <span style={css("font-family: var(--font-mono);")}>
                {"→"}
              </span>
            </a>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
