/**
 * Built from design/designs/Aether Lenses.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, portalLabel, useDesignState, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-lenses-page.css';

import { createElement as h, type ReactNode } from 'react';

type LKind = 'human' | 'org' | 'system' | 'agent' | 'value';
type LNode = [id: string, label: string, kind: LKind, graph: [number, number], geo: [number, number], time: number, region: string];
type Lens = [key: string, g: string, label: string, color: string, set: string[] | 'ALL' | null, title: string, body: string];
const EASE = 'cubic-bezier(0.22,1,0.36,1)';
const KC: Record<LKind, string> = { human: '#9fbad6', org: '#c9b088', system: '#8fb0cc', agent: '#dcb683', value: '#9cc4a9' };
const N: LNode[] = [
  ['jane', 'Jane Smith', 'human', [360, 222], [180, 230], 2, 'nyc'],
  ['acme', 'Acme Co.', 'org', [360, 70], [110, 140], 1, 'nyc'],
  ['web', 'anon_941', 'system', [210, 120], [250, 140], 1, 'nyc'],
  ['app', 'iOS app', 'system', [510, 120], [500, 140], 2, 'ldn'],
  ['email', 'Email', 'system', [190, 310], [100, 320], 3, 'nyc'],
  ['camp', 'Spring campaign', 'org', [80, 200], [70, 230], 0, 'nyc'],
  ['agent', 'Support agent', 'agent', [540, 320], [520, 300], 4, 'ldn'],
  ['orch', 'Orchestrator', 'agent', [660, 250], [640, 260], 4, 'ldn'],
  ['order', 'Order #5532', 'value', [360, 362], [200, 360], 5, 'nyc'],
  ['pay', '$149 payment', 'value', [230, 410], [300, 330], 5, 'nyc'],
  ['refund', '$42 refund', 'value', [510, 412], [600, 370], 6, 'ldn'],
  ['device', 'Shared device', 'system', [630, 170], [610, 180], 3, 'ldn'],
  ['acct2', 'Account B', 'human', [660, 80], [650, 100], 6, 'ldn'],
];
const E: [string, string, number?][] = [['jane', 'web'], ['jane', 'app'], ['jane', 'email'], ['camp', 'web', 1], ['camp', 'email'], ['jane', 'agent'], ['agent', 'orch'], ['jane', 'order'], ['order', 'pay'], ['agent', 'refund'], ['jane', 'acme'], ['app', 'device'], ['device', 'acct2'], ['acct2', 'refund', 1], ['camp', 'order', 1]];
const LENSES: Lens[] = [
  ['default', '○', 'Default', '#a09f99', null, 'Everything equal.', 'Every entity and relationship Aether knows, with nothing foregrounded.'],
  ['identity', '⬡', 'Identity', '#9fbad6', ['jane', 'web', 'app', 'acme', 'device', 'email'], 'Who is this?', 'Identifiers and the evidence that resolves them into one entity come forward.'],
  ['journey', '→', 'Journey', '#dcb683', ['camp', 'web', 'app', 'email', 'agent', 'order', 'jane'], 'How did they get here?', 'The ordered path of touchpoints toward the outcome comes forward.'],
  ['attribution', '◈', 'Attribution', '#c9b088', ['camp', 'web', 'email', 'agent', 'order', 'jane'], 'What influenced this outcome?', 'Touchpoints that received credit for the order come forward, with the inferred ones dashed.'],
  ['value', '↑', 'Value', '#9cc4a9', ['order', 'pay', 'refund', 'jane', 'camp'], 'What value resulted?', 'Revenue nodes brighten. Low-value edges recede.'],
  ['risk', '▲', 'Risk', '#e09a8f', ['device', 'acct2', 'refund', 'app', 'jane'], 'Where is the risk?', 'Risk relationships become foregrounded — a shared device links Jane to Account B and a refund.'],
  ['agent', '⬡', 'Agent', '#dcb683', ['agent', 'orch', 'refund', 'jane'], 'What did the agent do?', 'Agents, what they acted on, and for whom.'],
  ['geography', '◉', 'Geography', '#8fb0cc', 'ALL', 'Where did it happen?', 'Nodes reorganize geographically into the regions where activity occurred.'],
  ['temporal', '◷', 'Temporal', '#a09f99', 'ALL', 'What changed over time?', 'Nodes reorganize along time, earliest on the left.'],
];
const LM: Record<string, Lens> = Object.fromEntries(LENSES.map((l) => [l[0], l]));
const TIME_ROW: Record<LKind, number> = { org: 70, human: 150, system: 230, agent: 310, value: 390 };

export function AetherLensesPage() {
  const link = useLink();
  usePageMeta('aether-lenses');
  const [state, setState] = useDesignState<{ on: string[] }>({ on: [] });
  const on = state.on;
  const sets = on.map((k) => LM[k]![4]).filter((s): s is string[] => Array.isArray(s));
  const union = new Set<string>();
  sets.forEach((s) => s.forEach((x) => union.add(x)));
  const filtering = sets.length > 0;
  const layoutKey = [...on].reverse().find((k) => k === 'geography' || k === 'temporal') || 'graph';
  const lensColor = on.length ? LM[on[on.length - 1]!]![3] : '#a09f99';
  const pos = (n: LNode): [number, number] => (layoutKey === 'geography' ? n[4] : layoutKey === 'temporal' ? [70 + n[5] * 100, TIME_ROW[n[2]]] : n[3]);
  const byId: Record<string, LNode> = Object.fromEntries(N.map((n) => [n[0], n]));
  const isOn = (id: string) => !filtering || union.has(id);
  const edges = E.map(([a, b, dashed], i) => {
    const A = pos(byId[a]!);
    const B = pos(byId[b]!);
    const hi = filtering && union.has(a) && union.has(b);
    const dim = filtering && !hi;
    return h('line', { key: 'e' + i, x1: A[0], y1: A[1], x2: B[0], y2: B[1], stroke: hi ? lensColor : '#4a4a52', strokeWidth: hi ? 1.8 : 1, strokeDasharray: dashed ? '4 4' : undefined, opacity: dim ? 0.12 : 1, style: { transition: 'opacity 200ms ' + EASE + ', stroke 200ms ' + EASE } });
  });
  const nodes = N.map(([id, label, kind], i) => {
    const [x, y] = pos(byId[id]!);
    const lit = isOn(id);
    const center = id === 'jane';
    const r = center ? 13 : 8;
    return h(
      'g',
      { key: id, style: { transform: 'translate(' + x + 'px,' + y + 'px)', opacity: lit ? 1 : 0.18, transition: 'transform 320ms ' + EASE + ' ' + i * 14 + 'ms, opacity 200ms ' + EASE } },
      filtering && lit ? h('circle', { r: r + 6, fill: 'none', stroke: lensColor, strokeWidth: 1, opacity: 0.7 }) : null,
      h('circle', { r, fill: center ? '#e8e6e1' : '#1a1a1e', stroke: KC[kind], strokeWidth: center ? 0 : 2 }),
      h('text', { y: r + 16, textAnchor: 'middle', fill: lit ? '#e8e6e1' : '#a09f99', style: { fontFamily: 'var(--font-sans)', fontSize: 11, fontWeight: center ? 500 : 400 } }, label),
    );
  });
  let deco: ReactNode = null;
  if (layoutKey === 'geography')
    deco = h(
      'g',
      { key: 'geo', style: { animation: 'lnFade 320ms ' + EASE + ' both' } },
      h('rect', { x: 30, y: 90, width: 320, height: 320, rx: 12, fill: 'none', stroke: '#2a2a2f', strokeDasharray: '3 5' }),
      h('rect', { x: 440, y: 60, width: 260, height: 350, rx: 12, fill: 'none', stroke: '#2a2a2f', strokeDasharray: '3 5' }),
      h('text', { x: 46, y: 112, fill: '#8fb0cc', style: { fontFamily: 'var(--font-mono)', fontSize: 11 } }, '◉ new york'),
      h('text', { x: 456, y: 82, fill: '#8fb0cc', style: { fontFamily: 'var(--font-mono)', fontSize: 11 } }, '◉ london'),
    );
  if (layoutKey === 'temporal')
    deco = h(
      'g',
      { key: 'tmp', style: { animation: 'lnFade 320ms ' + EASE + ' both' } },
      h('line', { x1: 40, y1: 432, x2: 700, y2: 432, stroke: '#2a2a2f' }),
      ['Mar 02', 'Mar 04', 'Mar 06', 'Mar 08', 'Mar 09', 'Mar 10', 'Mar 11'].map((t, i) => h('text', { key: t, x: 70 + i * 100, y: 446, textAnchor: 'middle', fill: '#6b6a65', style: { fontFamily: 'var(--font-mono)', fontSize: 10 } }, t)),
    );
  const graph = h(
    'svg',
    { viewBox: '0 0 720 450', width: '100%', height: '100%', role: 'img', 'aria-label': 'Graph with ' + (on.length ? on.join(' and ') : 'no') + ' lens applied', style: { position: 'absolute', inset: 0, display: 'block', overflow: 'visible' } },
    deco,
    h('g', { key: 'E' }, edges),
    h('g', { key: 'N' }, nodes),
  );
  const toggle = (k: string) =>
    setState((s) => {
      if (k === 'default') return { on: [] };
      const has = s.on.includes(k);
      return { on: has ? s.on.filter((x) => x !== k) : [...s.on, k] };
    });
  const active = on.length ? LM[on[on.length - 1]!]! : LM.default!;
  const merged = on.length > 1;
  const lensBtns = LENSES.map(([k, g, label, c]) => {
    const sel = k === 'default' ? on.length === 0 : on.includes(k);
    return {
      g, label, sel, go: () => toggle(k),
      gStyle: 'font-family: var(--font-mono); color: ' + (sel ? '#1a1a1e' : c) + ';',
      style: 'font-family: inherit; display: inline-flex; align-items: center; gap: 7px; min-height: 36px; padding: 0 13px; border-radius: 999px; cursor: pointer; font-size: 13px; font-weight: 500; transition: background-color 120ms ' + EASE + ', border-color 120ms ' + EASE + ', color 120ms ' + EASE + '; ' + (sel ? 'background: ' + (k === 'default' ? '#e8e6e1' : c) + '; color: #1a1a1e; border: 1px solid transparent;' : 'background: #1a1a1e; color: #e8e6e1; border: 1px solid #2a2a2f;'),
    };
  });
  const panelKicker = merged ? 'Combined lens' : on.length ? active[2] + ' lens' : 'No lens applied';
  const panelTitle = merged ? on.map((k) => LM[k]![2]).join(' + ') : active[5];
  const panelBody = merged ? 'Semantic merge combines perspectives: everything foregrounded by any applied lens comes forward, laid out by the most recent spatial lens.' : active[6];
  const mergeName = on.map((k) => LM[k]![2].toLowerCase()).join(' + ');
  const countOn = filtering ? union.size : N.length;
  const countAll = N.length;
  const layoutName = ({ graph: 'relationships', geography: 'geographic', temporal: 'temporal' } as Record<string, string>)[layoutKey];
  const ops = [['Apply a lens', 'Foreground one perspective'], ['Remove a lens', 'Return to the full graph'], ['Combine lenses', 'Semantic merge'], ['Save a lens', 'Reuse the perspective'], ['Lens scope', 'What a lens can see'], ['Examples', 'Common perspectives']].map(([t, b]) => ({ t, b }));
  return (
    <div className="dc pg-aether-lenses">
    <div data-page="aether-lenses" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Platform" />
      <main id="main" tabIndex={-1}>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 9vw, 120px) 24px clamp(40px, 6vw, 72px); display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); gap: 32px; align-items: end;")}>
            <div style={css("display: flex; flex-direction: column; gap: 20px;")}>
              <span style={css("display: flex; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                <a href={link("Aether Platform.dc.html")} style={css("color: #6b6a65; text-decoration: none;")}>
                  {"Platform"}
                </a>
                <span>
                  {"/"}
                </span>
                <span style={css("color: #8a6433;")}>
                  {"Lenses"}
                </span>
              </span>
              <h1 style={css("font-size: clamp(44px, 6.4vw, 84px); font-weight: 500; line-height: 0.96; letter-spacing: -0.045em; margin: 0; text-wrap: balance;")}>
                {"Same data. Different perspective."}
              </h1>
            </div>
            <p style={css("font-size: 17px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 500px; padding-bottom: 8px;")}>
              {"A lens highlights what matters for one question — money, risk, location, time — and fades the rest. Use one, combine a few, and save the view."}
            </p>
          </div>
        </section>
        <section id="explorer" data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(40px, 6vw, 72px) 24px clamp(56px, 8vw, 96px); display: flex; flex-direction: column; gap: 16px;")}>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px;")}>
              <div role="group" aria-label="Lenses" style={css("display: flex; flex-wrap: wrap; gap: 6px;")}>
                {(lensBtns).map((b: any, bIndex: number) => (
                  <Fragment key={bIndex}>
                    <button type="button" aria-pressed={b.sel} onClick={b.go} style={css(b.style)}>
                      <span style={css(b.gStyle)}>
                        {b.g}
                      </span>
                      {b.label}
                    </button>
                  </Fragment>
                ))}
              </div>
              <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                {"select several to combine · synthetic tenant"}
              </span>
            </div>
            <div style={css("display: flex; flex-wrap: wrap; gap: 12px; align-items: stretch;")}>
              <div style={css("flex: 2.2 1 560px; min-width: 0; border: 1px solid #2a2a2f; border-radius: 12px; background: #1a1a1e; padding: 12px; box-sizing: border-box;")}>
                <div style={css("position: relative; width: 100%; aspect-ratio: 720 / 450;")}>
                  {graph}
                </div>
              </div>
              <div style={css("flex: 1 1 280px; min-width: 0; border: 1px solid #2a2a2f; border-radius: 12px; background: #1a1a1e; padding: 22px; display: flex; flex-direction: column; gap: 14px; box-sizing: border-box;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {panelKicker}
                </span>
                <span style={css("font-size: 24px; font-weight: 500; letter-spacing: -0.02em; line-height: 1.2; color: #e8e6e1;")}>
                  {panelTitle}
                </span>
                <span style={css("font-size: 14px; line-height: 1.6; color: #a09f99;")}>
                  {panelBody}
                </span>
                <div style={css("display: flex; flex-direction: column; gap: 6px; margin-top: auto; padding-top: 14px; border-top: 1px solid #2a2a2f;")}>
                  <span style={css("display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 12px; color: #a09f99;")}>
                    <span>
                      {"foregrounded"}
                    </span>
                    <span style={css("color: #e8e6e1;")}>
                      {countOn}{" of "}{countAll}{" entities"}
                    </span>
                  </span>
                  <span style={css("display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 12px; color: #a09f99;")}>
                    <span>
                      {"layout"}
                    </span>
                    <span style={css("color: #e8e6e1;")}>
                      {layoutName}
                    </span>
                  </span>
                  {(merged) ? (
                    <>
                      <span style={css("font-family: var(--font-mono); font-size: 12px; color: #dcb683; padding: 8px 10px; border: 1px solid rgba(220,182,131,0.35); border-radius: 6px; margin-top: 6px;")}>
                        {"◈ semantic merge · "}{mergeName}
                      </span>
                    </>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        </section>
        <section id="what" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 104px) 24px; display: flex; flex-wrap: wrap; gap: clamp(24px, 4vw, 56px); align-items: flex-start;")}>
            <div style={css("flex: 1 1 320px; display: flex; flex-direction: column; gap: 14px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #8a6433;")}>
                {"What is a Lens?"}
              </span>
              <h2 style={css("font-size: clamp(28px, 3.4vw, 44px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0; text-wrap: balance;")}>
                {"A perspective, not another dashboard."}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"Nothing is copied or rebuilt. Your data stays the same; the lens just changes what stands out."}
              </p>
            </div>
            <div style={css("flex: 2 1 560px; display: flex; flex-wrap: wrap; gap: 10px; min-width: 0;")}>
              <div style={css("flex: 1 1 240px; display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 24px; border-radius: 12px; background: #fbfaf8; border: 1px solid #d8d6d0; font-family: var(--font-mono); font-size: 12px; text-align: center;")}>
                <span style={css("padding: 10px 14px; border: 1px solid #d8d6d0; border-radius: 6px; width: 100%; box-sizing: border-box;")}>
                  <span style={css("font-family: var(--font-sans); font-size: 14px; font-weight: 500;")}>
                    {"The graph"}
                  </span>
                  <br />
                  <span style={css("color: #6b6a65;")}>
                    {"everything Aether knows"}
                  </span>
                </span>
                <span style={css("color: #9c9b95;")}>
                  {"↓ apply"}
                </span>
                <span style={css("padding: 8px 14px; border-radius: 6px; background: #4f7a5e; color: #f5f4f1;")}>
                  {"◈ value lens"}
                </span>
                <span style={css("color: #9c9b95;")}>
                  {"↓"}
                </span>
                <span style={css("color: #4a4945; line-height: 1.5;")}>
                  {"same graph — value relationships foregrounded"}
                </span>
              </div>
              <div style={css("flex: 1 1 240px; display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 24px; border-radius: 12px; background: #fbfaf8; border: 1px solid #d8d6d0; font-family: var(--font-mono); font-size: 12px; text-align: center;")}>
                <span style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 6px;")}>
                  <span style={css("padding: 6px 10px; border-radius: 6px; background: rgba(107,154,124,0.16); color: #4f7a5e;")}>
                    {"value"}
                  </span>
                  <span style={css("color: #9c9b95; align-self: center;")}>
                    {"+"}
                  </span>
                  <span style={css("padding: 6px 10px; border-radius: 6px; background: rgba(90,133,168,0.16); color: #3f6a8c;")}>
                    {"geography"}
                  </span>
                  <span style={css("color: #9c9b95; align-self: center;")}>
                    {"+"}
                  </span>
                  <span style={css("padding: 6px 10px; border-radius: 6px; background: rgba(201,151,90,0.18); color: #8a6433;")}>
                    {"journey"}
                  </span>
                </span>
                <span style={css("color: #9c9b95;")}>
                  {"↓ semantic merge"}
                </span>
                <span style={css("padding: 8px 14px; border-radius: 6px; background: #1a1a1e; color: #e8e6e1;")}>
                  {"combined perspective"}
                </span>
                <span style={css("color: #4a4945; line-height: 1.5;")}>
                  {"where value moved, by region, along which path"}
                </span>
              </div>
              <div style={css("flex: 1 1 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr)); gap: 6px;")}>
                {(ops).map((o: any, oIndex: number) => (
                  <Fragment key={oIndex}>
                    <a href={link("Docs.dc.html?page=lenses")} style={css("display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 8px; background: #eceae5; border: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e;")} className="hv-4d1362f5">
                      <span style={css("font-size: 13px; font-weight: 500;")}>
                        {o.t}
                      </span>
                      <span style={css("font-size: 12px; color: #6b6a65;")}>
                        {o.b}
                      </span>
                    </a>
                  </Fragment>
                ))}
              </div>
            </div>
          </div>
        </section>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: flex; flex-direction: column; gap: 20px; align-items: flex-start;")}>
            <h2 style={css("font-size: clamp(30px, 4.2vw, 52px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.04; margin: 0; max-width: 760px; text-wrap: balance;")}>
              {"See a new perspective."}
            </h2>
            <div style={css("display: flex; flex-wrap: wrap; gap: 8px;")}>
              <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {portalLabel("Get started")}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Aether Platform.dc.html")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-4d1362f5">
                {"Back to the platform"}
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
