/**
 * Built from design/designs/Aether Agents.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, portalLabel, useDesignState, useLink, useReducedMotion } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-agents-page.css';

import { createElement as h, useEffect, useRef, type ReactNode } from 'react';

type AKind = 'human' | 'agent' | 'system' | 'value';
const EASE = 'cubic-bezier(0.22,1,0.36,1)';
const KC: Record<AKind, string> = { human: '#9fbad6', agent: '#dcb683', system: '#8fb0cc', value: '#9cc4a9' };
const KG: Record<AKind, string> = { human: '●', agent: '⬡', system: '○', value: '↑' };
const CHAIN = ['human', 'orch', 'exec', 'sys', 'out'];
const STAGES: [kicker: string, title: string, body: string][] = [
  ['Instruction', 'A person asks an agent to do something.', 'One instruction. One agent. Aether records who gave it and when.'],
  ['Orchestration', 'The agent starts other agents.', 'An orchestrator creates research, planning, data, and execution agents. Aether records who created whom.'],
  ['Authority', 'Permission is passed down.', 'Full authority with the human, delegated to the orchestrator, scoped tool access for the execution agent against the payment API.'],
  ['Termination', 'The agents end. The history does not.', 'Temporary agents terminate when the task is complete. Their lineage, actions, and outcome remain in Aether — and open in Agent 360.'],
];
type RKind = 'human' | 'agent';
const RL: [title: string, body: string, from: RKind, to: RKind, fromLabel: string, toLabel: string, verb: string, example: string][] = [
  ['Person to person', 'Who works with whom.', 'human', 'human', 'Maya Chen', 'Sam Ortiz', 'reviewed', 'usr_2x8kf → usr_9q1m · reviewed refund'],
  ['Person to agent', 'Who asked an agent to do what.', 'human', 'agent', 'Maya Chen', 'Support agent', 'asked', 'usr_2x8kf → agt_orch_01 · “refund order #5532”'],
  ['Agent to agent', 'Which agent started or handed off to another.', 'agent', 'agent', 'Orchestrator', 'Execution agent', 'handed off', 'agt_orch_01 → agt_x_22 · scoped to payments'],
  ['Agent to person', 'When an agent came back to a person for a decision.', 'agent', 'human', 'Execution agent', 'Maya Chen', 'checked with', 'agt_x_22 → usr_2x8kf · refund above $40 limit'],
];
const RC: Record<RKind, string> = { human: '#3a6896', agent: '#a8783e' };
const RG: Record<RKind, string> = { human: '●', agent: '⬡' };
const STATES: [g: string, k: string, b: string, c: string][] = [['●', 'Observed', 'Something directly occurred.', '#3a6896'], ['○', 'Inferred', 'Aether derived something from evidence.', '#6b6a65'], ['↔', 'Resolved', 'Records determined to be the same entity or relationship.', '#3a6896'], ['✓', 'Authorized', 'A person or system permitted an action.', '#a8783e'], ['→', 'Executed', 'An action occurred.', '#a8783e'], ['✓', 'Verified', 'The expected effect was observed.', '#4f7a5e'], ['↑', 'Measured', 'The resulting outcome was evaluated.', '#4f7a5e']];

export function AetherAgentsPage() {
  const link = useLink();
  usePageMeta('aether-agents');
  const reduce = useReducedMotion();
  const [state, setState] = useDesignState<{ stage: number; w: number; manual: boolean; rel: number; relHeld: boolean }>({ stage: 0, w: 1280, manual: false, rel: 0, relHeld: false });
  const live = useRef(state);
  live.current = state;
  useEffect(() => {
    const onR = () => setState({ w: window.innerWidth });
    const onS = () => {
      if (live.current.w < 1000) return;
      const els = document.querySelectorAll('[data-astep]');
      if (!els.length) return;
      const mid = window.innerHeight * 0.5;
      let best = 0;
      let bd = Infinity;
      els.forEach((el) => {
        const r = el.getBoundingClientRect();
        const d = Math.abs(r.top + r.height / 2 - mid);
        if (d < bd) {
          bd = d;
          best = Number(el.getAttribute('data-astep'));
        }
      });
      if (best !== live.current.stage) setState({ stage: best });
    };
    onR();
    window.addEventListener('resize', onR);
    window.addEventListener('scroll', onS, { passive: true });
    let relTimer: ReturnType<typeof setInterval> | undefined;
    let timer: ReturnType<typeof setInterval> | undefined;
    if (!reduce) {
      relTimer = setInterval(() => {
        if (!live.current.relHeld) setState((s) => ({ rel: (s.rel + 1) % 4 }));
      }, 3200);
      timer = setInterval(() => {
        if (live.current.w < 1000 && !live.current.manual) setState((s) => ({ stage: (s.stage + 1) % 4 }));
      }, 2800);
    }
    return () => {
      window.removeEventListener('resize', onR);
      window.removeEventListener('scroll', onS);
      clearInterval(timer);
      clearInterval(relTimer);
    };
  }, [reduce, setState]);
  const st = state.stage;
  const narrow = state.w < 1000;
  const N: [id: string, label: string, raw: string, kind: AKind, p: [number, number], temp?: string][] = [
    ['human', 'Maya Chen', 'usr_2x8kf', 'human', [300, 48]],
    ['orch', st === 0 ? 'Agent' : 'Orchestrator', 'agt_orch_01', 'agent', [300, 148]],
    ['research', 'Research agent', 'agt_r_14', 'agent', [84, 262], 'temp'],
    ['planning', 'Planning agent', 'agt_p_03', 'agent', [228, 262], 'temp'],
    ['data', 'Data agent', 'agt_d_07', 'agent', [372, 262], 'temp'],
    ['exec', 'Execution agent', 'agt_x_22', 'agent', [516, 262]],
    ['sys', 'Payment API', 'req_9fa', 'system', [516, 352]],
    ['out', 'Refund · $42', 'oc_118', 'value', [516, 432]],
  ];
  const by = Object.fromEntries(N.map((n) => [n[0], n]));
  const visible = (id: string) => st > 0 || id === 'human' || id === 'orch';
  const E: [string, string, string][] =
    st === 0
      ? [['human', 'orch', 'instructs']]
      : [['human', 'orch', st >= 2 ? 'full authority' : 'instructs'], ['orch', 'research', 'spawns'], ['orch', 'planning', 'spawns'], ['orch', 'data', 'spawns'], ['orch', 'exec', st >= 2 ? 'delegated' : 'spawns'], ['exec', 'sys', st >= 2 ? 'scoped tool access' : 'calls'], ['sys', 'out', 'recorded']];
  const edges = E.map(([a, b, lab], i) => {
    const A = by[a]![4];
    const B = by[b]![4];
    const inChain = CHAIN.includes(a) && CHAIN.includes(b);
    const dim = st >= 2 && !inChain;
    const term = st === 3 && by[b]![5] === 'temp';
    const d = 'M' + A[0] + ' ' + (A[1] + 22) + 'L' + B[0] + ' ' + (B[1] - 22);
    const showLab = st >= 2 && inChain && lab !== 'recorded';
    const mx = (A[0] + B[0]) / 2;
    const my = (A[1] + 22 + B[1] - 22) / 2;
    return h(
      'g',
      { key: 'e' + st + i, opacity: dim ? 0.18 : 1, style: { transition: 'opacity 200ms ' + EASE } },
      h('path', { d, pathLength: 1, fill: 'none', stroke: st >= 2 && inChain ? '#dcb683' : '#4a4a52', strokeWidth: st >= 2 && inChain ? 1.8 : 1.2, strokeDasharray: term ? '0.03 0.03' : '1', style: term ? {} : { animation: 'agDraw 320ms ' + EASE + ' ' + (160 + i * 50) + 'ms both' } }),
      showLab
        ? h(
            'g',
            { transform: 'translate(' + (mx + (a === 'orch' ? 0 : 8)) + ',' + my + ')', style: { animation: 'agFade 200ms ' + EASE + ' 260ms both' } },
            h('rect', { x: 0, y: -9, width: lab.length * 6.2 + 14, height: 18, rx: 9, fill: '#dcb683' }),
            h('text', { x: 7, y: 4, fill: '#111114', style: { fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 500 } }, lab),
          )
        : null,
    );
  });
  const nodes = N.map(([id, label, raw, kind, p, temp], i) => {
    const vis = visible(id);
    const start = by.orch![4];
    const [x, y] = vis ? p : start;
    const w = 132;
    const hh = 44;
    const dim = st >= 2 && !CHAIN.includes(id);
    const term = st === 3 && temp;
    return h(
      'g',
      { key: id, style: { transform: 'translate(' + (x - w / 2) + 'px,' + (y - hh / 2) + 'px)', opacity: !vis ? 0 : dim ? (term ? 0.55 : 0.3) : 1, transition: 'transform 320ms ' + EASE + ' ' + i * 30 + 'ms, opacity 200ms ' + EASE } },
      h('rect', { width: w, height: hh, rx: 6, fill: id === 'human' ? '#e8e6e1' : '#111114', stroke: term ? '#6b6a65' : id === 'human' ? '#e8e6e1' : '#2a2a2f', strokeDasharray: term ? '4 3' : undefined }),
      h('text', { x: 12, y: 26, fill: id === 'human' ? '#3a6896' : KC[kind], style: { fontFamily: 'var(--font-mono)', fontSize: 12 } }, KG[kind]),
      h('text', { x: 28, y: 19, fill: id === 'human' ? '#1a1a1e' : '#e8e6e1', style: { fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 500 } }, label),
      h('text', { x: 28, y: 34, fill: id === 'human' ? '#6b6a65' : '#a09f99', style: { fontFamily: 'var(--font-mono)', fontSize: 10 } }, term ? 'terminated 10:07' : raw),
    );
  });
  const hist: ReactNode =
    st === 3
      ? h(
          'g',
          { key: 'hist', style: { animation: 'agFade 320ms ' + EASE + ' 200ms both' } },
          h('rect', { x: 18, y: 330, width: 290, height: 120, rx: 8, fill: 'none', stroke: '#3a3a40', strokeDasharray: '3 4' }),
          h('text', { x: 34, y: 354, fill: '#9cc4a9', style: { fontFamily: 'var(--font-mono)', fontSize: 11 } }, '● history remains in Aether'),
          ['10:02  instructed  usr_2x8kf → agt_orch_01', '10:03  spawned     agt_r_14, agt_p_03, agt_d_07', '10:06  tool call   agt_x_22 → req_9fa', '10:07  terminated  3 temporary agents'].map((t, i) =>
            h('text', { key: i, x: 34, y: 378 + i * 17, fill: '#a09f99', style: { fontFamily: 'var(--font-mono)', fontSize: 10 } }, t),
          ),
        )
      : null;
  const tree = h('svg', { viewBox: '0 0 600 470', width: '100%', height: '100%', role: 'img', 'aria-label': 'Agent lineage, step ' + (st + 1) + ' of 4', style: { position: 'absolute', inset: 0, display: 'block', overflow: 'visible' } }, h('g', { key: 'E' }, edges), h('g', { key: 'N' }, nodes), hist);
  const ri = state.rel;
  const cur = RL[ri]!;
  const node = (x: number, kind: RKind, label: string, k: string) =>
    h(
      'g',
      { key: k + ri, style: { transform: 'translate(' + x + 'px, 75px)', animation: 'agFade 200ms ' + EASE + ' both' } },
      h('circle', { r: 22, fill: kind === 'human' ? '#1a1a1e' : '#f5f4f1', stroke: RC[kind], strokeWidth: 1.5 }),
      h('text', { y: 5, textAnchor: 'middle', fill: kind === 'human' ? '#e8e6e1' : RC[kind], style: { fontFamily: 'var(--font-mono)', fontSize: 14 } }, RG[kind]),
      h('text', { y: 44, textAnchor: 'middle', fill: '#1a1a1e', style: { fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 500 } }, label),
    );
  const relViz = h(
    'svg',
    { viewBox: '0 0 420 150', width: '100%', height: '100%', role: 'img', 'aria-label': cur[0], style: { position: 'absolute', inset: 0, display: 'block', overflow: 'visible' } },
    h('path', { key: 'l' + ri, d: 'M 92 75 L 318 75', pathLength: 1, fill: 'none', stroke: RC[cur[3]], strokeWidth: 1.5, strokeDasharray: '1', style: { animation: 'agDraw 320ms ' + EASE + ' 120ms both' } }),
    h('path', { key: 'a' + ri, d: 'M 310 69 L 318 75 L 310 81', fill: 'none', stroke: RC[cur[3]], strokeWidth: 1.5, style: { animation: 'agFade 200ms ' + EASE + ' 380ms both' } }),
    h(
      'g',
      { key: 'tg' + ri, style: { animation: 'agFade 200ms ' + EASE + ' 300ms both' } },
      h('rect', { x: 210 - (cur[6].length * 3.3 + 10), y: 54, width: cur[6].length * 6.6 + 20, height: 20, rx: 10, fill: '#f5f4f1', stroke: '#d8d6d0' }),
      h('text', { x: 210, y: 68, textAnchor: 'middle', fill: '#4a4945', style: { fontFamily: 'var(--font-mono)', fontSize: 11 } }, cur[6]),
    ),
    reduce
      ? null
      : h(
          'circle',
          { key: 'p' + ri, r: 3, fill: RC[cur[3]], opacity: 0 },
          h('animateMotion', { dur: '1.8s', begin: '0.5s', repeatCount: 'indefinite', path: 'M 92 75 L 318 75' }),
          h('animate', { attributeName: 'opacity', values: '0;1;1;0', keyTimes: '0;0.1;0.85;1', dur: '1.8s', begin: '0.5s', repeatCount: 'indefinite' }),
        ),
    node(60, cur[2], cur[4], 'na'),
    node(350, cur[3], cur[5], 'nb'),
  );
  const relEx = cur[7];
  const rels = RL.map(([t, b, from, to], i) => {
    const on = i === ri;
    return {
      t, b, g: RG[from] + ' → ' + RG[to], sel: on, go: () => setState({ rel: i, relHeld: true }),
      gStyle: 'font-family: var(--font-mono); font-size: 13px; color: ' + (on ? RC[to] : '#9c9b95') + '; transition: color 200ms ' + EASE + ';',
      bar: 'position: absolute; left: 0; top: -1px; height: 2px; width: ' + (on ? '100%' : '0') + '; background: #1a1a1e; transition: width 320ms ' + EASE + ';',
      style: 'font-family: inherit; position: relative; text-align: left; display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 20px; align-items: baseline; padding: 20px 0; background: transparent; border: 0; border-bottom: 1px solid #d8d6d0; cursor: pointer; color: #1a1a1e;',
      tStyle: 'font-size: 17px; font-weight: 500; color: ' + (on ? '#1a1a1e' : '#6b6a65') + '; transition: color 200ms ' + EASE + ';',
    };
  });
  const steps = STAGES.map(([kicker, title, body], i) => ({
    i, n: '0' + (i + 1), kicker, title, body,
    style: 'min-height: ' + (narrow ? 'auto' : '64vh') + '; display: flex; flex-direction: column; justify-content: center; gap: 12px; padding: ' + (narrow ? '24px 0 24px 24px' : '0 0 0 24px') + '; border-left: 2px solid ' + (i === st ? '#dcb683' : '#2a2a2f') + '; opacity: ' + (i === st || narrow ? 1 : 0.38) + '; transition: opacity 320ms ' + EASE + ', border-color 200ms ' + EASE + ';',
  }));
  const stageLabel = ['01 · instruction', '02 · orchestration', '03 · authority', '04 · termination'][st];
  const stickyStyle = narrow ? 'position: relative; order: -1;' : 'position: sticky; top: calc(50vh - 300px); margin-top: 18vh;';
  const bars = [0, 1, 2, 3].map((i) => ({ label: 'Step ' + (i + 1), go: () => setState({ stage: i, manual: true }), style: 'height: 10px; padding: 4px 0; border: 0; cursor: pointer; background: transparent; background-clip: content-box; box-sizing: border-box; border-top: 2px solid ' + (i <= st ? '#dcb683' : '#2a2a2f') + '; transition: border-color 200ms ' + EASE + ';' }));
  const asks = ['Who created whom?', 'Who instructed whom?', 'Who had authority?', 'What tools were used?', 'What happened?', 'What did the agent affect?', 'What outcome resulted?'].map((q, i) => ({ q, n: '0' + (i + 1) }));
  const states = STATES.map(([g, k, b, c]) => ({ g, k, b, gStyle: 'font-family: var(--font-mono); font-size: 16px; color: ' + c + ';', style: 'display: flex; flex-direction: column; gap: 8px; padding: 20px; min-height: 150px; box-sizing: border-box; border-right: 1px solid #d8d6d0; border-top: 3px solid ' + c + ';' }));
  return (
    <div className="dc pg-aether-agents">
    <div data-page="aether-agents" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
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
                  {"Agents"}
                </span>
              </span>
              <h1 style={css("font-size: clamp(44px, 6.4vw, 84px); font-weight: 500; line-height: 0.96; letter-spacing: -0.045em; margin: 0; text-wrap: balance;")}>
                {"Observe every agent, and who orchestrated it."}
              </h1>
            </div>
            <p style={css("font-size: 17px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 500px; padding-bottom: 8px;")}>
              {"Aether keeps a clear record of every AI agent: who started it, what it was allowed to do, what it touched, and what happened. The record stays even after the agent is gone."}
            </p>
          </div>
        </section>
        <section id="lineage" data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: clamp(24px, 5vw, 72px); align-items: start;")}>
            <div style={css("display: flex; flex-direction: column;")}>
              {(steps).map((s: any, sIndex: number) => (
                <Fragment key={sIndex}>
                  <div data-astep={s.i} style={css(s.style)}>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #dcb683;")}>
                      {s.n}{" · "}{s.kicker}
                    </span>
                    <span style={css("font-size: clamp(24px, 2.6vw, 32px); font-weight: 500; letter-spacing: -0.02em; line-height: 1.15; color: #e8e6e1; text-wrap: balance;")}>
                      {s.title}
                    </span>
                    <span style={css("font-size: 15px; line-height: 1.6; color: #a09f99; max-width: 440px;")}>
                      {s.body}
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
            <div style={css(stickyStyle)}>
              <div style={css("border: 1px solid #2a2a2f; border-radius: 12px; background: #1a1a1e; padding: 20px; display: flex; flex-direction: column; gap: 14px;")}>
                <div style={css("display: flex; justify-content: space-between; align-items: center; gap: 8px;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                    {"Agent lineage"}
                  </span>
                  <span style={css("font-family: var(--font-mono); font-size: 11px; color: #dcb683;")}>
                    {stageLabel}
                  </span>
                </div>
                <div style={css("position: relative; width: 100%; aspect-ratio: 600 / 470;")}>
                  {tree}
                </div>
                <div style={css("display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px;")}>
                  {(bars).map((b: any, bIndex: number) => (
                    <Fragment key={bIndex}>
                      <button type="button" onClick={b.go} aria-label={b.label} style={css(b.style)} />
                    </Fragment>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>
        <section id="records" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 104px) 24px; display: flex; flex-wrap: wrap; gap: clamp(24px, 4vw, 56px); align-items: flex-start;")}>
            <div style={css("flex: 1 1 300px; display: flex; flex-direction: column; gap: 14px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #8a6433;")}>
                {"Aether records"}
              </span>
              <h2 style={css("font-size: clamp(28px, 3.4vw, 44px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0; text-wrap: balance;")}>
                {"Seven questions you can always answer."}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"Aether watches and records. It doesn’t approve, block, or send agent actions — people stay in charge of those."}
              </p>
            </div>
            <ol style={css("flex: 2 1 520px; list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 8px;")}>
              {(asks).map((a: any, aIndex: number) => (
                <Fragment key={aIndex}>
                  <li style={css("display: flex; gap: 12px; align-items: baseline; padding: 16px 18px; border-radius: 10px; background: #fbfaf8; border: 1px solid #d8d6d0;")}>
                    <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a8783e;")}>
                      {a.n}
                    </span>
                    <span style={css("font-size: 16px; font-weight: 500;")}>
                      {a.q}
                    </span>
                  </li>
                </Fragment>
              ))}
            </ol>
          </div>
        </section>
        <section id="evidence" style={css("border-bottom: 1px solid #d8d6d0; background: #eceae5;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 104px) 24px; display: flex; flex-direction: column; gap: 28px;")}>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 24px; align-items: end;")}>
              <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #4f7a5e;")}>
                  {"Evidence states"}
                </span>
                <h2 style={css("font-size: clamp(28px, 3.4vw, 44px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0;")}>
                  {"How Aether knows what it knows."}
                </h2>
              </div>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"Everything Aether shows is labeled: did it see this happen, or work it out? The two are never mixed up."}
              </p>
            </div>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr)); gap: 0; border: 1px solid #d8d6d0; border-radius: 12px; overflow: hidden; background: #fbfaf8;")}>
              {(states).map((s: any, sIndex: number) => (
                <Fragment key={sIndex}>
                  <div style={css(s.style)}>
                    <span style={css(s.gStyle)}>
                      {s.g}
                    </span>
                    <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase;")}>
                      {s.k}
                    </span>
                    <span style={css("font-size: 13px; line-height: 1.5; color: #4a4945;")}>
                      {s.b}
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="relationships" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 120px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: clamp(32px, 6vw, 96px); align-items: start;")}>
            <div style={css("display: flex; flex-direction: column; gap: 16px;")}>
              <h2 style={css("font-size: clamp(30px, 3.8vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
                {"People and AI, working together."}
              </h2>
              <p style={css("font-size: 16px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 420px;")}>
                {"Work now moves between people and AI agents in every direction. Aether keeps track of all four."}
              </p>
              <div style={css("margin-top: 24px; border: 1px solid #d8d6d0; border-radius: 12px; background: #fbfaf8; padding: 20px; display: flex; flex-direction: column; gap: 12px; max-width: 460px;")}>
                <div style={css("position: relative; width: 100%; aspect-ratio: 420 / 150;")}>
                  {relViz}
                </div>
                <span style={css("font-family: var(--font-mono); font-size: 12px; color: #4a4945; min-height: 18px;")}>
                  {relEx}
                </span>
              </div>
            </div>
            <div role="tablist" aria-label="Relationship types" style={css("display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              {(rels).map((r: any, rIndex: number) => (
                <Fragment key={rIndex}>
                  <button type="button" role="tab" aria-selected={r.sel} onClick={r.go} style={css(r.style)}>
                    <span style={css(r.gStyle)}>
                      {r.g}
                    </span>
                    <span style={css("display: flex; flex-direction: column; gap: 4px;")}>
                      <span style={css(r.tStyle)}>
                        {r.t}
                      </span>
                      <span style={css("font-size: 14px; color: #6b6a65;")}>
                        {r.b}
                      </span>
                    </span>
                    <span style={css(r.bar)} />
                  </button>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: flex; flex-direction: column; gap: 20px; align-items: flex-start;")}>
            <h2 style={css("font-size: clamp(30px, 4.2vw, 52px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.04; margin: 0; max-width: 760px; text-wrap: balance;")}>
              {"Record one agent action. See its full history."}
            </h2>
            <div style={css("display: flex; flex-wrap: wrap; gap: 8px;")}>
              <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {portalLabel("Get started")}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Contact.dc.html?brand=aether&type=pilot")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-4d1362f5">
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
