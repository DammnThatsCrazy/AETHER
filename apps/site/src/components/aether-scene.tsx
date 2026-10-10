/**
 * Built from design/designs/Aether Scene.dc.html: the signature
 * disconnected → connected diagram. Three stories (customer, agent, value),
 * four stages each (fragmented, connected, history, lens). Story data, copy
 * and styles are verbatim from the design.
 */
import { createElement as h, useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { css, useDesignState, useReducedMotion } from '@site/design/runtime';
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
      ['jane', 'center', 'Aether profile', 'prf_7k2m', 'Jane Smith', [300, 220], null, null, true],
      ['ad', 'system', 'Google Ads', 'clk_88f1', 'Ad impression', [110, 100], '18% credit', '09:01'],
      ['web', 'system', 'Web SDK', 'anon_941', 'Website visit', [300, 64], '27% credit', '09:04'],
      ['app', 'system', 'iOS SDK', 'dev_ios_2c9', 'Mobile app', [490, 100], null, '09:15'],
      ['email', 'system', 'Klaviyo', 'evt_311', 'Email interaction', [505, 252], '31% credit', '11:43'],
      ['agent', 'agent', 'Support agent', 'session_381', 'Agent conversation', [400, 372], '24% credit', '14:22'],
      ['buy', 'value', 'Stripe', 'cus_3321', 'Purchase · $149', [200, 372], '$149', '16:08'],
      ['support', 'system', 'Zendesk', 'tkt_5521', 'Support interaction', [95, 252], null, '17:30'],
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
      ['person', 'human', 'HubSpot', 'ct_10293', 'Jane Smith', [300, 226], null, 'Mar 10'],
      ['order', 'system', 'Shopify', 'ord_5532', 'Order #5532', [100, 226], null, 'Mar 10'],
      ['val', 'center', 'Stripe', 'ch_3Nf2', '$149 revenue', [300, 370], '100% attributed', 'Mar 11'],
    ],
    conn: [['ref', 'camp'], ['camp', 'email'], ['email', 'journey'], ['journey', 'person'], ['person', 'order'], ['order', 'val'], ['ref', 'person', 1]],
    seq: ['ref', 'camp', 'email', 'journey', 'person', 'order', 'val'],
  },
};

const STORY_ORDER: StoryKey[] = ['customer', 'agent', 'value'];
const KG: Record<Kind, string> = { human: '●', agent: '⬡', system: '○', value: '↑', org: '◈', center: '●' };
const FR: [number, number][] = [[104, 92], [300, 70], [496, 100], [112, 226], [488, 232], [118, 356], [300, 374], [490, 354]];
const CAPS = ['Your systems know pieces of the story.', 'Aether understands how those pieces belong together.', 'Then turns activity into history and journeys.', 'Explore the same reality from any perspective.'];

