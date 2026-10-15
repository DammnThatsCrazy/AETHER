/**
 * Built from design/designs/Glossary.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useDesignState, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './glossary-page.css';

import type { ChangeEvent } from 'react';

const EASE = 'cubic-bezier(0.22,1,0.36,1)';
type Layer = 'understand' | 'connect' | 'explore' | 'act';
/** Each Aether term in plain, product, and technical language. */
export const GLOSSARY: [id: string, g: string, term: string, layer: Layer, plain: string, product: string, tech: string, c: string][] = [
  ['signal', '◉', 'Signal', 'understand', 'Something happened.', 'An observed event from any connected source — page viewed, order completed, agent invoked a tool.', 'An observation validated against the canonical event registry and accepted at /v1/batch.', '#4f7a5e'],
  ['source', '○', 'Source', 'connect', 'Where something happened.', 'The application, platform, device, provider, or agent a signal came from.', 'The origin metadata attached to every canonical observation envelope.', '#5a85a8'],
  ['connection', '⚙', 'Connection', 'connect', 'How a system is linked to Aether.', 'A connector, SDK, API, webhook, or import that brings activity in.', 'A managed connector or ingestion path with authorization, sync lifecycle, cursor state, and normalization.', '#5a85a8'],
  ['entity', '⬡', 'Entity', 'understand', 'A person, agent, organization, system, or device.', 'Anything Aether can resolve and build a Profile for.', 'A typed node in the tenant-scoped graph, resolved from identity evidence.', '#3a6896'],
  ['profile', '⬡', 'Profile', 'understand', 'Everything Aether knows about one person, agent, organization, or other entity.', 'The 360 view for a resolved entity.', 'A tenant-scoped resolved entity projection constructed from evidence and identity relationships.', '#3a6896'],
  ['relationship', '↔', 'Relationship', 'understand', 'How two things are connected.', 'An edge in the Graph — observed or inferred — with its evidence.', 'A typed, temporal graph edge produced by resolution and projected from the graph outbox.', '#3a6896'],
  ['journey', '→', 'Journey', 'explore', 'The path that led to an outcome.', 'An ordered sequence of touchpoints in Journeys and Journey 360.', 'Journey construction over temporally ordered, linked signals; supports pause, resume, branch, and re-entry.', '#4f7a5e'],
  ['lens', '◈', 'Lens', 'explore', 'A perspective on the same information.', 'A saved, combinable view that foregrounds identity, value, risk, geography, time, or agents.', 'A projection with semantic merge over the tenant graph; does not copy data.', '#8a6433'],
  ['syndicate', '◈', 'Syndicate', 'explore', 'A group that acts together.', 'A relationship cluster across people, agents, and organizations.', 'A detected subgraph community with shared edges; currently direction, not a released capability.', '#7d6538'],
  ['agent', '⬡', 'Agent', 'act', 'Software acting on someone’s behalf.', 'An actor in Agents and Agent 360, with lineage and authority.', 'An entity with lifecycle, parent/child lineage, delegated authority, and tool-call evidence.', '#a8783e'],
  ['value', '↑', 'Value', 'act', 'What an outcome was worth, and what contributed to it.', 'Revenue and economic activity linked to relationships, with attribution.', 'Attribution credits over journey touchpoints, joined to normalized financial events.', '#4f7a5e'],
  ['evidence', '✓', 'Evidence', 'act', 'Why Aether believes what it believes.', 'The observed, inferred, resolved, authorized, executed, verified, or measured state of a claim.', 'Evidence-state metadata on every edge and projection; inference is never stored as observation.', '#4f7a5e'],
  ['outcome', '●', 'Outcome', 'act', 'What resulted.', 'The measured end of a journey, agent action, or campaign.', 'A terminal event or measured state linked back through journey and attribution edges.', '#a3473c'],
];
const LN: Record<Layer, string> = { understand: '02 · understand', connect: '01 · connect', explore: '03 · explore', act: '04 · act' };
const DP = [['all', 'All three'], ['plain', 'Plain'], ['product', 'Product'], ['tech', 'Technical']];
const MAP = [['Observation', 'Signal / event', 'Something happened'], ['Identity stitching', 'Profile resolution', 'Recognize the same entity across systems'], ['Graph projection', 'Graph', 'Connect entities and activity'], ['Canonical contract', 'Event / schema contract', 'Give different systems a common language'], ['Temporal graph query', 'Timeline / history', 'Understand how something changed over time'], ['Attribution credits', 'Value', 'Understand what contributed to an outcome'], ['Agent lineage', 'Agent relationships', 'See which agents created or directed other agents'], ['Journey construction', 'Journeys', 'See the path that led to an outcome']].map(([i, p, e]) => ({ i, p, e }));

