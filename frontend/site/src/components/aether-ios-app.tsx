/**
 * Built from design/designs/Aether iOS App.dc.html (copy, layout and styles verbatim).
 *
 * The native-feeling Aether app Aether Home shows inside the iPhone frame:
 * large title that collapses into a frosted nav bar, grouped lists, segmented
 * controls, a push detail screen with an edge-swipe back gesture, an action
 * sheet, toasts and a floating glass tab bar. All data is synthetic.
 */
import { Fragment, useEffect, useRef, type PointerEvent as ReactPointerEvent, type UIEvent } from 'react';
import { asset, css, hoverClass, useDesignState } from '@site/design/runtime';
import './aether-ios-app.css';

type Tab = 'overview' | 'rels' | 'journeys' | 'risk' | 'value';
type Filter = 'all' | 'humans' | 'agents' | 'syndicates';
type Journey = 'ig' | 'x';
type Decision = 'approved' | 'declined' | null;

type State = {
  tab: Tab;
  filter: Filter;
  push: string | null;
  entered: boolean;
  drag: number;
  dragging: boolean;
  j: Journey;
  sheet: boolean;
  sheetIn: boolean;
  decision: Decision;
  watch: boolean;
  p: number;
  toast: string;
};

type Act = { g: string; x: string; t: string; gStyle: string; style: string };
type Rel = {
  key: string; g: string; name: string; id: string; role: string; kind: string; type: Exclude<Filter, 'all'>;
  c: string; risk: number; desc: string; facts: string[]; actions?: Act[]; members?: [string, string, string][];
};
type Row = {
  title: string; sub: string; hasSub: boolean; trail: string; chev: boolean; isLogo: boolean; isGlyph: boolean;
  logo: string; g: string; gStyle: string; hasBar: boolean; bar: string; go: () => void; trailStyle: string; style?: string;
};

