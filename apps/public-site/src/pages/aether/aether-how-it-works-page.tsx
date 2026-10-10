/**
 * Built from design/designs/Aether How It Works.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, portalLabel, useDesignState, useLink, useReducedMotion } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { AetherScene } from '@site/components/aether-scene';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-how-it-works-page.css';

import { useEffect, useRef } from 'react';

const EASE = 'cubic-bezier(0.22,1,0.36,1)';
const STEPS: [title: string, body: string, stage: number, color: string][] = [
  ['Connect', 'Aether receives activity from the tools you already use.', 0, '#9fbad6'],
  ['Recognize', 'Aether works out which people, companies, AI agents, and apps were involved.', 1, '#9cc4a9'],
  ['Relate', 'Activity becomes connections, timelines, and journeys.', 2, '#dcb683'],
  ['Understand', 'Aether spots patterns, value, and anything it isn’t sure about.', 3, '#c9b088'],
  ['Act', 'People and tools use what Aether learned to investigate, decide, and automate.', 3, '#e09a8f'],
];
const QUESTIONS: [string, string][] = [['What', 'happened?'], ['Who', 'or what was involved?'], ['Where', 'did it happen?'], ['When', 'did it happen?'], ['What', 'was it connected to?'], ['Before', 'what happened before it?'], ['After', 'what happened after it?'], ['Who', 'influenced it?'], ['Value', 'what value did it create?'], ['Why', 'does it matter?'], ['Next', 'what can happen next?']];
const QC = ['#3a6896', '#3a6896', '#5a85a8', '#6b6a65', '#3a6896', '#6b6a65', '#6b6a65', '#a8783e', '#4f7a5e', '#8a6433', '#a3473c'];
const PIPELINE: [string, string, string][] = [['01', 'Connect', 'SDK / connector / import → /v1/batch'], ['02', 'Recognize', 'Bronze → Silver normalization · identity resolution'], ['03', 'Relate', 'campaign, journey, communication, agent resolution'], ['04', 'Understand', 'value resolution · graph outbox · tenant-scoped projections'], ['05', 'Act', 'lenses and 360s · APIs · MCP · CLI']];

export function AetherHowItWorksPage() {
  const link = useLink();
  usePageMeta('aether-how-it-works');
  const reduce = useReducedMotion();
  const [state, setState] = useDesignState<{ step: number; tech: boolean; held: boolean }>({ step: 0, tech: false, held: false });
  const heldRef = useRef(false);
  heldRef.current = state.held;
  useEffect(() => {
    if (reduce) return;
    const timer = setInterval(() => {
      if (!heldRef.current) setState((s) => ({ step: (s.step + 1) % 5 }));
    }, 3200);
    return () => clearInterval(timer);
  }, [reduce, setState]);
  const st = state.step;
  const steps = STEPS.map(([title, body, , c], i) => {
    const on = i === st;
    return {
      n: '0' + (i + 1), title, body, open: on, sel: on, go: () => setState({ step: i, held: true }),
      numStyle: 'width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 12px; flex-shrink: 0; transition: background-color 200ms ' + EASE + ', color 200ms ' + EASE + '; ' + (on ? 'background: ' + c + '; color: #111114;' : 'background: #1a1a1e; color: #a09f99; border: 1px solid #2a2a2f; box-sizing: border-box;'),
      style: 'font-family: inherit; text-align: left; width: 100%; display: flex; flex-direction: column; gap: 10px; padding: 18px; border-radius: 12px; cursor: pointer; color: ' + (on ? '#e8e6e1' : '#a09f99') + '; transition: background-color 200ms ' + EASE + ', border-color 200ms ' + EASE + ', color 200ms ' + EASE + '; ' + (on ? 'background: #1a1a1e; border: 1px solid #3a3a40;' : 'background: transparent; border: 1px solid transparent;'),
    };
  });
  const sceneStage = STEPS[st]![2];
  const stepLabel = '0' + (st + 1) + ' · ' + STEPS[st]![0].toLowerCase();
  const asks = QUESTIONS.map(([k, q], i) => ({
    k: k.toUpperCase(),
    q: k === 'What' || k === 'Who' || k === 'Where' || k === 'When' || k === 'Why' ? k + ' ' + q : q.charAt(0).toUpperCase() + q.slice(1),
    kStyle: 'font-family: var(--font-mono); font-size: 12px; font-weight: 500; color: ' + QC[i] + ';',
  }));
  const pipeline = PIPELINE.map(([n, plain, tech]) => ({ n, plain, tech }));
  const showTech = state.tech;
  const techStr = state.tech;
  const techLabel = state.tech ? 'Hide technical detail' : 'Show technical detail';
  const techGlyph = state.tech ? '−' : '+';
  const toggleTech = () => setState((s) => ({ tech: !s.tech }));
  return (
    <div className="dc pg-aether-how-it-works">
    <div data-page="aether-how-it-works" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Platform" />
      <main id="main" tabIndex={-1}>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 9vw, 120px) 24px clamp(40px, 6vw, 72px); display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); gap: 32px; align-items: end;")}>
            <div style={css("display: flex; flex-direction: column; gap: 20px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #4f7a5e;")}>
                {"How it works"}
              </span>
              <h1 style={css("font-size: clamp(44px, 6.4vw, 84px); font-weight: 500; line-height: 0.96; letter-spacing: -0.045em; margin: 0; text-wrap: balance;")}>
                {"How Aether works."}
              </h1>
            </div>
            <p style={css("font-size: 17px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 500px; padding-bottom: 8px;")}>
              {"Five steps, from activity in the tools you already use to answers you can act on."}
            </p>
          </div>
        </section>
        <section id="steps" data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(48px, 7vw, 88px) 24px; display: flex; flex-wrap: wrap; gap: clamp(24px, 4vw, 56px); align-items: stretch;")}>
            <ol style={css("flex: 1 1 340px; list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px;")}>
              {(steps).map((s: any, sIndex: number) => (
                <Fragment key={sIndex}>
                  <li style={css("display: flex;")}>
                    <button type="button" onClick={s.go} aria-pressed={s.sel} style={css(s.style)}>
                      <span style={css("display: flex; align-items: center; gap: 12px;")}>
                        <span style={css(s.numStyle)}>
                          {s.n}
                        </span>
                        <span style={css("font-size: 20px; font-weight: 500; letter-spacing: -0.3px;")}>
                          {s.title}
                        </span>
                      </span>
                      {(s.open) ? (
                        <>
                          <span style={css("font-size: 15px; line-height: 1.6; color: #a09f99; padding-left: 44px;")}>
                            {s.body}
                          </span>
                        </>
                      ) : null}
                    </button>
                  </li>
                </Fragment>
              ))}
            </ol>
            <div style={css("flex: 1.4 1 480px; min-width: 0; border: 1px solid #2a2a2f; border-radius: 12px; background: #1a1a1e; padding: 20px; display: flex; flex-direction: column; gap: 14px; box-sizing: border-box;")}>
              <div style={css("display: flex; justify-content: space-between; align-items: center;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {"Synthetic example"}
                </span>
                <span style={css("font-family: var(--font-mono); font-size: 11px; color: #9cc4a9;")}>
                  {stepLabel}
                </span>
              </div>
              <AetherScene dark={true} story="customer" stage={sceneStage} controls={false} />
            </div>
          </div>
        </section>
        <section id="questions" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 104px) 24px; display: flex; flex-wrap: wrap; gap: clamp(24px, 4vw, 56px); align-items: flex-start;")}>
            <div style={css("flex: 1 1 300px; display: flex; flex-direction: column; gap: 14px; position: sticky; top: 96px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #3a6896;")}>
                {"The same thing, every time"}
              </span>
              <h2 style={css("font-size: clamp(30px, 3.8vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
                {"Something happened. Aether works out:"}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"Whatever you’re looking at — a customer, a campaign, an AI agent, a sale — Aether is answering these same questions. Everything else is the engineering that makes the answers reliable."}
              </p>
            </div>
            <ol style={css("flex: 1.6 1 460px; list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              {(asks).map((a: any, aIndex: number) => (
                <Fragment key={aIndex}>
                  <li style={css("display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 16px; align-items: baseline; padding: 14px 0; border-bottom: 1px solid #d8d6d0;")}>
                    <span style={css(a.kStyle)}>
                      {a.k}
                    </span>
                    <span style={css("font-size: clamp(17px, 1.7vw, 21px); font-weight: 500; letter-spacing: -0.01em;")}>
                      {a.q}
                    </span>
                  </li>
                </Fragment>
              ))}
            </ol>
          </div>
        </section>
        <section id="technical" style={css("border-bottom: 1px solid #d8d6d0; background: #eceae5;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 104px) 24px; display: flex; flex-direction: column; gap: 24px;")}>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 24px; align-items: end;")}>
              <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                  {"For technical evaluators"}
                </span>
                <h2 style={css("font-size: clamp(28px, 3.4vw, 44px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0;")}>
                  {"The same steps, in technical detail."}
                </h2>
              </div>
              <div style={css("display: flex; justify-content: flex-start;")}>
                <button type="button" onClick={toggleTech} aria-expanded={techStr} style={css("font-family: inherit; display: inline-flex; align-items: center; gap: 8px; min-height: 42px; padding: 0 18px; border-radius: 6px; font-size: 14px; font-weight: 500; cursor: pointer; background: #2563eb; color: #f5f4f1; border: 1px solid #2563eb;")}>
                  {techLabel}
                  <span style={css("font-family: var(--font-mono);")}>
                    {techGlyph}
                  </span>
                </button>
              </div>
            </div>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr)); gap: 6px;")}>
              {(pipeline).map((p: any, pIndex: number) => (
                <Fragment key={pIndex}>
                  <div style={css("display: flex; flex-direction: column; gap: 6px; padding: 16px; border-radius: 10px; background: #f5f4f1; border: 1px solid #d8d6d0;")}>
                    <span style={css("font-family: var(--font-mono); font-size: 11px; color: #9c9b95;")}>
                      {p.n}
                    </span>
                    <span style={css("font-size: 15px; font-weight: 500;")}>
                      {p.plain}
                    </span>
                    {(showTech) ? (
                      <>
                        <span style={css("font-family: var(--font-mono); font-size: 11px; line-height: 1.6; color: #4a4945; padding-top: 8px; border-top: 1px dashed #c9c7c0;")}>
                          {p.tech}
                        </span>
                      </>
                    ) : null}
                  </div>
                </Fragment>
              ))}
            </div>
            {(showTech) ? (
              <>
                <pre style={css("margin: 0; font-family: var(--font-mono); font-size: 12px; line-height: 1.7; color: #e8e6e1; background: #111114; border: 1px solid #2a2a2f; border-radius: 10px; padding: 18px 20px; overflow-x: auto;")}>
                  {"SDKs / providers / connectors\n→ canonical observation envelopes\n→ /v1/batch ingestion\n→ Bronze/Silver normalization\n→ identity, campaign, journey, communication, agent, and value resolution\n→ graph outbox\n→ tenant-scoped graph projections\n→ lenses and 360s\n→ Aether, Kyber, Noesis, developer APIs, MCP, and CLI surfaces"}
                </pre>
              </>
            ) : null}
            <a href={link("Docs.dc.html?page=how-it-works")} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none;")} className="hv-cc8e330e">
              {"Read the architecture docs"}
              <span style={css("font-family: var(--font-mono);")}>
                {"→"}
              </span>
            </a>
          </div>
        </section>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: flex; flex-direction: column; gap: 20px; align-items: flex-start;")}>
            <h2 style={css("font-size: clamp(30px, 4.2vw, 52px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.04; margin: 0; max-width: 760px; text-wrap: balance;")}>
              {"Connect one tool and watch your first customer come together."}
            </h2>
            <div style={css("display: flex; flex-wrap: wrap; gap: 8px;")}>
              <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {portalLabel("Get started")}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Aether Connect.dc.html")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-4d1362f5">
                {"Choose how to connect"}
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