export interface AetherSceneProps {
  story?: string;
  /** Fixed stage (0–3); when set, autoplay does not advance. */
  stage?: number | string | null;
  autoplay?: boolean;
  /** Cycle stories at the end of each run. */
  rotate?: boolean;
  controls?: boolean;
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
    }, props.interval ?? 2800);
    return () => clearInterval(timer);
  }, [props.autoplay, props.interval, reduce, setState]);

  const dark = !!props.dark;
  const storyKey = state.story ?? props.story ?? 'customer';
  const st: StoryKey = isStory(storyKey) ? storyKey : 'customer';
  const S = SCENE_STORIES[st];
  const stage = props.stage != null && props.stage !== '' ? Number(props.stage) : state.stage ?? list[0] ?? 0;
  const P = dark
    ? { card: '#1a1a1e', stroke: '#2a2a2f', fg: '#e8e6e1', sub: '#a09f99', edge: '#4a4a52', cFill: '#e8e6e1', cFg: '#1a1a1e', cSub: '#6b6a65', tagFg: '#111114' }
    : { card: '#fbfaf8', stroke: '#d8d6d0', fg: '#1a1a1e', sub: '#6b6a65', edge: '#b9b7b0', cFill: '#1a1a1e', cFg: '#e8e6e1', cSub: '#a09f99', tagFg: '#f5f4f1' };
  const KC: Record<Kind, string> = dark
    ? { human: '#9fbad6', agent: '#dcb683', system: '#8fb0cc', value: '#9cc4a9', org: '#c9b088', center: '#9fbad6' }
    : { human: '#3a6896', agent: '#a8783e', system: '#5a85a8', value: '#4f8466', org: '#7d6538', center: '#3a6896' };

  let fi = 0;
  const nodes: SceneNode[] = S.nodes.map(([id, kind, sys, raw, label, conn, tag, t, hideFrag]) => {
    const frag: [number, number] = hideFrag ? [300, 220] : FR[fi++] ?? [300, 220];
    const k = S.seq.indexOf(id);
    const time: [number, number] = k < 0 ? [300, 96] : [72 + k * 76, k % 2 ? 336 : 238];
    return { id, kind, sys, raw, label, conn, tag, t, hideFrag, frag, time };
  });
  const pos = (n: SceneNode) => (stage === 0 ? n.frag : stage === 2 ? n.time : n.conn);
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
    const d = 'M' + A[0] + ' ' + A[1] + 'L' + B[0] + ' ' + B[1];
    const delay = 220 + i * 45;
    const stroke = hi ? (dark ? '#dcb683' : '#a8783e') : P.edge;
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
    if (!reduce && !dashed && !dim && i < 5) {
      kids.push(
        h(
          'circle',
          { key: 'c', r: 2.6, fill: hi ? stroke : KC.human, opacity: 0 },
          h('animateMotion', { dur: '2.8s', begin: 0.6 + i * 0.55 + 's', repeatCount: 'indefinite', path: d }),
          h('animate', { attributeName: 'opacity', values: '0;0.9;0.9;0', keyTimes: '0;0.15;0.85;1', dur: '2.8s', begin: 0.6 + i * 0.55 + 's', repeatCount: 'indefinite' }),
        ),
      );
    }
    return h('g', { key: st + stage + 'e' + i, opacity: dim ? 0.16 : 1, style: { transition: 'opacity 200ms ' + ease } }, kids);
  });
  const nodeEls = nodes.map((n, i) => {
    const [x, y] = pos(n);
    const isC = n.kind === 'center';
    const w = isC ? 158 : 136;
    const hh = isC ? 54 : 46;
    const hidden = stage === 0 && n.hideFrag;
    const dim = lensOn && !n.tag && n.kind !== 'center';
    const fill = isC ? P.cFill : P.card;
    const fg = isC ? P.cFg : P.fg;
    const sub = isC ? P.cSub : P.sub;
    const acc = KC[n.kind];
    const title = stage === 0 ? n.sys : n.label;
    const kids: ReactNode[] = [
      h('rect', { key: 'r', width: w, height: hh, rx: 6, fill, stroke: isC ? fill : lensOn && n.tag ? acc : P.stroke, strokeWidth: 1 }),
      h('text', { key: 'g', x: 12, y: hh / 2 + 4, fill: isC ? (dark ? '#3a6896' : '#9fbad6') : acc, style: { fontFamily: 'var(--font-mono)', fontSize: 12 } }, KG[n.kind]),
      h('text', { key: 't', x: 28, y: isC ? 23 : 20, fill: fg, style: { fontFamily: 'var(--font-sans)', fontSize: isC ? 14 : 12, fontWeight: 500, letterSpacing: '-0.01em' } }, title),
      h('text', { key: 's', x: 28, y: isC ? 40 : 35, fill: sub, style: { fontFamily: 'var(--font-mono)', fontSize: 10 } }, n.raw),
    ];
    if (stage === 0 && !isC) kids.push(h('rect', { key: 'x', x: w - 16, y: 8, width: 6, height: 6, rx: 3, fill: P.edge }));
    if (stage === 2 && n.t) kids.push(h('text', { key: 'tm', x: 0, y: -7, fill: sub, style: { fontFamily: 'var(--font-mono)', fontSize: 10 } }, n.t));
    if (lensOn && n.tag) {
      const tw = n.tag.length * 6.1 + 16;
      kids.push(
        h(
          'g',
          { key: 'tag', transform: 'translate(' + (w / 2 - tw / 2) + ',' + (hh + 5) + ')', style: { animation: 'aeFade 200ms ' + ease + ' 200ms both' } },
          h('rect', { width: tw, height: 18, rx: 9, fill: dark ? '#dcb683' : '#8a6433' }),
          h('text', { x: tw / 2, y: 12.5, textAnchor: 'middle', fill: P.tagFg, style: { fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 500 } }, n.tag),
        ),
      );
    }
    return h(
      'g',
      {
        key: st + n.id,
        style: {
          transform: 'translate(' + (x - w / 2) + 'px,' + (y - hh / 2) + 'px)',
          opacity: hidden ? 0 : dim ? 0.3 : 1,
          transition: 'transform 320ms ' + ease + ' ' + i * 18 + 'ms, opacity 200ms ' + ease,
        },
      },
      kids,
    );
  });
  const axis = stage === 2 ? h('line', { key: 'ax', x1: 40, y1: 287, x2: 560, y2: 287, stroke: P.stroke, strokeWidth: 1, style: { animation: 'aeFade 320ms ' + ease + ' both' } }) : null;
  const svg = h(
    'svg',
    {
      viewBox: '0 0 600 440',
      width: '100%',
      height: '100%',
      role: 'img',
      'aria-label': S.label + ' scenario, ' + ['fragmented', 'connected', 'history', S.lens][stage] + ' view',
      style: { display: 'block', overflow: 'visible', position: 'absolute', inset: 0 },
    },
    axis,
    h('g', { key: 'E' }, edgeEls),
    h('g', { key: 'N' }, nodeEls),
  );
  const hold = (patch: { story?: StoryKey; stage?: number }) => setState({ hold: true, ...patch });
  const names = ['Fragmented', 'Connected', 'History', S.lens];
  const acc = dark ? '#e8e6e1' : '#1a1a1e';
  const controls = !!props.controls;
  const tabsWrap =
    'display: flex; gap: 4px; padding: 3px; border-radius: 10px; background: ' + (dark ? '#111114' : '#eceae5') + '; border: 1px solid ' + (dark ? '#2a2a2f' : '#d8d6d0') + ';';
  const stories = STORY_ORDER.map((k) => {
    const on = k === st;
    return {
      key: k,
      label: SCENE_STORIES[k].label,
      g: SCENE_STORIES[k].g,
      sel: on,
      go: () => hold({ story: k, stage: 1 }),
      style:
        'font-family: inherit; display: inline-flex; gap: 6px; align-items: center; min-height: 32px; padding: 0 12px; border-radius: 7px; border: 0; cursor: pointer; font-size: 12px; font-weight: 500; transition: background-color 120ms ' +
        ease +
        ', color 120ms ' +
        ease +
        '; ' +
        (on ? 'background: ' + acc + '; color: ' + (dark ? '#1a1a1e' : '#f5f4f1') + ';' : 'background: transparent; color: ' + (dark ? '#a09f99' : '#6b6a65') + ';'),
    };
  });
  const liveLabel = state.hold ? 'paused · synthetic example' : 'synthetic example';
  const liveStyle = 'display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: 11px; color: ' + (dark ? '#a09f99' : '#6b6a65') + ';';
  const liveDot = 'width: 6px; height: 6px; border-radius: 999px; background: ' + (state.hold ? '#9c9b95' : '#6b9a7c') + ';';
  const steps = list.map((k, i) => {
    const on = k === stage;
    return {
      key: k,
      n: '0' + (i + 1),
      label: names[k],
      sel: on,
      go: () => hold({ stage: k }),
      bar: 'height: 2px; border-radius: 2px; width: 100%; background: ' + (on ? acc : dark ? '#2a2a2f' : '#d8d6d0') + '; transition: background-color 200ms ' + ease + ';',
      style:
        'font-family: inherit; text-align: left; display: flex; flex-direction: column; gap: 8px; padding: 0 0 4px; background: transparent; border: 0; cursor: pointer; font-size: 12px; font-weight: 500; color: ' +
        (on ? acc : dark ? '#a09f99' : '#6b6a65') +
        '; transition: color 120ms ' +
        ease +
        ';',
    };
  });
  const caption = stage === 3 ? S.close : CAPS[stage];
  const sub = S.subs[stage as 0 | 1 | 2 | 3];
  const capStyle = 'font-size: 15px; font-weight: 500; line-height: 1.4; letter-spacing: -0.01em; color: ' + acc + '; text-wrap: pretty;';
  const subStyle = 'font-family: var(--font-mono); font-size: 11px; color: ' + (dark ? '#a09f99' : '#6b6a65') + ';';

  return (
    <div className="dc pg-aether-scene" style={props.style}>
      <div style={css('display: flex; flex-direction: column; gap: 14px; width: 100%; font-family: var(--font-sans);')}>
        {controls ? (
          <div style={css('display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px;')}>
            <div role="tablist" aria-label="Scenario" style={css(tabsWrap)}>
              {stories.map((s) => (
                <button key={s.key} type="button" role="tab" aria-selected={s.sel} onClick={s.go} style={css(s.style)}>
                  <span aria-hidden="true" style={css('font-family: var(--font-mono);')}>
                    {s.g}
                  </span>
                  {s.label}
                </button>
              ))}
            </div>
            <span style={css(liveStyle)}>
              <span style={css(liveDot)} />
              {liveLabel}
            </span>
          </div>
        ) : null}
        <div style={css('position: relative; width: 100%; aspect-ratio: 600 / 440;')}>{svg}</div>
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
              <span style={css(capStyle)}>{caption}</span>
              <span style={css(subStyle)}>{sub}</span>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
