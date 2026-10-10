/**
 * Built from design/designs/Olympus Technology.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { asset, css, useDesignState, useLink } from '@site/design/runtime';
import { markSrc } from '@site/components/brand-mark';
import { usePageMeta } from '@site/design/page-meta';
import { AetherScene } from '@site/components/aether-scene';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './olympus-technology-page.css';

const EASE = 'cubic-bezier(0.22,1,0.36,1)';
const DIMS = [['⬡', 'Who', 'People, companies, AI agents, apps, and devices.', '#3a6896'], ['◉', 'What', 'Anything that happened, in any tool.', '#4f7a5e'], ['↔', 'Connections', 'How they’re linked — and how we know.', '#3a6896'], ['◷', 'When', 'What came before, and what came after.', '#6b6a65'], ['✓', 'Responsibility', 'Who acted, and on whose behalf.', '#a8783e'], ['↑', 'Value', 'What it was worth, and why.', '#4f7a5e']].map(([g, t, b, c], i) => ({ g, t, b, gStyle: 'font-family: var(--font-mono); font-size: 16px; color: ' + c + ';', style: 'display: flex; flex-direction: column; gap: 6px; padding: 22px ' + (i ? '20px' : '20px 22px 0') + '; ' + (i ? 'border-left: 1px solid #d8d6d0;' : '') }));
const VIEWS: [string, string][] = [['System view', 'Four systems hold four records. Each one is correct, and none of them is the whole story.'], ['Connected view', 'The same records, resolved into one entity — with every relationship traced to its evidence.'], ['Over time', 'Identity plus relationships plus time: the record becomes a history someone can reason about.']];
const LAYER_NAMES = [['⬡', 'identity'], ['↔', 'relationships'], ['◷', 'time'], ['✓', 'authority'], ['↑', 'value']];
const DEPTHS = [
  ['Level 1', '5 seconds', 'What is this?', 'Technology for understanding connected systems.'],
  ['Level 2', '30 seconds', 'What does it actually do?', 'Connect your systems. Aether observes activity, recognizes entities and relationships, builds a connected history — and you explore, query, and act on it.'],
  ['Level 3', '2–5 minutes', 'How could I use it?', 'Customer journeys, agent activity, communications, campaigns, value movement, identity, relationships, operations, risk.'],
  ['Level 4', 'technical evaluation', 'How does it actually work?', 'SDKs, connectors, APIs, event schemas, identity resolution, temporal graph, canonical contracts, MCP, security, tenant isolation, deployment.'],
].map(([n, time, q, a], i) => ({ n, time, q, a, style: 'display: flex; flex-direction: column; gap: 8px; padding: 24px; margin-left: ' + i * 18 + 'px; border: 1px solid #d8d6d0; border-radius: 12px; margin-bottom: 10px; background: ' + ['#fbfaf8', '#f5f4f1', '#eceae5', '#e2e0da'][i] + ';' }));

export function OlympusTechnologyPage() {
  const link = useLink();
  usePageMeta('olympus-technology');
  const [state, setState] = useDesignState({ view: 0 });
  const v = state.view;
  const lit = [0, 2, 3][v]!;
  const dims = DIMS;
  const viewStage = v;
  const viewTitle = VIEWS[v]![0];
  const viewBody = VIEWS[v]![1];
  const views = VIEWS.map(([label], i) => {
    const on = i === v;
    return { label, sel: on ? 'true' : 'false', go: () => setState({ view: i }), style: 'font-family: inherit; min-height: 36px; padding: 0 14px; border-radius: 7px; border: 0; cursor: pointer; font-size: 13px; font-weight: 500; transition: background-color 120ms ' + EASE + ', color 120ms ' + EASE + '; ' + (on ? 'background: #e8e6e1; color: #1a1a1e;' : 'background: transparent; color: #a09f99;') };
  });
  const layers = LAYER_NAMES.map(([g, t], i) => ({ g, t, style: 'display: flex; gap: 10px; align-items: center; font-size: 13px; padding: 8px 10px; border-radius: 6px; transition: background-color 200ms ' + EASE + ', color 200ms ' + EASE + ', border-color 200ms ' + EASE + '; border: 1px solid ' + (i < lit ? '#3a3a40' : '#2a2a2f') + '; background: ' + (i < lit ? '#1f1f24' : 'transparent') + '; color: ' + (i < lit ? '#e8e6e1' : '#6b6a65') + ';' }));
  const depths = DEPTHS;
  return (
    <div className="dc pg-olympus-technology">
    <div data-page="olympus-technology" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="olympus" active="Technology" />
      <main id="main" tabIndex={-1}>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 10vw, 136px) 24px clamp(48px, 7vw, 88px); display: flex; flex-direction: column; gap: 28px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #3a6896;")}>
              {"Technology"}
            </span>
            <h1 style={css("font-size: clamp(52px, 8.4vw, 120px); font-weight: 500; line-height: 0.92; letter-spacing: -0.05em; margin: 0; text-wrap: balance;")}>
              {"Technology that sees the whole picture."}
            </h1>
            <p style={css("font-size: 19px; line-height: 1.55; color: #4a4945; margin: 0; max-width: 640px; text-wrap: pretty;")}>
              {"Most software stores things in separate boxes. Olympus Labs builds technology that keeps the people, activity, connections, timing, responsibility, and value together — so people and AI can make sense of them."}
            </p>
          </div>
          <div style={css("border-top: 1px solid #d8d6d0;")}>
            <div style={css("max-width: 1200px; margin: 0 auto; padding: 0 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));")}>
              {(dims).map((d: any, dIndex: number) => (
                <Fragment key={dIndex}>
                  <div style={css(d.style)}>
                    <span style={css(d.gStyle)}>
                      {d.g}
                    </span>
                    <span style={css("font-size: 16px; font-weight: 500;")}>
                      {d.t}
                    </span>
                    <span style={css("font-size: 12px; line-height: 1.5; color: #6b6a65;")}>
                      {d.b}
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="views" data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: flex; flex-direction: column; gap: 32px;")}>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 24px; align-items: end;")}>
              <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #c9975a;")}>
                  {"◈ Two views of the same activity"}
                </span>
                <h2 style={css("font-size: clamp(30px, 4vw, 52px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.02; margin: 0; color: #e8e6e1; text-wrap: balance;")}>
                  {"What most tools see. What Olympus sees."}
                </h2>
              </div>
              <div role="tablist" aria-label="View" style={css("display: flex; gap: 4px; padding: 4px; border-radius: 10px; background: #1a1a1e; border: 1px solid #2a2a2f; justify-self: start;")}>
                {(views).map((v: any, vIndex: number) => (
                  <Fragment key={vIndex}>
                    <button type="button" role="tab" aria-selected={v.sel} onClick={v.go} style={css(v.style)}>
                      {v.label}
                    </button>
                  </Fragment>
                ))}
              </div>
            </div>
            <div style={css("display: flex; flex-wrap: wrap; gap: 12px; align-items: stretch;")}>
              <div style={css("flex: 2 1 520px; border: 1px solid #2a2a2f; border-radius: 12px; background: #1a1a1e; padding: 20px; min-width: 0;")}>
                <AetherScene dark={true} story="customer" stage={viewStage} controls={false} />
              </div>
              <div style={css("flex: 1 1 280px; display: flex; flex-direction: column; gap: 12px;")}>
                <div style={css("flex: 1; border: 1px solid #2a2a2f; border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 14px; background: #1a1a1e;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                    {viewTitle}
                  </span>
                  <span style={css("font-size: 18px; font-weight: 500; line-height: 1.35; color: #e8e6e1;")}>
                    {viewBody}
                  </span>
                  <div style={css("display: flex; flex-direction: column; gap: 6px; margin-top: auto;")}>
                    {(layers).map((l: any, lIndex: number) => (
                      <Fragment key={lIndex}>
                        <span style={css(l.style)}>
                          <span style={css("font-family: var(--font-mono);")}>
                            {l.g}
                          </span>
                          {l.t}
                        </span>
                      </Fragment>
                    ))}
                  </div>
                </div>
              </div>
            </div>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr)); gap: 12px;")}>
              <div style={css("border: 1px solid #2a2a2f; border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 12px;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {"What traditional software sees"}
                </span>
                <div style={css("display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 6px; font-family: var(--font-mono); font-size: 12px; text-align: center;")}>
                  <span style={css("color: #e8e6e1;")}>
                    {"CRM"}
                  </span>
                  <span style={css("color: #e8e6e1;")}>
                    {"Analytics"}
                  </span>
                  <span style={css("color: #e8e6e1;")}>
                    {"Payments"}
                  </span>
                  <span style={css("color: #e8e6e1;")}>
                    {"AI"}
                  </span>
                  <span style={css("color: #6b6a65;")}>
                    {"↓"}
                  </span>
                  <span style={css("color: #6b6a65;")}>
                    {"↓"}
                  </span>
                  <span style={css("color: #6b6a65;")}>
                    {"↓"}
                  </span>
                  <span style={css("color: #6b6a65;")}>
                    {"↓"}
                  </span>
                  <span style={css("padding: 6px 0; border: 1px solid #2a2a2f; border-radius: 6px; color: #a09f99;")}>
                    {"records"}
                  </span>
                  <span style={css("padding: 6px 0; border: 1px solid #2a2a2f; border-radius: 6px; color: #a09f99;")}>
                    {"events"}
                  </span>
                  <span style={css("padding: 6px 0; border: 1px solid #2a2a2f; border-radius: 6px; color: #a09f99;")}>
                    {"transactions"}
                  </span>
                  <span style={css("padding: 6px 0; border: 1px solid #2a2a2f; border-radius: 6px; color: #a09f99;")}>
                    {"actions"}
                  </span>
                </div>
                <span style={css("font-family: var(--font-mono); font-size: 11px; color: #e09a8f;")}>
                  {"■ unknown relationships"}
                </span>
              </div>
              <div style={css("border: 1px solid rgba(107,154,124,0.45); border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 12px; background: rgba(107,154,124,0.08);")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #9cc4a9;")}>
                  {"What Olympus technology sees"}
                </span>
                <div style={css("display: flex; flex-direction: column; align-items: center; gap: 4px; font-family: var(--font-mono); font-size: 12px;")}>
                  <span style={css("padding: 5px 10px; border-radius: 6px; background: #e8e6e1; color: #1a1a1e;")}>
                    {"● person"}
                  </span>
                  <span style={css("display: flex; gap: 6px; color: #a09f99;")}>
                    <span style={css("padding: 4px 8px; border: 1px solid #2a2a2f; border-radius: 6px;")}>
                      {"campaign"}
                    </span>
                    <span style={css("padding: 4px 8px; border: 1px solid #2a2a2f; border-radius: 6px;")}>
                      {"interaction"}
                    </span>
                    <span style={css("padding: 4px 8px; border: 1px solid #2a2a2f; border-radius: 6px; color: #dcb683;")}>
                      {"⬡ agent"}
                    </span>
                  </span>
                  <span style={css("color: #6b6a65;")}>
                    {"↓"}
                  </span>
                  <span style={css("display: flex; gap: 6px; color: #a09f99;")}>
                    <span style={css("padding: 4px 8px; border: 1px solid #2a2a2f; border-radius: 6px;")}>
                      {"purchase"}
                    </span>
                    <span style={css("color: #6b6a65;")}>
                      {"→"}
                    </span>
                    <span style={css("padding: 4px 8px; border: 1px solid rgba(107,154,124,0.5); border-radius: 6px; color: #9cc4a9;")}>
                      {"↑ value"}
                    </span>
                  </span>
                </div>
                <span style={css("font-family: var(--font-mono); font-size: 11px; color: #9cc4a9;")}>
                  {"● one connected model"}
                </span>
              </div>
            </div>
          </div>
        </section>
        <section id="approach" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: clamp(32px, 5vw, 72px); align-items: start;")}>
            <div style={css("display: flex; flex-direction: column; gap: 16px; position: sticky; top: 96px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #4f7a5e;")}>
                {"Approach"}
              </span>
              <h2 style={css("font-size: clamp(30px, 3.8vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
                {"Simple on the surface. Detailed when you need it."}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 420px;")}>
                {"The engineering underneath is serious. Using it shouldn’t feel that way. Start with the short answer, and go deeper only when you want to."}
              </p>
            </div>
            <div style={css("display: flex; flex-direction: column; gap: 0;")}>
              {(depths).map((d: any, dIndex: number) => (
                <Fragment key={dIndex}>
                  <div style={css(d.style)}>
                    <span style={css("display: flex; justify-content: space-between; gap: 8px; align-items: baseline;")}>
                      <span style={css("font-family: var(--font-mono); font-size: 12px; color: #6b6a65;")}>
                        {d.n}
                      </span>
                      <span style={css("font-family: var(--font-mono); font-size: 12px; color: #9c9b95;")}>
                        {d.time}
                      </span>
                    </span>
                    <span style={css("font-size: 20px; font-weight: 500; letter-spacing: -0.3px;")}>
                      {d.q}
                    </span>
                    <span style={css("font-size: 14px; line-height: 1.6; color: #4a4945;")}>
                      {d.a}
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section style={css("background: #eceae5;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 32px; align-items: center;")}>
            <div style={css("display: flex; flex-direction: column; gap: 16px;")}>
              <span style={css("display: inline-flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                <img src={markSrc('aether')} alt="" style={css("width: 16px; height: 16px;")} />
                {"The implementation"}
              </span>
              <h2 style={css("font-size: clamp(30px, 3.8vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
                {"Aether puts it into practice."}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 480px;")}>
                {"Aether is the product built on this technology: one live picture of what’s happening across all your tools."}
              </p>
            </div>
            <div style={css("display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-start;")}>
              <a href={link("Aether Home.dc.html")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {"Explore Aether"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Olympus Research.dc.html")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #f5f4f1; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-4d1362f5">
                {"Open research problems"}
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