const E = 'cubic-bezier(0.22,1,0.36,1)';
const TINT = '#6ea0ff';
const SEC = 'rgba(235,235,245,0.6)';
const B = (k: string) => asset('assets/brand/' + (k === 'x' ? 'x-dark' : k) + '.svg');
const GLASS = 'flex-shrink: 0; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.13); border-radius: 20px; overflow: hidden; -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); box-shadow: inset 0 1px 0 rgba(255,255,255,0.14); box-sizing: border-box;';
const AG = { Ptolemy: '#3a6896', Kierkegaard: '#5a85a8', Mordred: '#c9975a' };
const act = (g: string, c: string, x: string, t: string): Act => ({ g, x, t, gStyle: 'font-family: var(--font-mono); width: 18px; text-align: center; color: ' + c + ';', style: 'display: flex; align-items: baseline; gap: 10px; padding: 12px 14px; border-top: 0.5px solid rgba(255,255,255,0.1);' });
const R: Rel[] = [
  { key: 'ptolemy', g: '⬡', name: 'Ptolemy', id: 'agt_2f18e', role: 'delegated agent', kind: 'H→A', type: 'agents', c: AG.Ptolemy, risk: 28, desc: 'Scores incoming supplier applications for Sofia and flags exceptions to Osiris.', facts: ['42 actions/day', 'strength 0.90', 'scope: scoring.read'],
    actions: [act('✓', '#8fc7a2', 'Scored application app_71c · 0.82', '1h'), act('→', '#9fbad6', 'Flagged exception to Osiris', '5h'), act('✓', '#8fc7a2', 'Onboarded supplier to SF syndicate', '2d')] },
  { key: 'kierkegaard', g: '⬡', name: 'Kierkegaard', id: 'agt_5c02f', role: 'delegated agent', kind: 'H→A', type: 'agents', c: AG.Kierkegaard, risk: 31, desc: 'Audits cross-border settlement records for irregularities.', facts: ['9 actions/day', '$1.8K value', 'strength 0.82'],
    actions: [act('◉', '#d9b878', 'Audited Stripe payout po_9x2 · clean', '3h'), act('✓', '#8fc7a2', 'Reconciled 14 settlements', '1d')] },
  { key: 'mordred', g: '⬡', name: 'Mordred', id: 'agt_88ce1', role: 'flagged relationship', kind: 'A→A', type: 'agents', c: AG.Mordred, risk: 91, desc: 'Unusual messages with an outside payments agent in a flagged group. Passed to Percival.', facts: ['conf 0.88', '212 messages', 'strength 0.68'],
    actions: [act('↔', '#e0b878', 'Messaged external agent in syn_dxb4 ×212', '6h'), act('▲', '#f08a7c', 'Escalated pattern to Percival', '6h'), act('■', '#f08a7c', 'Percival paused the next payment batch · seen', 'now')] },
  { key: 'percival', g: '●', name: 'Percival', id: 'usr_91b2c', role: 'risk analyst', kind: 'H→H', type: 'humans', c: '#6b9a7c', risk: 12, desc: 'Approves payment batches together with Sofia. Receives Mordred’s alerts.', facts: ['14 shared approvals', 'slack · crm', 'strength 0.74'] },
  { key: 'osiris', g: '●', name: 'Osiris', id: 'usr_c33a0', role: 'compliance', kind: 'H→H', type: 'humans', c: '#6b9a7c', risk: 18, desc: 'Reviews rule exceptions raised by Ptolemy.', facts: ['6 reviews', 'strength 0.52'] },
  { key: 'maya', g: '●', name: 'Maya Chen', id: 'usr_a81d3', role: 'referred by Sofia', kind: 'H→H', type: 'humans', c: '#6b9a7c', risk: 9, desc: 'Joined through Sofia’s referral link on X. Now a repeat buyer.', facts: ['referral', '$2.1K value', '3 orders'] },
  { key: 'supplier', g: '◈', name: 'SF supplier syndicate', id: 'syn_sf01', role: '5 humans · 2 agents', kind: 'cluster', type: 'syndicates', c: '#a88a5a', risk: 36, desc: 'Supplier network handled through Ptolemy. Most common path: sourced → contracted → active.', facts: ['$14.6K value', '11 journeys'],
    members: [['●', 'Sofia Marchetti', '#6b9a7c'], ['●', 'Osiris', '#6b9a7c'], ['●', '+3 suppliers', '#6b9a7c'], ['⬡', 'Ptolemy', AG.Ptolemy], ['⬡', 'Kierkegaard', AG.Kierkegaard]] },
  { key: 'settlement', g: '◈', name: 'Settlement syndicate', id: 'syn_dxb4', role: '2 humans · 3 agents', kind: 'cluster', type: 'syndicates', c: '#d9695a', risk: 84, desc: 'Flagged group in Dubai. Mordred messages one of its agents.', facts: ['flagged', '2 hops from Sofia'],
    members: [['●', '2 unknown humans', '#a09f99'], ['⬡', 'agt_x41 (external)', '#d9695a'], ['⬡', '+2 agents', '#d9695a']] },
];
const riskC = (n: number) => (n >= 80 ? '#f08a7c' : n >= 50 ? '#f0c995' : '#8fc7a2');
type Step = [label: string, src: string, n: number, rate: string, d: string];
const J: Record<Journey, { label: string; name: string; campaign: string; status: string; c: string; kpis: [string, string, string][]; steps: Step[]; meta: string }> = {
  ig: { label: 'Instagram', name: 'Paid social → first purchase', campaign: 'campaign:cmp_spring26 · Instagram', status: '● converted', c: '#8fc7a2',
    kpis: [['$38.20', 'CAC', '#b3dcc0'], ['5.3%', 'click → buy', '#a9c4e0'], ['3.4×', 'ROAS', '#f0c995'], ['$2,330', 'spend', '#fff']],
    steps: [['Reel impression', 'instagram', 48200, '100%', 'Mar 9'], ['Link click', 'instagram', 1157, '2.4%', 'Mar 9'], ['Product view', 'shopify', 812, '70.2%', 'Mar 9'], ['Add to cart', 'shopify', 204, '25.1%', 'Mar 10'], ['Checkout started', 'stripe', 96, '47.1%', 'Mar 12'], ['Paid · $4,200', 'stripe', 61, '63.5%', 'Mar 12']],
    meta: 'journey:jrn_ig_01 · attribution 0.34 to campaign' },
  x: { label: 'X referral', name: 'Creator post → subscription', campaign: 'campaign:cmp_creator_x · referral thread', status: '▲ renewal at risk', c: '#f0c995',
    kpis: [['$52.10', 'CAC', '#b3dcc0'], ['3.1%', 'visit → paid', '#a9c4e0'], ['$18.4K', 'LTV', '#f0c995'], ['353×', 'LTV / CAC', '#fff']],
    steps: [['Creator post', 'x', 22400, '100%', 'Feb 2'], ['Landing visit', 'x', 1840, '8.2%', 'Feb 2'], ['Lead captured', 'hubspot', 410, '22.3%', 'Feb 3'], ['Nurture email opened', 'hubspot', 236, '57.6%', 'Feb 6'], ['Demo booked', 'hubspot', 92, '39.0%', 'Feb 9'], ['Subscribed · Beta', 'stripe', 57, '62.0%', 'Feb 14']],
    meta: 'journey:jrn_x_02 · referral edge → Maya Chen' },
};
const TITLES: Record<Tab, string> = { overview: 'Sofia Marchetti', rels: 'Relationships', journeys: 'Journeys', risk: 'Risk', value: 'Value' };
const TB: [Tab, string, string][] = [['overview', '◈', 'Overview'], ['rels', '↔', 'People'], ['journeys', '→', 'Journeys'], ['risk', '▲', 'Risk'], ['value', '↑', 'Value']];
const ROW_BASE = 'font-family: inherit; color: #fff; width: 100%; display: flex; align-items: center; gap: 12px; min-height: 56px; padding: 10px 14px; box-sizing: border-box; background: transparent; border: 0; cursor: pointer; transition: background-color 120ms ' + E + ';';
const segStyle = (on: boolean) => 'flex: 1; font-family: inherit; min-height: 30px; border: 0; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background-color 200ms ' + E + ', color 120ms ' + E + '; ' + (on ? 'background: rgba(255,255,255,0.94); color: #111114;' : 'background: transparent; color: #fff;');

const ACTIVE_TILE = hoverClass('background: rgba(255,255,255,0.16);', 'active');
const ACTIVE_ROW = hoverClass('background: rgba(255,255,255,0.14);', 'active');
const ACTIVE_SHEET = hoverClass('background: rgba(255,255,255,0.12);', 'active');