export function GlossaryPage() {
  const link = useLink();
  usePageMeta('glossary');
  const [state, setState] = useDesignState({ q: '', depth: 'all' });
  const query = state.q.trim().toLowerCase();
  const dp = state.depth;
  const list = GLOSSARY.filter((t) => !query || (t[2] + ' ' + t[4] + ' ' + t[5] + ' ' + t[6]).toLowerCase().includes(query));
  const q = state.q;
  const onQ = (e: ChangeEvent<HTMLInputElement>) => setState({ q: e.target.value });
  const empty = list.length === 0;
  const depths = DP.map(([k, l]) => {
    const on = k === dp;
    return { l, sel: on ? 'true' : 'false', go: () => setState({ depth: k! }), style: 'font-family: inherit; min-height: 32px; padding: 0 12px; border-radius: 6px; border: 0; cursor: pointer; font-size: 13px; font-weight: 500; transition: background-color 120ms ' + EASE + '; ' + (on ? 'background: #1a1a1e; color: #f5f4f1;' : 'background: transparent; color: #6b6a65;') };
  });
  const terms = list.map(([id, g, term, layer, plain, product, tech, c]) => ({ id, g, term, plain, product, tech, layer: LN[layer], gStyle: 'font-family: var(--font-mono); font-size: 16px; color: ' + c + ';', showPlain: dp === 'all' || dp === 'plain', showProduct: dp === 'all' || dp === 'product', showTech: dp === 'all' || dp === 'tech' }));
  const map = MAP;
  return (
    <div className="dc pg-glossary">
    <div data-page="glossary" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Developers" />
      <main id="main" tabIndex={-1}>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(48px, 8vw, 104px) 24px clamp(32px, 5vw, 56px); display: flex; flex-direction: column; gap: 20px;")}>
            <span style={css("display: flex; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              <a href={link("Docs.dc.html")} style={css("color: #6b6a65; text-decoration: none;")}>
                {"Docs"}
              </a>
              <span>
                {"/"}
              </span>
              <span style={css("color: #8a6433;")}>
                {"Glossary"}
              </span>
            </span>
            <h1 style={css("font-size: clamp(40px, 6vw, 72px); font-weight: 500; line-height: 0.98; letter-spacing: -0.042em; margin: 0; text-wrap: balance;")}>
              {"What the words mean."}
            </h1>
            <p style={css("font-size: 16px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 640px;")}>
              {"Every term explained three ways: in plain English, as it appears in Aether, and in technical detail for developers. Pick the one you need."}
            </p>
            <div style={css("display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 8px;")}>
              <input value={q} onChange={onQ} aria-label="Filter terms" placeholder="Filter terms…" style={css("font-family: inherit; font-size: 14px; height: 40px; padding: 0 12px; border-radius: 6px; border: 1px solid #d8d6d0; background: #fbfaf8; color: #1a1a1e; outline: none; flex: 0 1 280px; min-width: 0;")} />
              <div role="radiogroup" aria-label="Depth" style={css("display: flex; gap: 4px; padding: 3px; border-radius: 8px; background: #eceae5; border: 1px solid #d8d6d0;")}>
                {(depths).map((d: any, dIndex: number) => (
                  <Fragment key={dIndex}>
                    <button type="button" role="radio" aria-checked={d.sel} onClick={d.go} style={css(d.style)}>
                      {d.l}
                    </button>
                  </Fragment>
                ))}
              </div>
            </div>
          </div>
        </section>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: 32px 24px clamp(48px, 7vw, 88px); display: flex; flex-direction: column; gap: 10px;")}>
            {(terms).map((t: any, tIndex: number) => (
              <Fragment key={tIndex}>
                <article id={t.id} style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 0; border: 1px solid #d8d6d0; border-radius: 12px; overflow: hidden; background: #fbfaf8;")}>
                  <div style={css("display: flex; flex-direction: column; gap: 6px; padding: 20px; background: #eceae5; border-right: 1px solid #d8d6d0;")}>
                    <span style={css(t.gStyle)}>
                      {t.g}
                    </span>
                    <h2 style={css("font-size: 22px; font-weight: 500; letter-spacing: -0.33px; margin: 0;")}>
                      {t.term}
                    </h2>
                    <span style={css("font-family: var(--font-mono); font-size: 11px; color: #6b6a65;")}>
                      {t.layer}
                    </span>
                  </div>
                  {(t.showPlain) ? (
                    <>
                      <div style={css("display: flex; flex-direction: column; gap: 6px; padding: 20px; border-right: 1px solid #e2e0da;")}>
                        <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #4f7a5e;")}>
                          {"Plain language"}
                        </span>
                        <span style={css("font-size: 15px; line-height: 1.55;")}>
                          {t.plain}
                        </span>
                      </div>
                    </>
                  ) : null}
                  {(t.showProduct) ? (
                    <>
                      <div style={css("display: flex; flex-direction: column; gap: 6px; padding: 20px; border-right: 1px solid #e2e0da;")}>
                        <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #3a6896;")}>
                          {"Product meaning"}
                        </span>
                        <span style={css("font-size: 14px; line-height: 1.55; color: #4a4945;")}>
                          {t.product}
                        </span>
                      </div>
                    </>
                  ) : null}
                  {(t.showTech) ? (
                    <>
                      <div style={css("display: flex; flex-direction: column; gap: 6px; padding: 20px; background: #1a1a1e;")}>
                        <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #dcb683;")}>
                          {"Technical meaning"}
                        </span>
                        <span style={css("font-family: var(--font-mono); font-size: 12px; line-height: 1.65; color: #e8e6e1;")}>
                          {t.tech}
                        </span>
                      </div>
                    </>
                  ) : null}
                </article>
              </Fragment>
            ))}
            {(empty) ? (
              <>
                <div style={css("padding: 24px; border: 1px dashed #c9c7c0; border-radius: 12px; font-size: 14px; color: #6b6a65;")}>
                  {"No term matches “"}{q}{"”."}
                </div>
              </>
            ) : null}
          </div>
        </section>
        <section style={css("background: #eceae5; border-top: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(48px, 7vw, 88px) 24px; display: flex; flex-direction: column; gap: 20px;")}>
            <div style={css("display: flex; flex-direction: column; gap: 10px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                {"Internal to public"}
              </span>
              <h2 style={css("font-size: clamp(26px, 3vw, 36px); font-weight: 500; letter-spacing: -0.026em; margin: 0;")}>
                {"Engineering terms, translated."}
              </h2>
            </div>
            <div style={css("border: 1px solid #d8d6d0; border-radius: 10px; overflow-x: auto; background: #fbfaf8;")}>
              <table style={css("width: 100%; border-collapse: collapse; font-size: 13px; min-width: 640px;")}>
                <thead>
                  <tr style={css("background: #f5f4f1;")}>
                    <th style={css("text-align: left; padding: 10px 14px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                      {"Internal"}
                    </th>
                    <th style={css("text-align: left; padding: 10px 14px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                      {"Product"}
                    </th>
                    <th style={css("text-align: left; padding: 10px 14px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                      {"Public explanation"}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(map).map((m: any, mIndex: number) => (
                    <Fragment key={mIndex}>
                      <tr style={css("border-top: 1px solid #e2e0da;")}>
                        <td style={css("padding: 10px 14px; font-family: var(--font-mono); font-size: 12px; color: #4a4945;")}>
                          {m.i}
                        </td>
                        <td style={css("padding: 10px 14px; font-weight: 500;")}>
                          {m.p}
                        </td>
                        <td style={css("padding: 10px 14px; color: #4a4945;")}>
                          {m.e}
                        </td>
                      </tr>
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
