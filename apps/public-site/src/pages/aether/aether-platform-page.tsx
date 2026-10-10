/**
 * Built from design/designs/Aether Platform.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, hoverClass, portalLabel, useDesignState, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-platform-page.css';

type Feat = [g: string, name: string, q: string, plain: string, product: string, tech: string, color: string, stage: 'connect' | 'understand' | 'explore' | 'act', href: string, pos: [number, number] | null];
const EASE = 'cubic-bezier(0.22,1,0.36,1)';
const F: Record<string, Feat> = {
  connections: ['⚙', 'Connections', 'How does my world enter Aether?', 'Bring activity together from the systems you already use.', 'Connectors, SDKs, APIs, webhooks, and imports.', 'Canonical observation envelopes accepted at /v1/batch.', '#8fb0cc', 'connect', 'Aether Connect.dc.html', null],
  profiles: ['⬡', 'Profiles', 'Who is this?', 'Everything Aether knows about one person, agent, organization, or other entity.', 'The 360 view for a resolved entity.', 'A tenant-scoped resolved entity projection constructed from evidence and identity relationships.', '#9fbad6', 'understand', 'Aether Feature Page.dc.html?f=profiles', [1, 2]],
  graph: ['↔', 'Graph', 'What is related?', 'Connect entities and activity.', 'The Graph Workspace: every resolved entity and relationship, explorable.', 'Tenant-scoped graph projection of resolved entities and typed edges.', '#9fbad6', 'understand', 'Aether Feature Page.dc.html?f=graph', [3, 1]],
  signals: ['◉', 'Signals', 'What happened?', 'Something happened.', 'Observed events from every source.', 'Observations validated against the canonical event registry.', '#9cc4a9', 'understand', 'Docs.dc.html?page=signals', [1, 4]],
  journeys: ['→', 'Journeys', 'How did they get here?', 'See the path that led to an outcome.', 'Journeys and Journey 360.', 'Journey construction over ordered, temporally linked signals.', '#9cc4a9', 'understand', 'Aether Feature Page.dc.html?f=journeys', [3, 2]],
  lenses: ['◈', 'Lenses', 'What does this look like from another perspective?', 'Same graph. Different perspective.', 'Saved, combinable perspectives over the graph.', 'Projection and semantic merge over the tenant graph.', '#dcb683', 'explore', 'Aether Lenses.dc.html', [5, 5]],
  timeline: ['◷', 'Timeline', 'What changed over time?', 'Understand how something changed over time.', 'Timeline and history on every 360.', 'Temporal graph query.', '#a09f99', 'explore', 'Docs.dc.html?page=journeys', [1, 5]],
  agents: ['⬡', 'Agents', 'What did the agent do?', 'See which agents created or directed other agents.', 'Agents and Agent 360.', 'Agent lineage with delegated authority and tool-call evidence.', '#dcb683', 'act', 'Aether Agents.dc.html', [5, 2]],
  comms: ['✉', 'Communications', 'What communication occurred?', 'Communications aren’t another inbox — they are part of the relationship history.', 'Communications 360.', 'Communication events resolved to entities and journeys.', '#8fb0cc', 'act', 'Aether Feature Page.dc.html?f=communications', [3, 4]],
  value: ['↑', 'Value', 'What influenced this outcome?', 'Understand what contributed to an outcome.', 'Value and attribution.', 'Attribution credits over journey touchpoints.', '#9cc4a9', 'act', 'Aether Feature Page.dc.html?f=value', [5, 4]],
  risk: ['▲', 'Risk', 'Where is the risk?', 'How risk emerges from relationships.', 'Risk signals with confidence and source.', 'Inferred risk edges, kept separate from observed evidence.', '#e09a8f', 'act', 'Aether Feature Page.dc.html?f=risk', [3, 5]],
};
const SN = { connect: '01 · connect', understand: '02 · understand', explore: '03 · explore', act: '04 · act' };
const G: [id: string, n: string, name: string, title: string, body: string, items: string[], col: string][] = [
  ['connect', '01', 'Connect', 'Bring your tools together.', 'Applications, platforms, devices, agents, providers, and systems you already use.', ['connections'], '#3a6896'],
  ['understand', '02', 'Understand', 'Work out who’s who and what happened.', 'Aether identifies the people, agents, organizations, events, relationships, and value behind activity.', ['profiles', 'graph', 'signals', 'journeys'], '#4f7a5e'],
  ['explore', '03', 'Explore', 'Follow people, paths, and history.', 'Follow anything through a connected model instead of searching across separate tools.', ['lenses', 'timeline'], '#8a6433'],
  ['act', '04', 'Act', 'Use what you learn.', 'Investigate, decide, personalize, measure outcomes, or give agents reliable context.', ['agents', 'comms', 'value', 'risk'], '#a3473c'],
];
const LIGHT: Record<string, string> = { '#8fb0cc': '#5a85a8', '#9fbad6': '#3a6896', '#9cc4a9': '#4f7a5e', '#dcb683': '#8a6433', '#a09f99': '#6b6a65', '#e09a8f': '#a3473c' };

export function AetherPlatformPage() {
  const link = useLink();
  usePageMeta('aether-platform');
  const [state, setState] = useDesignState<{ sel: string }>({ sel: 'graph' });
  const k = state.sel;
  const c = F[k] ?? F.graph!;
  const map = Object.keys(F)
    .filter((id) => F[id]![9])
    .map((id) => {
      const [g, name, , , , , col, , , pos] = F[id]!;
      const on = id === k;
      const isG = id === 'graph';
      const p = pos ?? [1, 1];
      return {
        g, name, sel: on, go: () => setState({ sel: id }),
        gStyle: 'font-family: var(--font-mono); font-size: ' + (isG ? 18 : 14) + 'px; color: ' + (on ? '#1a1a1e' : col) + ';',
        style: 'font-family: inherit; grid-column: ' + p[0] + '; grid-row: ' + p[1] + '; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; min-height: ' + (isG ? 84 : 72) + 'px; padding: 10px 6px; border-radius: 10px; cursor: pointer; transition: background-color 120ms ' + EASE + ', border-color 120ms ' + EASE + ', color 120ms ' + EASE + '; ' + (on ? 'background: #e8e6e1; color: #1a1a1e; border: 1px solid #e8e6e1;' : 'background: ' + (isG ? '#1f1f24' : '#1a1a1e') + '; color: #e8e6e1; border: 1px solid ' + (isG ? '#4a4a52' : '#2a2a2f') + ';'),
        hover: on ? 'background: #e8e6e1;' : 'border-color: #6b6a65;',
      };
    });
  const sel = { g: c[0], name: c[1], q: c[2], plain: c[3], product: c[4], tech: c[5], stage: SN[c[7]], href: c[8], cta: 'Explore ' + c[1].toLowerCase() };
  const selChip = 'width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 18px; background: #e8e6e1; color: #1a1a1e;';
  const groups = G.map(([id, n, name, title, body, items, col], i) => ({
    id, n, name, title, body,
    bg: 'border-bottom: 1px solid #d8d6d0; background: ' + (i % 2 ? '#eceae5' : '#f5f4f1') + ';',
    kStyle: 'font-family: var(--font-mono); font-size: 12px; color: ' + col + ';',
    items: items.map((x) => {
      const f = F[x]!;
      return { g: f[0], name: f[1], q: f[2], plain: f[3], href: f[8], gStyle: 'font-family: var(--font-mono); font-size: 16px; color: ' + (LIGHT[f[6]] || col) + ';' };
    }),
  }));
  return (
    <div className="dc pg-aether-platform">
    <div data-page="aether-platform" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Platform" />
      <main id="main" tabIndex={-1}>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 9vw, 120px) 24px clamp(48px, 7vw, 80px); display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); gap: 32px; align-items: end;")}>
            <div style={css("display: flex; flex-direction: column; gap: 20px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #3a6896;")}>
                {"Platform"}
              </span>
              <h1 style={css("font-size: clamp(44px, 6.4vw, 84px); font-weight: 500; line-height: 0.96; letter-spacing: -0.045em; margin: 0; text-wrap: balance;")}>
                {"One picture. Many ways to look at it."}
              </h1>
            </div>
            <div style={css("display: flex; flex-direction: column; gap: 20px; padding-bottom: 8px;")}>
              <p style={css("font-size: 17px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 500px;")}>
                {"Every part of Aether looks at the same connected picture of your business — so the answers line up, wherever you start."}
              </p>
              <div style={css("display: flex; flex-wrap: wrap; gap: 8px;")}>
                <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 42px; padding: 0 18px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                  {portalLabel("Get started")}
                  <span style={css("font-family: var(--font-mono);")}>
                    {"→"}
                  </span>
                </a>
                <a href={link("Aether How It Works.dc.html")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 42px; padding: 0 18px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-4d1362f5">
                  {"How it works"}
                </a>
              </div>
            </div>
          </div>
        </section>
        <section id="map" data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: flex; flex-wrap: wrap; gap: 24px; align-items: stretch;")}>
            <div style={css("flex: 3 1 560px; min-width: 0; position: relative; border: 1px dashed #3a3a40; border-radius: 16px; padding: 44px 20px 20px; box-sizing: border-box;")}>
              <span style={css("position: absolute; top: 14px; left: 20px; font-family: var(--font-mono); font-size: 11px; color: #dcb683;")}>
                {"◈ lenses surround the model · geography · value · risk · temporal"}
              </span>
              <div style={css("display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); grid-template-rows: repeat(5, auto); gap: 10px;")}>
                {(map).map((m: any, mIndex: number) => (
                  <Fragment key={mIndex}>
                    <button type="button" onClick={m.go} aria-pressed={m.sel} style={css(m.style)} className={`${hoverClass(m.hover, 'hover')}`}>
                      <span style={css(m.gStyle)}>
                        {m.g}
                      </span>
                      <span style={css("font-size: 13px; font-weight: 500;")}>
                        {m.name}
                      </span>
                    </button>
                  </Fragment>
                ))}
                <div style={css("grid-column: 2 / 5; grid-row: 3; display: flex; align-items: center; justify-content: center; gap: 10px; padding: 10px; border-top: 1px solid #3a3a40; border-bottom: 1px solid #3a3a40; font-family: var(--font-mono); font-size: 12px; color: #a09f99;")}>
                  {"↔ relationships"}
                </div>
              </div>
            </div>
            <div style={css("flex: 2 1 340px; min-width: 0; border: 1px solid #2a2a2f; border-radius: 16px; background: #1a1a1e; padding: 24px; display: flex; flex-direction: column; gap: 16px; box-sizing: border-box;")}>
              <div style={css("display: flex; justify-content: space-between; align-items: center;")}>
                <span style={css(selChip)}>
                  {sel.g}
                </span>
                <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                  {sel.stage}
                </span>
              </div>
              <span style={css("font-size: 13px; color: #a09f99;")}>
                {sel.name}{" answers"}
              </span>
              <span style={css("font-size: clamp(24px, 2.4vw, 30px); font-weight: 500; letter-spacing: -0.02em; line-height: 1.15; color: #e8e6e1; margin-top: -8px;")}>
                {sel.q}
              </span>
              <div style={css("display: flex; flex-direction: column; gap: 0; border-top: 1px solid #2a2a2f; margin-top: auto;")}>
                <div style={css("display: grid; grid-template-columns: 92px minmax(0,1fr); gap: 12px; padding: 12px 0; border-bottom: 1px solid #2a2a2f;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                    {"Plain"}
                  </span>
                  <span style={css("font-size: 14px; line-height: 1.5; color: #e8e6e1;")}>
                    {sel.plain}
                  </span>
                </div>
                <div style={css("display: grid; grid-template-columns: 92px minmax(0,1fr); gap: 12px; padding: 12px 0; border-bottom: 1px solid #2a2a2f;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                    {"Product"}
                  </span>
                  <span style={css("font-size: 14px; line-height: 1.5; color: #a09f99;")}>
                    {sel.product}
                  </span>
                </div>
                <div style={css("display: grid; grid-template-columns: 92px minmax(0,1fr); gap: 12px; padding: 12px 0;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                    {"Technical"}
                  </span>
                  <span style={css("font-family: var(--font-mono); font-size: 12px; line-height: 1.6; color: #a09f99;")}>
                    {sel.tech}
                  </span>
                </div>
              </div>
              <a href={link(sel.href)} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #e8e6e1; text-decoration: none;")} className="hv-6f6d4759">
                {sel.cta}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
            </div>
          </div>
        </section>
        {(groups).map((gp: any, gpIndex: number) => (
          <Fragment key={gpIndex}>
            <section id={gp.id} style={css(gp.bg)}>
              <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: flex; flex-wrap: wrap; gap: clamp(24px, 4vw, 56px); align-items: flex-start;")}>
                <div style={css("flex: 1 1 300px; display: flex; flex-direction: column; gap: 12px;")}>
                  <span style={css(gp.kStyle)}>
                    {gp.n}{" · "}{gp.name}
                  </span>
                  <h2 style={css("font-size: clamp(28px, 3.4vw, 42px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0; text-wrap: balance;")}>
                    {gp.title}
                  </h2>
                  <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 420px;")}>
                    {gp.body}
                  </p>
                </div>
                <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 10px; flex: 2 1 520px; min-width: 0;")}>
                  {(gp.items).map((it: any, itIndex: number) => (
                    <Fragment key={itIndex}>
                      <a href={link(it.href)} style={css("display: flex; flex-direction: column; gap: 8px; min-height: 170px; padding: 20px; border-radius: 12px; background: #fbfaf8; border: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e; box-sizing: border-box; transition: border-color 120ms cubic-bezier(0.22,1,0.36,1), background-color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-356a9228">
                        <span style={css("display: flex; justify-content: space-between; align-items: center;")}>
                          <span style={css(it.gStyle)}>
                            {it.g}
                          </span>
                          <span style={css("font-family: var(--font-mono); font-size: 12px; color: #9c9b95;")}>
                            {"→"}
                          </span>
                        </span>
                        <span style={css("font-size: 17px; font-weight: 500; margin-top: auto;")}>
                          {it.name}
                        </span>
                        <span style={css("font-size: 13px; font-weight: 500; color: #4a4945;")}>
                          {it.q}
                        </span>
                        <span style={css("font-size: 13px; line-height: 1.5; color: #6b6a65;")}>
                          {it.plain}
                        </span>
                      </a>
                    </Fragment>
                  ))}
                </div>
              </div>
            </section>
          </Fragment>
        ))}
        <section data-theme="dark" style={css("background: #1a1a1e; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: flex; flex-direction: column; gap: 20px; align-items: flex-start;")}>
            <h2 style={css("font-size: clamp(30px, 4.2vw, 52px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.04; margin: 0; max-width: 760px; color: #e8e6e1; text-wrap: balance;")}>
              {"Connect one tool. See the puzzle pieces come together."}
            </h2>
            <div style={css("display: flex; flex-wrap: wrap; gap: 8px;")}>
              <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #e8e6e1; color: #1a1a1e;")} className="hv-eed11080">
                {portalLabel("Get started")}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Contact.dc.html?brand=aether&type=pilot")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: transparent; color: #e8e6e1; border: 1px solid #3a3a40;")} className="hv-51ea9421">
                {"Request a pilot"}
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