export function AetherIosApp() {
  const [s, setState] = useDesignState<State>({ tab: 'overview', filter: 'all', push: null, entered: false, drag: 0, dragging: false, j: 'ig', sheet: false, sheetIn: false, decision: null, watch: false, p: 0, toast: '' });
  const scrollRef = useRef<HTMLDivElement>(null);
  const tt = useRef<ReturnType<typeof setTimeout>>(undefined);
  const pt = useRef<ReturnType<typeof setTimeout>>(undefined);
  const dx0 = useRef(0);
  useEffect(() => () => { clearTimeout(tt.current); clearTimeout(pt.current); }, []);

  const say = (x: string) => { clearTimeout(tt.current); setState({ toast: x }); tt.current = setTimeout(() => setState({ toast: '' }), 2200); };
  const setTab = (k: Tab) => { setState({ tab: k, p: 0 }); const el = scrollRef.current; if (el) el.scrollTop = 0; };
  const open = (key: string) => { setState({ push: key, entered: false, drag: 0, dragging: false }); clearTimeout(pt.current); pt.current = setTimeout(() => setState({ entered: true }), 30); };
  const close = () => { setState({ entered: false, dragging: false, drag: 0 }); clearTimeout(pt.current); pt.current = setTimeout(() => setState({ push: null }), 320); };
  const openSheet = () => { setState({ sheet: true, sheetIn: false }); setTimeout(() => setState({ sheetIn: true }), 30); };
  const closeSheet = (patch?: Partial<State>) => { setState({ sheetIn: false }); setTimeout(() => setState({ sheet: false, ...(patch ?? {}) }), 320); };

  const jr = J[s.j] ?? J.ig;
  const jmax = jr.steps[0]![2];
  const tab = s.tab;
  const rw = (o: Partial<Row>): Row => ({ title: '', sub: '', trail: '', chev: false, isLogo: false, isGlyph: false, logo: '', g: '', gStyle: '', hasBar: false, bar: '', go: () => {}, trailStyle: 'font-size: 15px; color: ' + SEC + '; white-space: nowrap;', ...o, hasSub: !!o.sub });
  const glyph = (g: string, bg: string): Partial<Row> => ({ isGlyph: true, g, gStyle: 'width: 32px; height: 32px; border-radius: ' + (g === '●' ? '999px' : '9px') + '; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 14px; color: #0b0b0e; background: ' + bg + ';' });
  const logoRow = (k: string, o: Partial<Row>) => rw({ isLogo: true, logo: B(k), ...o });

  let groups: { header: string; rows: Row[] }[] = [];
  let segs: { label: string; sel: boolean; go: () => void; style: string }[] = [];
  let tiles: [string, string, string, Tab | null][] = [];
  let foot = '';
  let cols = 4;
  if (tab === 'overview') {
    groups = [
      { header: 'Connected accounts', rows: ([['stripe', 'Stripe', 'cus_Q8…4f'], ['hubspot', 'HubSpot', 'contact 9812'], ['x', 'X', '@sofia.marchetti'], ['instagram', 'Instagram', '@sofia.makes'], ['phantom', 'Phantom', '7xKX…9fQm'], ['shopify', 'Shopify', '3 orders']] as const).map(([k, n, h]) => logoRow(k, { title: n, trail: h, trailStyle: 'font-family: var(--font-mono); font-size: 12px; color: ' + SEC + ';', chev: true, go: () => say('↔ ' + n + ' · ' + h) })) },
      { header: 'Recent evidence', rows: [
        logoRow('stripe', { title: 'invoice.paid · $4,200', sub: 'stripe', trail: '2h' }),
        rw({ ...glyph('⬡', AG.Mordred), title: 'Mordred ↔ syn_dxb4', sub: '212 messages', trail: '6h' }),
        rw({ ...glyph('⬡', AG.Ptolemy), title: 'Ptolemy scored app_71c', sub: '0.82', trail: '1h' }),
        logoRow('instagram', { title: 'Reel click', sub: 'cmp_spring26', trail: '1d' }),
        logoRow('hubspot', { title: 'Lifecycle → customer', sub: 'hubspot', trail: '2d' }),
        rw({ ...glyph('✓', '#9fbad6'), title: 'Approval · batch_0912', sub: 'Percival', trail: '3d' }),
      ] }];
    tiles = [['$18.4K', 'value', '#b3dcc0', 'rels'], ['8', 'relationships', '#a9c4e0', 'rels'], ['3', 'agents', '#f0c995', 'rels'], ['2', 'journeys', '#d9b878', 'journeys']];
  } else if (tab === 'rels') {
    const F: Filter[] = ['all', 'humans', 'agents', 'syndicates'];
    const LB: Record<Filter, string> = { all: 'All', humans: 'People', agents: 'Agents', syndicates: 'Groups' };
    segs = F.map((f) => ({ label: LB[f], sel: s.filter === f, go: () => setState({ filter: f }), style: segStyle(s.filter === f) }));
    const shown = R.filter((r) => s.filter === 'all' || r.type === s.filter);
    groups = [{ header: shown.length + ' connected', rows: shown.map((r) => rw({ ...glyph(r.g, r.c), title: r.name, sub: r.id + ' · ' + r.role, trail: 'risk ' + r.risk, trailStyle: 'font-family: var(--font-mono); font-size: 12px; white-space: nowrap; color: ' + riskC(r.risk) + ';', chev: true, go: () => open(r.key) })) }];
  } else if (tab === 'journeys') {
    segs = (Object.keys(J) as Journey[]).map((k) => ({ label: J[k].label, sel: s.j === k, go: () => setState({ j: k }), style: segStyle(s.j === k) }));
    tiles = jr.kpis.map(([v, k, c]) => [v, k, c, null]);
    cols = 4;
    groups = [{ header: 'Funnel', rows: jr.steps.map(([label, src, n, rate, d], i) => logoRow(src, { title: label, trail: n.toLocaleString('en-US'), trailStyle: 'font-family: var(--font-mono); font-size: 12px; color: #fff;', hasBar: true, bar: 'display: block; height: 100%; border-radius: 999px; width: ' + Math.max(3, Math.sqrt(n / jmax) * 100) + '%; background: ' + ['#3a6896', '#5a85a8', '#6b9a7c', '#a88a5a', '#c9975a', '#6b9a7c'][i] + ';', sub: rate + ' · ' + d })) }];
    foot = jr.meta;
  } else if (tab === 'risk') {
    groups = [{ header: 'What drives it', rows: ([['Agent Mordred is two steps from a flagged group', '+31', '#f08a7c'], ['Cross-border payments up 3.1× in speed', '+18', '#f0c995'], ['New counterparty in 7 days', '+9', '#f0c995'], ['Verified identity across 6 sources', '−12', '#8fc7a2']] as const).map(([x, v, c]) => rw({ title: x, trail: v, trailStyle: 'font-family: var(--font-mono); font-size: 14px; color: ' + c + ';' })) }];
  } else {
    tiles = [['$18,420', 'lifetime', '#b3dcc0', null], ['$14.6K', 'syndicate', '#a9c4e0', null], ['$1.8K', 'agent-sourced', '#f0c995', null]];
    cols = 3;
    groups = [{ header: 'What led to the sale', rows: ([['instagram', 'Instagram', 0.34, '#E4405F'], ['x', 'X referral', 0.26, '#9fbad6'], ['hubspot', 'HubSpot', 0.22, '#FF7A59'], ['shopify', 'Shopify', 0.18, '#6b9a7c']] as const).map(([k, n, w, c]) => logoRow(k, { title: n, trail: w.toFixed(2), trailStyle: 'font-family: var(--font-mono); font-size: 12px;', hasBar: true, bar: 'display: block; height: 100%; border-radius: 999px; width: ' + Math.min(100, w * 250) + '%; background: ' + c + ';' })) }];
    foot = 'worked out by Aether · attribution 0.34 to campaign';
  }
  groups = groups.map((g) => ({ header: g.header, rows: g.rows.map((r, i) => ({ ...r, style: ROW_BASE + (i ? ' border-top: 0.5px solid rgba(255,255,255,0.1);' : '') })) }));

  const decided = s.decision;
  const dr = R.find((r) => r.key === s.push);
  const d = dr
    ? { name: dr.name, id: dr.id, role: dr.role, g: dr.g, desc: dr.desc, facts: dr.facts, risk: 'risk ' + dr.risk, riskStyle: 'font-family: var(--font-mono); font-size: 12px; color: ' + riskC(dr.risk) + ';',
        avStyle: 'width: 64px; height: 64px; flex-shrink: 0; border-radius: ' + (dr.g === '●' ? '999px' : '18px') + '; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 26px; color: #0b0b0e; background: ' + dr.c + ';',
        hasActions: !!dr.actions, actions: dr.actions ?? [], hasMembers: !!dr.members,
        members: (dr.members ?? []).map(([g, n, c]) => ({ g, n, style: 'font-size: 13px; padding: 6px 12px; border-radius: 999px; background: rgba(255,255,255,0.08); border: 1px solid ' + c + '99; font-family: var(--font-mono);' })) }
    : null;
  const drag = s.dragging ? s.drag : 0;
  const p = s.p;
  const tOverview = tab === 'overview';

  const underStyle = 'position: absolute; inset: 0; transform: translateX(' + (s.push && s.entered ? -90 + drag * 0.22 : 0) + 'px); opacity: ' + (s.push && s.entered ? 0.55 : 1) + '; transition: ' + (s.dragging ? 'none' : 'transform 320ms ' + E + ', opacity 320ms ' + E) + ';';
  const onScroll = (e: UIEvent<HTMLDivElement>) => { const v = Math.round(Math.max(0, Math.min(1, (e.currentTarget.scrollTop - 8) / 36)) * 10) / 10; if (v !== s.p) setState({ p: v }); };
  const toTop = () => { const el = scrollRef.current; if (el?.scrollTo) el.scrollTo({ top: 0, behavior: 'smooth' }); };
  const barStyle = 'position: absolute; left: 0; right: 0; top: 0; height: 98px; opacity: ' + p + '; pointer-events: ' + (p > 0.5 ? 'auto' : 'none') + '; background: rgba(11,11,14,0.6); -webkit-backdrop-filter: blur(24px) saturate(1.5); backdrop-filter: blur(24px) saturate(1.5); border-bottom: 0.5px solid rgba(255,255,255,0.14); transition: opacity 120ms ' + E + ';';
  const actions = [
    { g: '↔', label: 'Graph', go: () => setTab('rels') },
    { g: s.watch ? '●' : '○', label: s.watch ? 'Watching' : 'Watch', go: () => { setState({ watch: !s.watch }); say(s.watch ? '○ Stopped watching Sofia Marchetti' : '● Watching Sofia Marchetti · alerts on new risk'); } },
    { g: '⇩', label: 'Export', go: () => say('⇩ Export queued · usr_4f21a9.jsonl') },
  ];
  const actionStyle = 'font-family: inherit; color: #fff; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 12px 6px; border-radius: 16px; cursor: pointer; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.13); transition: background-color 120ms ' + E + ';';
  const tilesGrid = GLASS + ' display: grid; grid-template-columns: repeat(' + (tOverview ? 4 : cols) + ', minmax(0, 1fr));';
  const tileList = tiles.map(([v, k, c, to], i) => ({ v, k, go: () => { if (to) setTab(to); }, vStyle: 'font-size: 19px; font-weight: 600; letter-spacing: -0.4px; color: ' + c + ';', style: 'font-family: inherit; color: #fff; display: flex; flex-direction: column; align-items: flex-start; gap: 3px; padding: 12px; background: transparent; border: 0; cursor: pointer; ' + (i ? 'border-left: 0.5px solid rgba(255,255,255,0.1);' : '') + ' transition: background-color 120ms ' + E + ';' }));
  const decision = decided === 'approved' ? '✓ Reviewed by you · just now' : decided === 'declined' ? '⚑ Flagged for follow-up' : '';
  const decisionStyle = 'font-size: 14px; font-weight: 600; color: ' + (decided === 'approved' ? '#b3dcc0' : '#f0c995') + ';';
  const tabs = TB.map(([k, g, label]) => ({ g, label, sel: tab === k, go: () => setTab(k),
    style: 'font-family: inherit; flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 7px 0; border: 0; border-radius: 999px; cursor: pointer; transition: background-color 200ms ' + E + ', color 120ms ' + E + '; background: ' + (tab === k ? 'rgba(255,255,255,0.94)' : 'transparent') + '; color: ' + (tab === k ? '#111114' : '#d1d1d6') + ';' }));
  const pushStyle = 'position: absolute; inset: 0; z-index: 20; touch-action: pan-y; background: radial-gradient(120% 45% at 100% 0%, rgba(58,104,150,0.55), transparent 62%), radial-gradient(90% 40% at 0% 52%, rgba(201,151,90,0.3), transparent 62%), #0b0b0e; box-shadow: -12px 0 32px rgba(0,0,0,0.35); transform: translateX(' + (s.entered ? drag : 402) + 'px); transition: ' + (s.dragging ? 'none' : 'transform 320ms ' + E) + ';';
  const dragDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (e.clientX - r.left < 36 * (r.width / 402)) {
      dx0.current = e.clientX;
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* capture is best effort */ }
      setState({ dragging: true, drag: 0 });
    }
  };
  const dragMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (s.dragging) setState({ drag: Math.max(0, (e.clientX - dx0.current) / (e.currentTarget.getBoundingClientRect().width / 402)) });
  };
  const dragUp = () => {
    if (!s.dragging) return;
    if (s.drag > 110) { setState({ dragging: false, entered: false }); clearTimeout(pt.current); pt.current = setTimeout(() => setState({ push: null, drag: 0 }), 320); }
    else setState({ dragging: false, drag: 0 });
  };
  const scrimStyle = 'position: absolute; inset: 0; background: rgba(0,0,0,0.5); opacity: ' + (s.sheetIn ? 1 : 0) + '; transition: opacity 200ms ' + E + ';';
  const sheetStyle = 'position: absolute; left: 10px; right: 10px; bottom: 30px; display: flex; flex-direction: column; gap: 8px; transform: translateY(' + (s.sheetIn ? 0 : 340) + 'px); transition: transform 320ms ' + E + ';';
  const sheetActions = ([['Mark reviewed', 'approved', '✓ Marked as reviewed', TINT], ['Flag for follow-up', 'declined', '⚑ Flagged for follow-up', '#f08a7c']] as const).map(([label, v, msg, c]) => ({ label, go: () => { closeSheet({ decision: v }); say(msg); }, style: 'font-family: inherit; width: 100%; min-height: 56px; border: 0; border-top: 0.5px solid rgba(255,255,255,0.14); background: transparent; color: ' + c + '; font-size: 20px; cursor: pointer; transition: background-color 120ms ' + E + ';' }));

  return (
    <div className="ax-app" style={css("position: relative; overflow: hidden; width: 100%; height: 874px; color: #fff; font-family: -apple-system, 'SF Pro Text', system-ui, sans-serif; -webkit-font-smoothing: antialiased; background: radial-gradient(120% 45% at 100% 0%, rgba(58,104,150,0.55), transparent 62%), radial-gradient(90% 40% at 0% 52%, rgba(201,151,90,0.3), transparent 62%), radial-gradient(100% 40% at 100% 100%, rgba(107,154,124,0.34), transparent 62%), #0b0b0e;")}>
      <div style={css(underStyle)}>
        <div ref={scrollRef} onScroll={onScroll} className="ax-scroll" style={css("position: absolute; inset: 0; overflow-y: auto; padding: 98px 16px 150px; box-sizing: border-box; display: flex; flex-direction: column; gap: 22px;")}>
          <div style={css("display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-top: -4px;")}>
            <span style={css("font-size: 34px; font-weight: 700; letter-spacing: 0.4px; line-height: 41px;")}>{TITLES[tab]}</span>
            {tOverview ? <span style={css("font-size: 12px; color: rgba(235,235,245,0.6);")}>{"synthetic"}</span> : null}
          </div>
          {segs.length > 0 ? (
            <div role="tablist" style={css("display: flex; padding: 2px; border-radius: 10px; background: rgba(118,118,128,0.28); border: 1px solid rgba(255,255,255,0.08);")}>
              {segs.map((sg) => (
                <button key={sg.label} type="button" role="tab" aria-selected={sg.sel} onClick={sg.go} style={css(sg.style)}>{sg.label}</button>
              ))}
            </div>
          ) : null}
          {tOverview ? (
            <>
              <div style={css(GLASS + " padding: 16px; display: flex; gap: 14px; align-items: center;")}>
                <span style={css("position: relative; width: 64px; height: 64px; flex-shrink: 0;")}>
                  <span style={css("width: 64px; height: 64px; border-radius: 999px; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 600; background: #3a6896; box-shadow: 0 0 0 3px rgba(94,148,255,0.3);")}>{"SM"}</span>
                  <span style={css("position: absolute; right: 0; bottom: 0; width: 16px; height: 16px; border-radius: 999px; background: #6b9a7c; border: 3px solid #1a1d24;")} />
                </span>
                <span style={css("display: flex; flex-direction: column; gap: 6px; min-width: 0;")}>
                  <span style={css("display: flex; gap: 6px; flex-wrap: wrap;")}>
                    <span style={css("font-size: 12px; font-weight: 600; padding: 3px 9px; border-radius: 999px; background: rgba(107,154,124,0.28); color: #b3dcc0;")}>{"VIP · Beta"}</span>
                    <span style={css("font-size: 12px; font-weight: 600; padding: 3px 9px; border-radius: 999px; background: rgba(201,151,90,0.28); color: #f0c995;")}>{"▲ risk 72"}</span>
                  </span>
                  <span style={css("font-family: var(--font-mono); font-size: 12px; color: rgba(235,235,245,0.7);")}>{"entity:usr_4f21a9"}</span>
                  <span style={css("font-size: 13px; color: rgba(235,235,245,0.6);")}>{"San Francisco, US · GMT-7"}</span>
                </span>
              </div>
              <div style={css("display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px;")}>
                {actions.map((a) => (
                  <button key={a.label} type="button" onClick={a.go} style={css(actionStyle)} className={ACTIVE_TILE}>
                    <span style={css("font-family: var(--font-mono); font-size: 22px; line-height: 26px; color: #6ea0ff;")}>{a.g}</span>
                    <span style={css("font-size: 12px; font-weight: 500;")}>{a.label}</span>
                  </button>
                ))}
              </div>
            </>
          ) : null}
          {tab === 'journeys' ? (
            <div style={css(GLASS + " padding: 16px; display: flex; flex-direction: column; gap: 4px;")}>
              <span style={css("display: flex; justify-content: space-between; align-items: baseline; gap: 8px;")}>
                <span style={css("font-size: 17px; font-weight: 600;")}>{jr.name}</span>
                <span style={css('font-size: 12px; font-weight: 600; white-space: nowrap; color: ' + jr.c + ';')}>{jr.status}</span>
              </span>
              <span style={css("font-family: var(--font-mono); font-size: 11px; color: rgba(235,235,245,0.6);")}>{jr.campaign}</span>
            </div>
          ) : null}
          {tab === 'risk' ? (
            <div style={css(GLASS + " padding: 18px 16px; display: flex; flex-direction: column; gap: 12px;")}>
              <span style={css("display: flex; align-items: baseline; gap: 10px;")}>
                <span style={css("font-size: 56px; font-weight: 700; letter-spacing: -1.5px; line-height: 1; color: #f0c995;")}>{"72"}</span>
                <span style={css("font-size: 15px; color: rgba(235,235,245,0.7);")}>{"elevated · worked out by Aether"}</span>
              </span>
              <span style={css("height: 8px; border-radius: 999px; background: rgba(255,255,255,0.12); overflow: hidden;")}>
                <span style={css("display: block; width: 72%; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #6b9a7c, #c9975a 60%, #d9695a);")} />
              </span>
            </div>
          ) : null}
          {tileList.length > 0 ? (
            <div style={css(tilesGrid)}>
              {tileList.map((ti) => (
                <button key={ti.k} type="button" onClick={ti.go} style={css(ti.style)} className={ACTIVE_TILE}>
                  <span style={css(ti.vStyle)}>{ti.v}</span>
                  <span style={css("font-size: 11px; color: rgba(235,235,245,0.62);")}>{ti.k}</span>
                </button>
              ))}
            </div>
          ) : null}
          {tOverview ? (
            <div style={css("border-radius: 20px; padding: 16px; display: flex; flex-direction: column; gap: 8px; background: rgba(201,151,90,0.16); border: 1px solid rgba(224,184,120,0.45); -webkit-backdrop-filter: blur(18px); backdrop-filter: blur(18px);")}>
              <span style={css("font-size: 12px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: #f0c995;")}>{"○ What the graph found"}</span>
              <span style={css("font-size: 15px; line-height: 1.45;")}>{"A top customer is two steps away from a flagged payment group, through an AI agent acting for her. No single tool shows this."}</span>
              <button type="button" onClick={() => setTab('risk')} style={css("font-family: inherit; align-self: flex-start; min-height: 36px; padding: 0 16px; border-radius: 999px; border: 0; background: #e0b878; color: #1a1a1e; font-size: 14px; font-weight: 600; cursor: pointer;")} className={hoverClass('background: #c9a068;', 'active')}>{"See why →"}</button>
            </div>
          ) : null}
          {groups.map((g) => (
            <div key={g.header} style={css("display: flex; flex-direction: column; gap: 8px;")}>
              <span style={css("font-size: 13px; letter-spacing: -0.08px; text-transform: uppercase; color: rgba(235,235,245,0.6); padding: 0 16px;")}>{g.header}</span>
              <div style={css(GLASS)}>
                {g.rows.map((r, rIndex) => (
                  <button key={rIndex} type="button" onClick={r.go} style={css(r.style)} className={ACTIVE_ROW}>
                    {r.isLogo ? (
                      <span style={css("width: 32px; height: 32px; border-radius: 8px; background: #f5f4f1; display: flex; align-items: center; justify-content: center; flex-shrink: 0;")}>
                        <img src={r.logo} alt="" style={css("width: 19px; height: 19px; object-fit: contain;")} />
                      </span>
                    ) : null}
                    {r.isGlyph ? <span style={css(r.gStyle)}>{r.g}</span> : null}
                    <span style={css("display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; text-align: left;")}>
                      <span style={css("font-size: 16px; line-height: 21px; letter-spacing: -0.3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;")}>{r.title}</span>
                      {r.hasSub ? <span style={css("font-family: var(--font-mono); font-size: 11px; color: rgba(235,235,245,0.6); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;")}>{r.sub}</span> : null}
                      {r.hasBar ? (
                        <span style={css("height: 5px; border-radius: 999px; background: rgba(255,255,255,0.12); overflow: hidden;")}>
                          <span style={css(r.bar)} />
                        </span>
                      ) : null}
                    </span>
                    <span style={css(r.trailStyle)}>{r.trail}</span>
                    {r.chev ? <span style={css("font-size: 20px; color: rgba(235,235,245,0.3); line-height: 1;")}>{"›"}</span> : null}
                  </button>
                ))}
              </div>
            </div>
          ))}
          {tab === 'risk' ? (
            <div style={css("border-radius: 20px; padding: 16px; display: flex; flex-direction: column; gap: 10px; background: rgba(58,104,150,0.22); border: 1px solid rgba(143,176,204,0.4); -webkit-backdrop-filter: blur(18px); backdrop-filter: blur(18px);")}>
              <span style={css("font-size: 12px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: #a9c4e0;")}>{"◉ Observed · worth a look"}</span>
              <span style={css("font-size: 15px; line-height: 1.45;")}>{"Mordred’s message pattern with syn_dxb4 changed. Aether records it; nothing is held or blocked."}</span>
              {!decided ? <button type="button" onClick={openSheet} style={css("font-family: inherit; align-self: flex-start; min-height: 36px; padding: 0 16px; border-radius: 999px; border: 0; background: #6ea0ff; color: #0b0b0e; font-size: 14px; font-weight: 600; cursor: pointer;")} className={hoverClass('background: #5688e6;', 'active')}>{"Review"}</button> : null}
              {decided ? <span style={css(decisionStyle)}>{decision}</span> : null}
            </div>
          ) : null}
          {foot ? <span style={css("font-family: var(--font-mono); font-size: 11px; color: rgba(235,235,245,0.5); padding: 0 16px;")}>{foot}</span> : null}
        </div>
        <div style={css(barStyle)}>
          <div style={{ ...css("position: absolute; left: 0; right: 0; top: 54px; height: 44px; display: flex; align-items: center; justify-content: center;"), opacity: p }}>
            <button type="button" onClick={toTop} style={css("font-family: inherit; background: transparent; border: 0; color: #fff; font-size: 17px; font-weight: 600; cursor: pointer;")}>{TITLES[tab]}</button>
          </div>
        </div>
        <div role="tablist" aria-label="Profile sections" style={css("position: absolute; left: 18px; right: 18px; bottom: 30px; padding: 6px; display: flex; gap: 4px; border-radius: 999px; background: rgba(60,60,67,0.5); border: 1px solid rgba(255,255,255,0.18); -webkit-backdrop-filter: blur(24px) saturate(1.6); backdrop-filter: blur(24px) saturate(1.6); box-shadow: inset 0 1px 0 rgba(255,255,255,0.2), 0 12px 32px rgba(0,0,0,0.4);")}>
          {tabs.map((tb) => (
            <button key={tb.label} type="button" role="tab" aria-selected={tb.sel} onClick={tb.go} style={css(tb.style)}>
              <span style={css("font-family: var(--font-mono); font-size: 19px; line-height: 22px;")}>{tb.g}</span>
              <span style={css("font-size: 10px; font-weight: 500;")}>{tb.label}</span>
            </button>
          ))}
        </div>
      </div>
      {d ? (
        <div onPointerDown={dragDown} onPointerMove={dragMove} onPointerUp={dragUp} onPointerCancel={dragUp} style={css(pushStyle)}>
          <div className="ax-scroll" style={css("position: absolute; inset: 0; overflow-y: auto; padding: 108px 16px 60px; box-sizing: border-box; display: flex; flex-direction: column; gap: 20px;")}>
            <div style={css("display: flex; align-items: center; gap: 14px;")}>
              <span style={css(d.avStyle)}>{d.g}</span>
              <span style={css("display: flex; flex-direction: column; gap: 4px; min-width: 0;")}>
                <span style={css("font-size: 28px; font-weight: 700; letter-spacing: 0.3px; line-height: 1.1;")}>{d.name}</span>
                <span style={css("font-family: var(--font-mono); font-size: 12px; color: rgba(235,235,245,0.6);")}>{d.id}{" · "}{d.role}</span>
              </span>
            </div>
            <div style={css(GLASS + " padding: 16px; display: flex; flex-direction: column; gap: 12px;")}>
              <span style={css("font-size: 15px; line-height: 1.5;")}>{d.desc}</span>
              <span style={css("display: flex; flex-wrap: wrap; gap: 6px;")}>
                {d.facts.map((f) => (
                  <span key={f} style={css("font-family: var(--font-mono); font-size: 11px; padding: 4px 9px; border-radius: 999px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.14);")}>{f}</span>
                ))}
              </span>
              <span style={css(d.riskStyle)}>{d.risk}</span>
            </div>
            {d.hasActions ? (
              <div style={css("display: flex; flex-direction: column; gap: 8px;")}>
                <span style={css("font-size: 13px; text-transform: uppercase; color: rgba(235,235,245,0.6); padding: 0 16px;")}>{"What it has done"}</span>
                <div style={css(GLASS)}>
                  {d.actions.map((a, aIndex) => (
                    <div key={aIndex} style={css(a.style)}>
                      <span style={css(a.gStyle)}>{a.g}</span>
                      <span style={css("flex: 1; font-size: 15px; line-height: 1.35;")}>{a.x}</span>
                      <span style={css("font-family: var(--font-mono); font-size: 11px; color: rgba(235,235,245,0.6);")}>{a.t}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {d.hasMembers ? (
              <div style={css("display: flex; flex-wrap: wrap; gap: 8px;")}>
                {d.members.map((m) => (
                  <Fragment key={m.n}>
                    <span style={css(m.style)}>{m.g}{" "}{m.n}</span>
                  </Fragment>
                ))}
              </div>
            ) : null}
            <button type="button" onClick={() => say('↔ Opening ' + d.name + ' in the graph')} style={css("font-family: inherit; min-height: 50px; border-radius: 14px; border: 0; background: #6ea0ff; color: #0b0b0e; font-size: 17px; font-weight: 600; cursor: pointer;")} className={hoverClass('background: #5688e6;', 'active')}>{"Open in graph"}</button>
          </div>
          <div style={css("position: absolute; left: 0; right: 0; top: 0; height: 98px; background: rgba(11,11,14,0.6); -webkit-backdrop-filter: blur(24px) saturate(1.5); backdrop-filter: blur(24px) saturate(1.5); border-bottom: 0.5px solid rgba(255,255,255,0.14);")}>
            <button type="button" onClick={close} style={css("position: absolute; left: 8px; top: 54px; height: 44px; padding: 0 8px; display: flex; align-items: center; gap: 2px; font-family: inherit; font-size: 17px; background: transparent; border: 0; color: #6ea0ff; cursor: pointer;")}>
              <svg width="12" height="20" viewBox="0 0 12 20" fill="none" aria-hidden="true"><path d="M10 2L2 10l8 8" stroke="#6ea0ff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              {"Relationships"}
            </button>
            <span style={css("position: absolute; left: 0; right: 0; top: 54px; height: 44px; display: flex; align-items: center; justify-content: center; font-size: 17px; font-weight: 600; pointer-events: none;")}>{d.name}</span>
          </div>
        </div>
      ) : null}
      {s.sheet ? (
        <div style={css("position: absolute; inset: 0; z-index: 30;")}>
          <div onClick={() => closeSheet()} style={css(scrimStyle)} />
          <div style={css(sheetStyle)}>
            <div style={css("border-radius: 18px; background: rgba(44,44,48,0.82); -webkit-backdrop-filter: blur(30px) saturate(1.6); backdrop-filter: blur(30px) saturate(1.6); border: 1px solid rgba(255,255,255,0.12); overflow: hidden;")}>
              <div style={css("padding: 16px; text-align: center; display: flex; flex-direction: column; gap: 4px;")}>
                <span style={css("font-size: 13px; font-weight: 600; color: rgba(235,235,245,0.7);")}>{"Mordred · syn_dxb4"}</span>
                <span style={css("font-size: 13px; color: rgba(235,235,245,0.55);")}>{"Choose what to record. Nothing is held or blocked."}</span>
              </div>
              {sheetActions.map((sa) => (
                <button key={sa.label} type="button" onClick={sa.go} style={css(sa.style)} className={ACTIVE_SHEET}>{sa.label}</button>
              ))}
            </div>
            <button type="button" onClick={() => closeSheet()} style={css("font-family: inherit; min-height: 56px; border-radius: 18px; border: 1px solid rgba(255,255,255,0.12); background: rgba(44,44,48,0.92); color: #6ea0ff; font-size: 20px; font-weight: 600; cursor: pointer;")} className={hoverClass('background: rgba(70,70,76,0.95);', 'active')}>{"Cancel"}</button>
          </div>
        </div>
      ) : null}
      {s.toast ? <div role="status" style={css("position: absolute; left: 24px; right: 24px; bottom: 124px; z-index: 40; padding: 12px 16px; border-radius: 16px; background: rgba(44,44,48,0.8); border: 1px solid rgba(255,255,255,0.16); -webkit-backdrop-filter: blur(24px) saturate(1.5); backdrop-filter: blur(24px) saturate(1.5); font-size: 14px; text-align: center; box-shadow: 0 12px 32px rgba(0,0,0,0.4);")}>{s.toast}</div> : null}
    </div>
  );
}
