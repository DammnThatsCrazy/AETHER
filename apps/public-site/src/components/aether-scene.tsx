/**
 * Built from design/designs/Aether Scene.dc.html: the signature
 * disconnected → connected diagram. Three stories (customer, agent, value),
 * four stages each (fragmented, connected, history, lens), drawn as frosted
 * glass tiles with brand-logo chips over a glowing dark panel. Connections
 * curve and carry slow dots (6.4s trips); tiles move in 240ms and drift 3px.
 * Story data, copy and styles are verbatim from the design.
 */
import { createElement as h, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { asset, css, useDesignState, useReducedMotion } from '@site/design/runtime';
import { markSrc } from '@site/components/brand-mark';
import './aether-scene.css';

type Kind = 'center' | 'system' | 'agent' | 'human' | 'org' | 'value';
type StoryKey = 'customer' | 'agent' | 'value';
type RawNode = [id: string, kind: Kind, sys: string, raw: string, label: string, conn: [number, number], tag: string | null, t: string | null, hideFrag?: boolean];

interface Story {
  lens: string;
  g: string;
  label: string;
  close: string;
  subs: [string, string, string, string];
  nodes: RawNode[];
  conn: [string, string, number?][];
  seq: string[];
}

export const SCENE_STORIES: Record<StoryKey, Story> = {
  customer: {
    lens: 'Value lens',
    g: '●',
    label: 'Customer',
    close: 'Aether understands that as one connected journey rather than seven unrelated records.',
    subs: ['7 records · 7 systems · no shared identity', '1 profile · 7 relationships', '1 journey · 7 steps · 8h 29m', 'value foregrounded · credit across 4 touchpoints'],
    nodes: [
      ['jane', 'center', 'Aether profile', 'prf_7k2m', 'Sofia Marchetti', [300, 220], null, null, true],
      ['ad', 'system', 'Google Ads', 'clk_88f1', 'Ad impression', [110, 100], '18% credit', '09:01'],
      ['web', 'system', 'Web SDK', 'anon_941', 'Website visit', [300, 64], '27% credit', '09:04'],
      ['app', 'system', 'iOS SDK', 'dev_ios_2c9', 'Mobile app', [490, 100], null, '09:15'],
      ['email', 'system', 'Klaviyo', 'evt_311', 'Email', [505, 252], '31% credit', '11:43'],
      ['agent', 'agent', 'Support agent', 'session_381', 'Agent chat', [400, 372], '24% credit', '14:22'],
      ['buy', 'value', 'Stripe', 'cus_3321', 'Purchase · $149', [200, 372], '$149', '16:08'],
      ['support', 'system', 'Zendesk', 'tkt_5521', 'Support ticket', [95, 252], null, '17:30'],
    ],
    conn: [['jane', 'ad', 1], ['jane', 'web', 1], ['jane', 'app'], ['jane', 'email'], ['jane', 'agent'], ['jane', 'buy'], ['jane', 'support']],
    seq: ['ad', 'web', 'app', 'email', 'agent', 'buy', 'support'],
  },
  agent: {
    lens: 'Authority lens',
    g: '⬡',
    label: 'Agent',
    close: 'Aether preserves who acted, under whose authority, against what system, and what resulted.',
    subs: ['7 records · 4 logs · no lineage', '1 human · 4 agents · 1 system · 1 outcome', '1 chain · 5 minutes · every handoff recorded', 'authority traced from instruction to outcome'],
    nodes: [
      ['maya', 'human', 'Okta', 'usr_2x8kf', 'Maya Chen', [300, 56], 'full authority', '10:02'],
      ['orch', 'agent', 'Agent runtime', 'agt_orch_01', 'Orchestrator', [300, 152], 'delegated', '10:02'],
      ['research', 'agent', 'Task queue', 'agt_r_14', 'Research agent', [110, 252], null, '10:03'],
      ['data', 'agent', 'Tool calls', 'agt_d_07', 'Data agent', [300, 252], null, '10:04'],
      ['exec', 'agent', 'Agent logs', 'agt_x_22', 'Execution agent', [490, 252], 'scoped access', '10:06'],
      ['api', 'system', 'Stripe API', 'req_9fa', 'Payment API', [490, 356], 'observed', '10:06'],
      ['out', 'value', 'Ledger', 'oc_118', 'Refund · $42', [300, 392], 'recorded', '10:07'],
    ],
    conn: [['maya', 'orch'], ['orch', 'research'], ['orch', 'data'], ['orch', 'exec'], ['research', 'data', 1], ['data', 'exec', 1], ['exec', 'api'], ['api', 'out']],
    seq: ['maya', 'orch', 'research', 'data', 'exec', 'api', 'out'],
  },
  value: {
    lens: 'Attribution lens',
    g: '↑',
    label: 'Value',
    close: 'Where did this value come from? Every contributing relationship, with its share of credit.',
    subs: ['7 records · 6 systems · no attribution', '1 path from referral to revenue', '9 days · 7 steps', 'credit distributed across 4 contributors'],
    nodes: [
      ['ref', 'human', 'Referral link', 'ref_0x91', 'Referral · Ana R.', [100, 84], '12% credit', 'Mar 02'],
      ['camp', 'org', 'Meta Ads', 'cmp_spring', 'Spring campaign', [300, 84], '34% credit', 'Mar 04'],
      ['email', 'system', 'Klaviyo', 'msg_7731', 'Email · restock', [500, 84], '29% credit', 'Mar 09'],
      ['journey', 'system', 'Aether journey', 'jrn_44a', 'Trial → paid', [500, 226], '25% credit', 'Mar 09'],
      ['person', 'human', 'HubSpot', 'ct_10293', 'Sofia Marchetti', [300, 226], null, 'Mar 10'],
      ['order', 'system', 'Shopify', 'ord_5532', 'Order #5532', [100, 226], null, 'Mar 10'],
      ['val', 'center', 'Stripe', 'ch_3Nf2', '$149 revenue', [300, 370], '100% attributed', 'Mar 11'],
    ],
    conn: [['ref', 'camp'], ['camp', 'email'], ['email', 'journey'], ['journey', 'person'], ['person', 'order'], ['order', 'val'], ['ref', 'person', 1]],
    seq: ['ref', 'camp', 'email', 'journey', 'person', 'order', 'val'],
  },
};

const STORY_ORDER: StoryKey[] = ['customer', 'agent', 'value'];
const KG: Record<Kind, string> = { human: '●', agent: '⬡', system: '○', value: '↑', org: '◈', center: '●' };
const KC: Record<Kind, string> = { human: '#9fbad6', agent: '#dcb683', system: '#8fb0cc', value: '#9cc4a9', org: '#c9b088', center: '#9fbad6' };
const FR: [number, number][] = [[104, 92], [300, 70], [496, 100], [112, 226], [488, 232], [118, 356], [300, 374], [490, 354]];
const CAPS = ['Your systems know pieces of the story.', 'Aether understands how those pieces belong together.', 'Then turns activity into history and journeys.', 'Explore the same reality from any perspective.'];
const GOLD = '#e0b878';
const BLUR = 'blur(18px) saturate(1.5)';
// Source systems with a provider logo; Aether's own sources carry the Aether mark; the rest get their kind glyph.
const LG: Record<string, string> = { 'Google Ads': 'googleads', 'iOS SDK': 'apple', Klaviyo: 'klaviyo', Zendesk: 'zendesk', Stripe: 'stripe', 'Stripe API': 'stripe', 'Meta Ads': 'meta', HubSpot: 'hubspot', Shopify: 'shopify' };
const AEN = ['Web SDK', 'Aether profile', 'Aether journey', 'Support agent', 'Agent runtime'];
const logoOf = (sys: string) => (LG[sys] ? asset('assets/brand/' + LG[sys] + '.svg') : AEN.includes(sys) ? markSrc('aether') : null);

export interface AetherSceneProps {
  story?: string;
  /** Fixed stage (0–3); when set, autoplay does not advance. */
  stage?: number | string | null;
  autoplay?: boolean;
  /** Cycle stories at the end of each run. */
  rotate?: boolean;
  controls?: boolean;
  /** Kept for callers; the glass panel is always dark. */
  dark?: boolean;
  /** Comma list of stages to play, default "0,1,2,3". */
  stages?: string;
  interval?: number;
  style?: CSSProperties;
}

interface SceneNode {
  id: string;
  kind: Kind;
  sys: string;
  raw: string;
  label: string;
  conn: [number, number];
  tag: string | null;
  t: string | null;
  hideFrag?: boolean;
  frag: [number, number];
  time: [number, number];
}

function isStory(value: unknown): value is StoryKey {
  return value === 'customer' || value === 'agent' || value === 'value';
}

export function AetherScene(props: AetherSceneProps) {
  const reduce = useReducedMotion();
  const [state, setState] = useDesignState<{ story: StoryKey | null; stage: number | null; hold: boolean }>({ story: null, stage: null, hold: false });
  const list = String(props.stages ?? '0,1,2,3').split(',').map(Number);
  const propsRef = useRef(props);
  propsRef.current = props;
  const holdRef = useRef(state.hold);
  holdRef.current = state.hold;
  const wrapRef = useRef<HTMLDivElement>(null);
  const [k, setK] = useState(1);

  useEffect(() => {
    if (!props.autoplay || reduce) return;
    const timer = setInterval(() => {
      const p = propsRef.current;
      if (holdRef.current || p.stage != null) return;
      const L = String(p.stages ?? '0,1,2,3').split(',').map(Number);
      setState((s) => {
        const cur = s.stage ?? L[0] ?? 0;
        let i = L.indexOf(cur) + 1;
        let story: StoryKey = s.story ?? (isStory(p.story) ? p.story : 'customer');
        if (i >= L.length) {
          i = 0;
          if (p.rotate) story = STORY_ORDER[(STORY_ORDER.indexOf(story) + 1) % 3] ?? 'customer';
        }
        return { stage: L[i] ?? 0, story };
      });
    }, props.interval ?? 4200);
    return () => clearInterval(timer);
  }, [props.autoplay, props.interval, reduce, setState]);

  // The stage is laid out at 600×440 and scaled to the frame's width.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const fit = () => {
      if (el.clientWidth) setK(el.clientWidth / 600);
    };
    fit();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const storyKey = state.story ?? props.story ?? 'customer';
  const st: StoryKey = isStory(storyKey) ? storyKey : 'customer';
  const S = SCENE_STORIES[st];
  const stage = props.stage != null && props.stage !== '' ? Number(props.stage) : state.stage ?? list[0] ?? 0;

  let fi = 0;
  const nodes: SceneNode[] = S.nodes.map(([id, kind, sys, raw, label, conn, tag, t, hideFrag]) => {
    const frag: [number, number] = hideFrag ? [300, 220] : FR[fi++] ?? [300, 220];
    const q = S.seq.indexOf(id);
    const time: [number, number] = q < 0 ? [300, 96] : [72 + q * 76, q % 2 ? 336 : 238];
    return { id, kind, sys, raw, label, conn, tag, t, hideFrag, frag, time };
  });
  // Keep each tile inside the 600px stage: the history layout puts the last step at x=528, where the wider center tile would overhang.
  const pos = (n: SceneNode): [number, number] => {
    const p = stage === 0 ? n.frag : stage === 2 ? n.time : n.conn;
    const half = (n.kind === 'center' ? 192 : 150) / 2 + 4;
    return [Math.min(600 - half, Math.max(half, p[0])), p[1]];
  };
  const byId: Record<string, SceneNode> = {};
  nodes.forEach((n) => {
    byId[n.id] = n;
  });
  const lensOn = stage === 3;
  const ease = 'cubic-bezier(0.22,1,0.36,1)';
  const edges: [string, string, number?][] = stage === 0 ? [] : stage === 2 ? S.seq.slice(1).map((b, i) => [S.seq[i] ?? b, b, 0]) : S.conn;
  const edgeEls = edges.map(([a, b, dashed], i) => {
    const na = byId[a];
    const nb = byId[b];
    if (!na || !nb) return null;
    const A = pos(na);
    const B = pos(nb);
    const lz = (n: SceneNode) => n.tag || n.kind === 'center';
    const hi = lensOn && lz(na) && lz(nb);
    const dim = lensOn && !hi;
    // Each connection bows to alternating sides so the map reads as curves, not spokes.
    const dx = B[0] - A[0];
    const dy = B[1] - A[1];
    const len = Math.hypot(dx, dy) || 1;
    const sg = (a.length + b.length + i) % 2 ? 1 : -1;
    const bow = Math.min(70, len * 0.24) * sg;
    const cx = (A[0] + B[0]) / 2 - (dy / len) * bow;
    const cy = (A[1] + B[1]) / 2 + (dx / len) * bow;
    const d = 'M' + A[0] + ' ' + A[1] + 'Q' + cx.toFixed(1) + ' ' + cy.toFixed(1) + ' ' + B[0] + ' ' + B[1];
    const delay = 220 + i * 45;
    const stroke = hi ? GOLD : 'rgba(255,255,255,0.34)';
    const kids: ReactNode[] = [
      h('path', {
        key: 'p',
        d,
        pathLength: 1,
        fill: 'none',
        stroke,
        strokeWidth: hi ? 2 : 1.25,
        strokeLinecap: 'round',
        strokeDasharray: dashed ? '0.014 0.014' : '1',
        style: dashed ? { animation: 'aeFade 320ms ' + ease + ' ' + delay + 'ms both' } : { strokeDashoffset: 0, animation: 'aeDraw 320ms ' + ease + ' ' + delay + 'ms both' },
      }),
    ];
    if (!reduce && !dashed && !dim && i < 6) {
      // The dot travels an offset copy of the path from off-canvas so it never sits at the origin before it starts.
      const dS = 'M' + (A[0] + 2000) + ' ' + (A[1] + 2000) + 'Q' + (cx + 2000).toFixed(1) + ' ' + (cy + 2000).toFixed(1) + ' ' + (B[0] + 2000) + ' ' + (B[1] + 2000);
      kids.push(
        h(
          'circle',
          { key: 'c', cx: -2000, cy: -2000, r: 2.8, fill: hi ? GOLD : '#cfe0f2', style: { opacity: 0 } },
          h('animateMotion', { dur: '6.4s', begin: 0.8 + i * 0.9 + 's', repeatCount: 'indefinite', path: dS, calcMode: 'spline', keyTimes: '0;1', keyPoints: '0;1', keySplines: '0.22 1 0.36 1' }),
          h('animate', { attributeName: 'opacity', values: '0;0.9;0.9;0', keyTimes: '0;0.2;0.8;1', dur: '6.4s', begin: 0.8 + i * 0.9 + 's', repeatCount: 'indefinite' }),
        ),
      );
      kids.push(h('animate', { key: 'br', attributeName: 'stroke-opacity', values: '1;0.55;1', dur: 5 + (i % 3) + 's', begin: i * 0.7 + 's', repeatCount: 'indefinite' }));
    }
    return h('g', { key: st + stage + 'e' + i, opacity: dim ? 0.16 : 1, style: { transition: 'opacity 200ms ' + ease } }, kids);
  });
  const nodeEls = nodes.map((n, i) => {
    const [x, y] = pos(n);
    const isC = n.kind === 'center';
    const w = isC ? 192 : 150;
    const hh = isC ? 62 : 52;
    const hidden = stage === 0 && n.hideFrag;
    const dim = lensOn && !n.tag && !isC;
    const acc = KC[n.kind];
    const title = stage === 0 ? n.sys : n.label;
    const logo = logoOf(n.sys);
    const hot = lensOn && n.tag;
    const chipSz = isC ? 38 : 26;
    const chip = logo
      ? h('span', { key: 'c', style: { width: chipSz, height: chipSz, flexShrink: 0, borderRadius: isC ? 12 : 9, background: 'rgba(255,255,255,0.94)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 1px 2px rgba(0,0,0,0.25)' } }, h('img', { src: logo, alt: '', style: { width: chipSz - 12, height: chipSz - 12, objectFit: 'contain' } }))
      : h('span', { key: 'c', 'aria-hidden': true, style: { width: chipSz, height: chipSz, flexShrink: 0, borderRadius: 9, background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.16)', color: acc, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-mono)', fontSize: 14 } }, KG[n.kind]);
    const kids: ReactNode[] = [
      chip,
      h(
        'span',
        { key: 't', style: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 } },
        h('span', { style: { fontSize: isC ? 14 : 12, fontWeight: 500, letterSpacing: '-0.01em', color: '#f4f2ee', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, title),
        h('span', { style: { fontFamily: 'var(--font-mono)', fontSize: 10, color: isC ? '#d5d3cd' : '#b4b2ac', whiteSpace: 'nowrap' } }, n.raw),
      ),
    ];
    if (stage === 0 && !isC) kids.push(h('span', { key: 'x', style: { position: 'absolute', right: 9, top: 9, width: 6, height: 6, borderRadius: 3, background: 'rgba(255,255,255,0.3)' } }));
    if (stage === 2 && n.t) kids.push(h('span', { key: 'tm', style: { position: 'absolute', left: 4, top: -17, fontFamily: 'var(--font-mono)', fontSize: 10, color: '#b4b2ac' } }, n.t));
    if (lensOn && n.tag) kids.push(h('span', { key: 'tag', style: { position: 'absolute', left: '50%', top: hh + 6, transform: 'translateX(-50%)', whiteSpace: 'nowrap', padding: '2px 9px', borderRadius: 999, fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 500, color: '#f6e2bf', background: 'rgba(201,151,90,0.3)', border: '1px solid rgba(224,184,120,0.55)', WebkitBackdropFilter: 'blur(10px)', backdropFilter: 'blur(10px)', animation: 'aeFade 200ms ' + ease + ' 200ms both' } }, n.tag));
    return h(
      'div',
      {
        key: st + n.id,
        style: {
          position: 'absolute',
          left: 0,
          top: 0,
          width: w,
          height: hh,
          boxSizing: 'border-box',
          padding: isC ? '0 14px' : '0 8px',
          display: 'flex',
          alignItems: 'center',
          gap: isC ? 10 : 8,
          borderRadius: isC ? 20 : 15,
          background: isC ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.09)',
          border: '1px solid ' + (hot ? 'rgba(224,184,120,0.7)' : isC ? 'rgba(255,255,255,0.4)' : 'rgba(255,255,255,0.17)'),
          boxShadow: 'inset 0 1px 0 rgba(255,255,255,' + (isC ? 0.34 : 0.2) + '), 0 10px 28px rgba(0,0,0,0.32)',
          WebkitBackdropFilter: BLUR,
          backdropFilter: BLUR,
          transform: 'translate(' + (x - w / 2) + 'px,' + (y - hh / 2) + 'px)',
          opacity: hidden ? 0 : dim ? 0.32 : 1,
          animation: reduce ? 'none' : 'aeFloat ' + (5 + (i % 4)) + 's ease-in-out ' + -i * 1.1 + 's infinite',
          transition: 'transform 240ms ' + ease + ' ' + i * 10 + 'ms, opacity 200ms ' + ease + ', border-color 200ms ' + ease,
        },
      },
      kids,
    );
  });
  const axis = stage === 2 ? h('line', { key: 'ax', x1: 40, y1: 287, x2: 560, y2: 287, stroke: 'rgba(255,255,255,0.16)', strokeWidth: 1, style: { animation: 'aeFade 320ms ' + ease + ' both' } }) : null;
  const svg = h('svg', { key: 'svg', viewBox: '0 0 600 440', width: 600, height: 440, 'aria-hidden': true, style: { position: 'absolute', left: 0, top: 0, overflow: 'visible' } }, axis, h('g', { key: 'E' }, edgeEls));
  const stageEl = h(
    'div',
    { role: 'img', 'aria-label': S.label + ' scenario, ' + ['fragmented', 'connected', 'history', S.lens][stage] + ' view', style: { position: 'absolute', left: 0, top: 0, width: 600, height: 440, transformOrigin: '0 0', transform: 'scale(' + k + ')' } },
    svg,
    nodeEls,
  );
  const hold = (patch: { story?: StoryKey; stage?: number }) => setState({ hold: true, ...patch });
  const names = ['Fragmented', 'Connected', 'History', S.lens];
  const controls = !!props.controls;
  const stories = STORY_ORDER.map((key) => {
    const on = key === st;
    return {
      key,
      label: SCENE_STORIES[key].label,
      g: SCENE_STORIES[key].g,
      sel: on,
      go: () => hold({ story: key, stage: 1 }),
      style:
        'font-family: inherit; display: inline-flex; gap: 6px; align-items: center; min-height: 32px; padding: 0 14px; border-radius: 999px; border: 0; cursor: pointer; font-size: 12px; font-weight: 500; transition: background-color 120ms ' +
        ease +
        ', color 120ms ' +
        ease +
        '; ' +
        (on ? 'background: rgba(255,255,255,0.94); color: #111114;' : 'background: transparent; color: #cfcdc7;'),
    };
  });
  const liveLabel = state.hold ? 'paused · synthetic example' : 'synthetic example';
  const liveDot = 'width: 6px; height: 6px; border-radius: 999px; background: ' + (state.hold ? '#9c9b95' : '#6b9a7c') + ';';
  const steps = list.map((kk, i) => {
    const on = kk === stage;
    return {
      key: kk,
      n: '0' + (i + 1),
      label: names[kk],
      sel: on,
      go: () => hold({ stage: kk }),
      bar: 'height: 3px; border-radius: 3px; width: 100%; background: ' + (on ? '#f4f2ee' : 'rgba(255,255,255,0.18)') + '; transition: background-color 200ms ' + ease + ';',
      style:
        'font-family: inherit; text-align: left; display: flex; flex-direction: column; gap: 8px; padding: 0 0 4px; background: transparent; border: 0; cursor: pointer; font-size: 12px; font-weight: 500; color: ' +
        (on ? '#f4f2ee' : '#b4b2ac') +
        '; transition: color 120ms ' +
        ease +
        ';',
    };
  });
  const caption = stage === 3 ? S.close : CAPS[stage];
  const sub = S.subs[stage as 0 | 1 | 2 | 3];

  return (
    <div className="dc pg-aether-scene" style={props.style}>
      <div style={css('position: relative; overflow: hidden; width: 100%; box-sizing: border-box; border-radius: 22px; background: #0d0d10; border: 1px solid rgba(255,255,255,0.08); padding: clamp(12px, 2vw, 20px); font-family: var(--font-sans); color: #e8e6e1;')}>
        <div style={css('position: absolute; width: 70%; aspect-ratio: 1; left: -18%; top: -26%; border-radius: 999px; background: radial-gradient(closest-side, rgba(58,104,150,0.62), rgba(58,104,150,0));')} />
        <div style={css('position: absolute; width: 62%; aspect-ratio: 1; right: -20%; top: 18%; border-radius: 999px; background: radial-gradient(closest-side, rgba(201,151,90,0.46), rgba(201,151,90,0));')} />
        <div style={css('position: absolute; width: 66%; aspect-ratio: 1; left: 12%; bottom: -34%; border-radius: 999px; background: radial-gradient(closest-side, rgba(107,154,124,0.42), rgba(107,154,124,0));')} />
        <div style={css('position: relative; display: flex; flex-direction: column; gap: 14px;')}>
          {controls ? (
            <div style={css('display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px;')}>
              <div role="tablist" aria-label="Scenario" style={css('display: flex; gap: 2px; padding: 3px; border-radius: 999px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14); -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px);')}>
                {stories.map((s) => (
                  <button key={s.key} type="button" role="tab" aria-selected={s.sel} onClick={s.go} style={css(s.style)}>
                    <span aria-hidden="true" style={css('font-family: var(--font-mono);')}>
                      {s.g}
                    </span>
                    {s.label}
                  </button>
                ))}
              </div>
              <span style={css('display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: 11px; color: #b4b2ac;')}>
                <span style={css(liveDot)} />
                {liveLabel}
              </span>
            </div>
          ) : null}
          <div ref={wrapRef} style={css('position: relative; width: 100%; aspect-ratio: 600 / 440;')}>
            {stageEl}
          </div>
          {controls ? (
            <>
              <div style={css('display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px;')}>
                {steps.map((stp) => (
                  <button key={stp.key} type="button" onClick={stp.go} aria-pressed={stp.sel} style={css(stp.style)}>
                    <span style={css(stp.bar)} />
                    <span style={css('display: flex; gap: 6px; align-items: baseline;')}>
                      <span style={css('font-family: var(--font-mono); font-size: 11px; opacity: 0.7;')}>{stp.n}</span>
                      <span>{stp.label}</span>
                    </span>
                  </button>
                ))}
              </div>
              <div style={css('display: flex; flex-direction: column; gap: 4px; min-height: 44px;')}>
                <span style={css('font-size: 15px; font-weight: 500; line-height: 1.4; letter-spacing: -0.01em; color: #f2f0ec; text-wrap: pretty;')}>{caption}</span>
                <span style={css('font-family: var(--font-mono); font-size: 11px; color: #b4b2ac;')}>{sub}</span>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
