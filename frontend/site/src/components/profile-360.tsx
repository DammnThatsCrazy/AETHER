/**
 * Built from design/designs/Profile 360.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { asset, css, hoverClass, useDesignState } from '@site/design/runtime';

import './profile-360.css';

import { useEffect, useRef, type ChangeEvent, type CSSProperties, type KeyboardEvent } from 'react';

type Act = { g: string; x: string; t: string; gStyle: string };
interface Rel {
  key: string;
  g: string;
  name: string;
  id: string;
  role: string;
  kind: string;
  type: 'agents' | 'humans' | 'syndicates';
  c: string;
  risk: number;
  desc: string;
  facts: string[];
  actions?: Act[];
  members?: [string, string, string][];
}
type JourneyStep = [label: string, src: string, n: number, rate: string, jane: boolean, d: string];
interface Journey {
  label: string;
  logo: string;
  name: string;
  campaign: string;
  status: string;
  c: string;
  kpis: [string, string, string][];
  steps: JourneyStep[];
  meta: string;
}

/** Brand logos are reviewed local marks; X uses its dark-surface variant here. */
const B = (k: string) => '../assets/brand/' + (k === 'x' ? 'x-dark' : k) + '.svg';
const TABS: [string, string, string, string][] = [['overview', '◈', 'Overview', '#5a85a8'], ['rels', '↔', 'Relationships', '#6b9a7c'], ['journeys', '→', 'Journeys', '#a88a5a'], ['risk', '▲', 'Risk', '#c9975a'], ['value', '↑', 'Value', '#6b9a7c']];
const AG = { Ptolemy: '#3a6896', Kierkegaard: '#5a85a8', Mordred: '#c9975a' };
const act = (g: string, c: string, x: string, t: string): Act => ({ g, x, t, gStyle: 'font-family: var(--font-mono); color: ' + c + ';' });
const R: Rel[] = [
  { key: 'ptolemy', g: '⬡', name: 'Ptolemy', id: 'agt_2f18e', role: 'delegated agent', kind: 'H→A', type: 'agents', c: AG.Ptolemy, risk: 28, desc: 'Scores incoming supplier applications for Jane and flags exceptions to Osiris.', facts: ['42 actions/day', 'strength 0.90', 'scope: scoring.read'],
    actions: [act('✓', '#6b9a7c', 'Scored application app_71c · 0.82', '1h'), act('→', '#9fbad6', 'Flagged exception to Osiris', '5h'), act('✓', '#6b9a7c', 'Onboarded supplier to SF syndicate', '2d')] },
  { key: 'kierkegaard', g: '⬡', name: 'Kierkegaard', id: 'agt_5c02f', role: 'delegated agent', kind: 'H→A', type: 'agents', c: AG.Kierkegaard, risk: 31, desc: 'Audits cross-border settlement records for irregularities.', facts: ['9 actions/day', '$1.8K value', 'strength 0.82'],
    actions: [act('◉', '#a88a5a', 'Audited Stripe payout po_9x2 · clean', '3h'), act('✓', '#6b9a7c', 'Reconciled 14 settlements', '1d')] },
  { key: 'mordred', g: '⬡', name: 'Mordred', id: 'agt_88ce1', role: 'flagged relationship', kind: 'A→A', type: 'agents', c: AG.Mordred, risk: 91, desc: 'Unusual messages with an outside payments agent in a flagged group. Passed to Percival.', facts: ['conf 0.88', '212 messages', 'strength 0.68'],
    actions: [act('↔', '#c9975a', 'Messaged external agent in syn_dxb4 ×212', '6h'), act('▲', '#b5564a', 'Escalated pattern to Percival', '6h'), act('■', '#b5564a', 'Percival paused the next payment batch · seen', 'now')] },
  { key: 'percival', g: '●', name: 'Percival', id: 'usr_91b2c', role: 'risk analyst', kind: 'H→H', type: 'humans', c: '#6b9a7c', risk: 12, desc: 'Approves payment batches together with Jane. Receives Mordred’s alerts.', facts: ['14 shared approvals', 'slack · crm', 'strength 0.74'] },
  { key: 'osiris', g: '●', name: 'Osiris', id: 'usr_c33a0', role: 'compliance', kind: 'H→H', type: 'humans', c: '#6b9a7c', risk: 18, desc: 'Reviews rule exceptions raised by Ptolemy.', facts: ['6 reviews', 'strength 0.52'] },
  { key: 'maya', g: '●', name: 'Maya Chen', id: 'usr_a81d3', role: 'referred by Jane', kind: 'H→H', type: 'humans', c: '#6b9a7c', risk: 9, desc: 'Joined through Jane’s referral link on X. Now a repeat buyer.', facts: ['referral', '$2.1K value', '3 orders'] },
  { key: 'supplier', g: '◈', name: 'SF supplier syndicate', id: 'syn_sf01', role: '5 humans · 2 agents', kind: 'cluster', type: 'syndicates', c: '#a88a5a', risk: 36, desc: 'Supplier network handled through Ptolemy. Most common path: sourced → contracted → active.', facts: ['$14.6K value', '11 journeys'],
    members: [['●', 'Jane Doe', '#6b9a7c'], ['●', 'Osiris', '#6b9a7c'], ['●', '+3 suppliers', '#6b9a7c'], ['⬡', 'Ptolemy', AG.Ptolemy], ['⬡', 'Kierkegaard', AG.Kierkegaard]] },
  { key: 'settlement', g: '◈', name: 'Settlement syndicate', id: 'syn_dxb4', role: '2 humans · 3 agents', kind: 'cluster', type: 'syndicates', c: '#b5564a', risk: 84, desc: 'Flagged group in Dubai. Mordred messages one of its agents.', facts: ['flagged', '2 hops from Jane'],
    members: [['●', '2 unknown humans', '#a09f99'], ['⬡', 'agt_x41 (external)', '#b5564a'], ['⬡', '+2 agents', '#b5564a']] },
];
const J: Record<'ig' | 'x', Journey> = {
  ig: { label: 'Instagram · Spring Drop', logo: B('instagram'), name: 'Paid social → first purchase', campaign: 'campaign:cmp_spring26 · Instagram Reels + Stories', status: '● converted', c: '#6b9a7c',
    kpis: [['$38.20', 'CAC', '#9cc4a9'], ['5.3%', 'click → purchase', '#9fbad6'], ['3.4×', 'ROAS', '#c9975a'], ['$2,330', 'spend', '#e8e6e1']],
    steps: [['Reel impression', 'instagram', 48200, '100%', true, 'Mar 9'], ['Link click', 'instagram', 1157, '2.4%', true, 'Mar 9'], ['Product view', 'shopify', 812, '70.2%', true, 'Mar 9'], ['Add to cart', 'shopify', 204, '25.1%', true, 'Mar 10'], ['Checkout started', 'stripe', 96, '47.1%', true, 'Mar 12'], ['Paid · $4,200', 'stripe', 61, '63.5%', true, 'Mar 12']],
    meta: 'journey:jrn_ig_01 · sources instagram, shopify, stripe · attribution 0.34 to campaign' },
  x: { label: 'X · Creator referral', logo: B('x'), name: 'Creator post → subscription', campaign: 'campaign:cmp_creator_x · referral thread on X', status: '▲ renewal at risk', c: '#c9975a',
    kpis: [['$52.10', 'CAC', '#9cc4a9'], ['3.1%', 'visit → paid', '#9fbad6'], ['$18.4K', 'LTV', '#c9975a'], ['353×', 'LTV / CAC', '#e8e6e1']],
    steps: [['Creator post', 'x', 22400, '100%', true, 'Feb 2'], ['Landing visit', 'x', 1840, '8.2%', true, 'Feb 2'], ['Lead captured', 'hubspot', 410, '22.3%', true, 'Feb 3'], ['Nurture email opened', 'hubspot', 236, '57.6%', true, 'Feb 6'], ['Demo booked', 'hubspot', 92, '39.0%', true, 'Feb 9'], ['Subscribed · Beta', 'stripe', 57, '62.0%', true, 'Feb 14']],
    meta: 'journey:jrn_x_02 · sources x, hubspot, stripe · referral edge → Maya Chen' },
};
const IDX: [string, string, string, string | null][] = [['Ptolemy · delegated agent', 'relationships', 'rels', 'agents'], ['Mordred · flagged', 'relationships', 'rels', 'agents'], ['Percival · risk analyst', 'relationships', 'rels', 'humans'], ['Settlement syndicate', 'relationships', 'rels', 'syndicates'], ['Instagram · Spring Drop', 'journeys', 'journeys', null], ['X · creator referral', 'journeys', 'journeys', null], ['Risk score 72', 'risk', 'risk', null], ['Lifetime value $18,420', 'value', 'value', null]];

interface P360State {
  tab: string;
  filter: string;
  open: string | null;
  decision: 'approved' | 'declined' | null;
  j: 'ig' | 'x';
  watch: boolean;
  search: boolean;
  q: string;
  note: string;
}

export function Profile360(props: { ios?: boolean; style?: CSSProperties }) {
  const ios = !!props.ios;
  const [s, setState] = useDesignState<P360State>({ tab: 'overview', filter: 'all', open: 'mordred', decision: null, j: 'ig', watch: false, search: false, q: '', note: '' });
  const searchRef = useRef<HTMLInputElement>(null);
  const noteTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(noteTimer.current), []);
  const flash = (x: string) => {
    clearTimeout(noteTimer.current);
    setState({ note: x });
    noteTimer.current = setTimeout(() => setState({ note: '' }), 2600);
  };
  const tab = (k: string) => () => setState({ tab: k });
  const counts: Record<string, number> = { all: R.length, humans: R.filter((r) => r.type === 'humans').length, agents: R.filter((r) => r.type === 'agents').length, syndicates: R.filter((r) => r.type === 'syndicates').length };
  const shown = R.filter((r) => s.filter === 'all' || r.type === s.filter);
  const riskC = (n: number) => (n >= 80 ? '#b5564a' : n >= 50 ? '#c9975a' : '#6b9a7c');
  const decided = s.decision;
  const jrRaw = J[s.j] ?? J.ig;
  const max = jrRaw.steps[0]?.[2] ?? 1;
  const ql = s.q.trim().toLowerCase();
  const hits = (ql ? IDX.filter((x) => x[0].toLowerCase().includes(ql)) : IDX.slice(0, 4)).map(([label, where, tb, f]) => ({ label, where, go: () => setState({ tab: tb, filter: f || s.filter, search: false, q: '' }) }));
  const hAct = (g: string, label: string, on: boolean, go: () => void, tone?: string) => ({
    g, label, go, pressed: on,
    style: 'font-family: inherit; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; min-height: 28px; padding: 0 10px; border-radius: 4px; font-size: 12px; font-weight: 500; cursor: pointer; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1); ' + (on ? 'background: rgba(90,133,168,0.18); color: #9fbad6; border: 1px solid #5a85a8;' : tone === 'primary' ? 'background: #e8e6e1; color: #1a1a1e; border: 1px solid #e8e6e1;' : 'background: #1a1a1e; color: #e8e6e1; border: 1px solid #2a2a2f;'),
    hover: tone === 'primary' ? 'background: #d8d6d0; border-color: #d8d6d0;' : 'background: #1f1f24; border-color: #3a3a40;',
  });
  const isIos = ios;
  const notIos = !ios;
  const rootClass = ios ? 'p360-ios' : '';
  const searchLabel = 'Search this profile';
  const searchOpen = s.search;
  const q = s.q;
  const openSearch = () => {
    setState({ search: !s.search });
    setTimeout(() => searchRef.current?.focus(), 0);
  };
  const onQ = (e: ChangeEvent<HTMLInputElement>) => setState({ q: e.target.value });
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') setState({ search: false, q: '' });
    if (e.key === 'Enter' && hits[0]) hits[0].go();
  };
  const hasNote = !!s.note;
  const note = s.note;
  const headActs = [
    hAct('↔', 'Open in graph', false, () => setState({ tab: 'rels' }), 'primary'),
    hAct(s.watch ? '●' : '○', s.watch ? 'Watching' : 'Watch', s.watch, () => {
      setState({ watch: !s.watch });
      flash(s.watch ? '○ stopped watching Jane Doe' : '● watching Jane Doe · alerts on new risk evidence');
    }),
    hAct('⇩', 'Export', false, () => flash('⇩ export queued · profiles:usr_4f21a9.jsonl')),
  ];
  const accounts = ([['stripe', 'Stripe', 'cus_Q8…4f', 'Billing customer'], ['hubspot', 'HubSpot', 'contact 9812', 'CRM contact'], ['x', 'X', '@janedoe', 'Social'], ['instagram', 'Instagram', '@jane.makes', 'Social'], ['phantom', 'Phantom', '7xKX…9fQm', 'Wallet'], ['shopify', 'Shopify', '3 orders', 'Commerce']] as const).map(([k, name, handle, title]) => ({ logo: B(k), name, handle, title, go: () => flash('↔ ' + name + ' · ' + handle + ' · ' + title.toLowerCase()) }));
  const sources = ([['stripe', 'Stripe'], ['hubspot', 'HubSpot'], ['x', 'X'], ['instagram', 'Instagram'], ['shopify', 'Shopify']] as const).map(([k, name]) => ({ logo: B(k), name }));
  const stats = ([['$18.4K', 'value', '#6b9a7c', 'value'], ['8', 'relationships', '#9fbad6', 'rels'], ['3', 'agents', '#c9975a', 'rels'], ['2', 'journeys', '#a88a5a', 'journeys']] as const).map(([v, k, c, t]) => ({
    v, k, go: tab(t),
    vStyle: 'font-size: 17px; font-weight: 500; color: ' + c + ';',
    style: 'font-family: inherit; padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; align-items: flex-start; background: transparent; border: 0; border-right: 1px solid #2a2a2f; cursor: pointer; color: #e8e6e1;',
  }));
  const tabs = TABS.map(([k, g, label, c]) => ({
    label, g, sel: s.tab === k, go: tab(k),
    gStyle: ios ? 'font-family: var(--font-mono); font-size: 20px; line-height: 24px; color: ' + (s.tab === k ? '#0A84FF' : '#8e8e93') + ';' : 'font-family: var(--font-mono); color: ' + c + ';',
    style: ios
      ? 'font-family: inherit; flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: 10px; font-weight: 500; padding: 4px 0; border: 0; background: transparent; cursor: pointer; transition: color 120ms cubic-bezier(0.22,1,0.36,1); color: ' + (s.tab === k ? '#0A84FF' : '#8e8e93') + ';'
      : 'font-family: inherit; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; font-size: 12px; font-weight: 500; padding: 10px 10px; border: 0; background: transparent; cursor: pointer; border-bottom: 2px solid ' + (s.tab === k ? c : 'transparent') + '; color: ' + (s.tab === k ? '#e8e6e1' : '#a09f99') + ';',
  }));
  const tOverview = s.tab === 'overview';
  const tRels = s.tab === 'rels';
  const tJourneys = s.tab === 'journeys';
  const tRisk = s.tab === 'risk';
  const tValue = s.tab === 'value';
  const goRisk = tab('risk');
  const timeline = ([
    { kind: 'logo', logo: B('stripe'), x: 'stripe · invoice.paid · $4,200', t: '2h' },
    { kind: 'agent', c: AG.Mordred, x: 'Mordred ↔ syn_dxb4 · 212 messages', t: '6h' },
    { kind: 'agent', c: AG.Ptolemy, x: 'Ptolemy · scored app_71c · 0.82', t: '1h' },
    { kind: 'logo', logo: B('instagram'), x: 'instagram · reel click · cmp_spring26', t: '1d' },
    { kind: 'logo', logo: B('hubspot'), x: 'hubspot · lifecycle → customer', t: '2d' },
    { kind: 'glyph', g: '✓', c: '#5a85a8', x: 'approval · batch_0912 · Percival', t: '3d' },
  ] as { kind: string; logo?: string; c?: string; g?: string; x: string; t: string }[]).map((e) => ({
    ...e,
    isAgent: e.kind === 'agent', isLogo: e.kind === 'logo', isGlyph: e.kind === 'glyph', logo: e.logo || '', g: e.g || '',
    agentStyle: 'width: 22px; height: 22px; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; color: #111114; background: ' + (e.c || '#c9975a') + ';',
    dot: 'width: 22px; text-align: center; color: ' + (e.c || '#6b9a7c') + ';',
  }));
  const filters = ['all', 'humans', 'agents', 'syndicates'].map((f) => ({
    label: f.charAt(0).toUpperCase() + f.slice(1), n: counts[f], go: () => setState({ filter: f }),
    style: 'font-family: inherit; font-size: 12px; font-weight: 500; min-height: 28px; padding: 0 11px; border-radius: 999px; cursor: pointer; ' + (s.filter === f ? 'background: #e8e6e1; color: #111114; border: 1px solid #e8e6e1;' : 'background: transparent; color: #e8e6e1; border: 1px solid #2a2a2f;'),
  }));
  const rels = shown.map((r, i) => {
    const open = s.open === r.key;
    return {
      ...r, open, risk: 'risk ' + r.risk, go: () => setState({ open: open ? null : r.key }),
      hasActions: !!r.actions, actions: r.actions || [], hasMembers: !!r.members,
      members: (r.members || []).map(([g, n, c]) => ({ g, n, style: 'font-size: 11px; padding: 3px 8px; border-radius: 999px; background: #1a1a1e; border: 1px solid ' + c + '66; color: #e8e6e1; font-family: var(--font-mono);' })),
      avatar: 'width: 30px; height: 30px; flex-shrink: 0; border-radius: ' + (r.g === '●' ? '999px' : '8px') + '; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 14px; color: #111114; background: ' + r.c + ';',
      kindStyle: 'font-family: var(--font-mono); font-size: 11px; padding: 2px 7px; border-radius: 6px; white-space: nowrap; color: ' + r.c + '; border: 1px solid ' + r.c + '66;',
      riskStyle: 'font-family: var(--font-mono); font-size: 11px; white-space: nowrap; min-width: 52px; text-align: right; color: ' + riskC(r.risk) + ';',
      detailStyle: 'padding: 10px 12px 12px 50px; display: flex; flex-direction: column; gap: 8px; background: #16161a; border-top: 1px solid #2a2a2f; box-shadow: inset 2px 0 0 ' + r.c + ';',
      style: 'font-family: inherit; display: flex; align-items: center; gap: 10px; width: 100%; padding: 9px 12px; background: ' + (open ? '#1a1a1e' : 'transparent') + '; border: 0; border-top: ' + (i ? '1px solid #2a2a2f' : '0') + '; cursor: pointer; color: inherit; transition: background-color 120ms;',
    };
  });
  const jTabs = (Object.entries(J) as ['ig' | 'x', Journey][]).map(([k, v]) => ({
    label: v.label, logo: v.logo, go: () => setState({ j: k }),
    style: 'font-family: inherit; display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; min-height: 30px; padding: 0 11px 0 5px; border-radius: 999px; font-size: 12px; font-weight: 500; cursor: pointer; ' + (s.j === k ? 'background: #e8e6e1; color: #111114; border: 1px solid #e8e6e1;' : 'background: transparent; color: #e8e6e1; border: 1px solid #2a2a2f;'),
  }));
  const jr = {
    name: jrRaw.name, campaign: jrRaw.campaign, status: jrRaw.status, meta: jrRaw.meta, stStyle: 'font-family: var(--font-mono); font-size: 11px; color: ' + jrRaw.c + ';',
    kpis: jrRaw.kpis.map(([v, k, c]) => ({ v, k, style: 'border-radius: 8px; padding: 8px; background: #1a1a1e; display: flex; flex-direction: column; gap: 2px;', vStyle: 'font-size: 15px; font-weight: 500; color: ' + c + ';' })),
    steps: jrRaw.steps.map(([label, src, n, rate, jane, d], i) => ({
      label, logo: B(src), n: n.toLocaleString('en-US'), rate, jane, d,
      bar: 'display: block; height: 100%; width: ' + Math.max(2, Math.sqrt(n / max) * 100) + '%; background: ' + ['#3a6896', '#5a85a8', '#6b9a7c', '#a88a5a', '#c9975a', '#6b9a7c'][i] + ';',
      rateStyle: 'font-family: var(--font-mono); font-size: 11px; text-align: right; color: ' + (i === 0 ? '#a09f99' : '#9cc4a9') + ';',
    })),
  };
  const drivers = ([['Agent Mordred is two steps from a flagged group', '+31', '#b5564a'], ['Cross-border payments up 3.1× in speed', '+18', '#c9975a'], ['New counterparty in 7 days', '+9', '#c9975a'], ['Verified identity across 6 sources', '−12', '#6b9a7c']] as const).map(([x, v, c]) => ({ x, v, vStyle: 'font-family: var(--font-mono); color: ' + c + ';' }));
  // Human review of what an agent did: "Mark reviewed" and "Flag" record the
  // reviewer's note; Aether never approves or blocks the agent's action.
  const pending = !decided;
  const approve = () => setState({ decision: 'approved' });
  const decline = () => setState({ decision: 'declined' });
  const decision = decided === 'approved' ? '✓ reviewed by you · just now' : decided === 'declined' ? '⚑ flagged for follow-up' : 'not yet reviewed';
  const decisionStyle = 'font-family: var(--font-mono); font-size: 11px; color: ' + (decided === 'approved' ? '#6b9a7c' : decided === 'declined' ? '#b5564a' : '#a09f99') + ';';
  const attribution = ([['instagram', 'instagram', 0.34, '#E4405F'], ['x', 'x · referral', 0.26, '#9fbad6'], ['hubspot', 'hubspot', 0.22, '#FF7A59'], ['shopify', 'shopify', 0.18, '#6b9a7c']] as const).map(([k, src, w, c]) => ({ logo: B(k), src, w: w.toFixed(2), bar: 'display: block; height: 100%; width: ' + w * 250 + '%; max-width: 100%; background: ' + c + ';' }));
  return (
    <div className="dc pg-profile-360" style={props.style}>
    <div data-page="profile-360" style={css("display: flex; flex-direction: column; min-width: 0; font-family: var(--font-sans);")} className={`${rootClass}`}>
      {(isIos) ? (
        <>
          <div data-theme="dark" style={css("background: rgba(0,0,0,0.88); -webkit-backdrop-filter: blur(20px); backdrop-filter: blur(20px); position: sticky; top: 0; z-index: 6; padding: 54px 16px 10px; margin-top: -54px; display: flex; flex-direction: column; gap: 6px;")}>
            <div style={css("display: flex; align-items: center; justify-content: space-between;")}>
              <span style={css("display: inline-flex; align-items: center; gap: 2px; color: #0A84FF; font-size: 17px;")}>
                <svg width="12" height="20" viewBox="0 0 12 20" fill="none">
                  <path d="M10 2L2 10l8 8" stroke="#0A84FF" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                {"Profiles"}
              </span>
              <button type="button" onClick={openSearch} aria-label="Search this profile" style={css("width: 36px; height: 36px; border-radius: 999px; border: 0; background: rgba(120,120,128,0.24); color: #e8e6e1; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center;")}>
                {"⌕"}
              </button>
            </div>
            <div style={css("display: flex; align-items: baseline; justify-content: space-between; gap: 8px;")}>
              <span style={css("font-size: 34px; font-weight: 700; letter-spacing: 0.4px; color: #fff;")}>
                {"Jane Doe"}
              </span>
              <span title="Illustrative data — not a customer record" style={css("font-size: 11px; color: #8e8e93;")}>
                {"synthetic"}
              </span>
            </div>
          </div>
        </>
      ) : null}
      {(notIos) ? (
        <>
          <div data-theme="dark" style={css("display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: #1a1a1e; border: 1px solid #2a2a2f; border-bottom: 0; border-radius: 8px 8px 0 0; color: #e8e6e1; font-size: 12px;")}>
            <span style={css("display: flex; align-items: center; gap: 6px; min-width: 0; white-space: nowrap;")}>
              <img src={asset("../assets/logo-aether-layers.svg")} alt="" style={css("width: 16px; height: 16px;")} />
              <span style={css("color: #a09f99;")}>
                {"360"}
              </span>
              <span style={css("color: #6b6a65;")}>
                {"/"}
              </span>
              <span style={css("font-weight: 500;")}>
                {"Jane Doe"}
              </span>
            </span>
            <button type="button" onClick={openSearch} style={css("font-family: inherit; flex: 1; min-width: 0; max-width: 260px; margin-left: auto; display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 28px; padding: 0 8px; border-radius: 4px; border: 1px solid #2a2a2f; background: #111114; color: #a09f99; font-size: 12px; cursor: pointer; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-0fb9f849">
              <span style={css("display: flex; gap: 6px; overflow: hidden; white-space: nowrap;")}>
                <span style={css("font-family: var(--font-mono);")}>
                  {"⌕"}
                </span>
                {searchLabel}
              </span>
              <kbd style={css("font-family: var(--font-mono); font-size: 10px; padding: 0 4px; border: 1px solid #2a2a2f; border-radius: 3px;")}>
                {"⌘K"}
              </kbd>
            </button>
            <span title="Illustrative data — not a customer record" style={css("font-family: var(--font-mono); font-size: 10px; padding: 2px 7px; border-radius: 999px; border: 1px dashed #3a3a40; color: #a09f99; white-space: nowrap;")}>
              {"synthetic"}
            </span>
          </div>
        </>
      ) : null}
      <div data-theme="dark" style={css("background: #111114; border: 1px solid #2a2a2f; border-radius: 0 0 8px 8px; color: #e8e6e1; font-size: 13px; overflow: hidden;")} className="p360">
        {(searchOpen) ? (
          <>
            <div style={css("border-bottom: 1px solid #2a2a2f; background: #16161a; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px;")}>
              <input ref={searchRef} value={q} onChange={onQ} onKeyDown={onKey} placeholder="Search relationships, agents, journeys" aria-label="Search this profile" style={css("font-family: inherit; font-size: 13px; min-height: 32px; padding: 0 10px; border-radius: 4px; border: 1px solid #3a3a40; background: #111114; color: #e8e6e1; outline: none;")} />
              {(hits).map((h: any, hIndex: number) => (
                <Fragment key={hIndex}>
                  <button type="button" onClick={h.go} style={css("font-family: inherit; text-align: left; display: flex; justify-content: space-between; gap: 8px; padding: 7px 10px; border-radius: 4px; border: 0; background: transparent; color: #e8e6e1; font-size: 12px; cursor: pointer; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-cbfffb40">
                    <span>
                      {h.label}
                    </span>
                    <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                      {h.where}
                    </span>
                  </button>
                </Fragment>
              ))}
            </div>
          </>
        ) : null}
        <div style={css("padding: 16px; display: flex; flex-direction: column; gap: 12px; border-bottom: 1px solid #2a2a2f; background: #141418;")}>
          <div style={css("display: flex; gap: 12px; align-items: center;")}>
            <span style={css("position: relative; width: 52px; height: 52px; flex-shrink: 0;")}>
              <span style={css("width: 52px; height: 52px; border-radius: 999px; display: flex; align-items: center; justify-content: center; font-weight: 500; font-size: 17px; background: #3a6896; color: #f5f4f1; box-shadow: 0 0 0 3px rgba(58,104,150,0.35);")}>
                {"JD"}
              </span>
              <span style={css("position: absolute; right: -2px; bottom: -2px; width: 14px; height: 14px; border-radius: 999px; background: #6b9a7c; border: 2px solid #111114;")} />
            </span>
            <span style={css("display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1;")}>
              <span style={css("display: flex; align-items: center; gap: 8px; flex-wrap: wrap;")}>
                <span style={css("font-size: 17px; font-weight: 500;")}>
                  {"Jane Doe"}
                </span>
                <span style={css("font-size: 11px; font-weight: 500; padding: 2px 8px; border-radius: 999px; background: rgba(107,154,124,0.2); color: #9cc4a9;")}>
                  {"VIP · Beta"}
                </span>
              </span>
              <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                {"entity:usr_4f21a9 · San Francisco, US · GMT-7"}
              </span>
            </span>
            <span style={css("display: inline-flex; gap: 6px; align-items: center; font-family: var(--font-mono); font-size: 11px; padding: 3px 9px; border-radius: 999px; background: rgba(201,151,90,0.18); color: #c9975a; white-space: nowrap;")}>
              {"▲ risk 72"}
            </span>
          </div>
          <div style={css("display: flex; flex-wrap: wrap; gap: 6px;")}>
            {(headActs).map((h: any, hIndex: number) => (
              <Fragment key={hIndex}>
                <button type="button" onClick={h.go} aria-pressed={h.pressed} style={css(h.style)} className={`${hoverClass(h.hover, 'hover')}`}>
                  <span style={css("font-family: var(--font-mono);")}>
                    {h.g}
                  </span>
                  {h.label}
                </button>
              </Fragment>
            ))}
          </div>
          <div style={css("display: flex; flex-wrap: wrap; gap: 6px;")}>
            {(accounts).map((a: any, aIndex: number) => (
              <Fragment key={aIndex}>
                <button type="button" title={a.title} onClick={a.go} style={css("font-family: inherit; color: #e8e6e1; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px 3px 3px; border-radius: 999px; background: #1a1a1e; border: 1px solid #2a2a2f; font-size: 11px; white-space: nowrap; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-00bd5268">
                  <span style={css("width: 20px; height: 20px; border-radius: 999px; background: #f5f4f1; display: inline-flex; align-items: center; justify-content: center;")}>
                    <span aria-hidden="true" style={css(`display: block; width: 12px; height: 12px; background: url(${a.logo}) center / contain no-repeat;`)} />
                  </span>
                  <span style={css("font-weight: 500;")}>
                    {a.name}
                  </span>
                  <span style={css("font-family: var(--font-mono); color: #a09f99;")}>
                    {a.handle}
                  </span>
                </button>
              </Fragment>
            ))}
          </div>
        </div>
        <div style={css("display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); border-bottom: 1px solid #2a2a2f;")}>
          {(stats).map((s: any, sIndex: number) => (
            <Fragment key={sIndex}>
              <button type="button" onClick={s.go} style={css(s.style)} className="hv-de76f755">
                <span style={css(s.vStyle)}>
                  {s.v}
                </span>
                <span style={css("font-size: 11px; color: #a09f99;")}>
                  {s.k}
                </span>
              </button>
            </Fragment>
          ))}
        </div>
        <div role="tablist" aria-label="Profile sections" style={css("display: flex; gap: 2px; padding: 0 8px; border-bottom: 1px solid #2a2a2f; overflow-x: auto;")}>
          {(tabs).map((t: any, tIndex: number) => (
            <Fragment key={tIndex}>
              <button type="button" role="tab" aria-selected={t.sel} onClick={t.go} style={css(t.style)} className="hv-761d44c6">
                <span style={css(t.gStyle)}>
                  {t.g}
                </span>
                {t.label}
              </button>
            </Fragment>
          ))}
        </div>
        <div style={css("padding: 14px 16px; min-height: 320px; display: flex; flex-direction: column; gap: 12px;")} className="p360-body">
          {(tOverview) ? (
            <>
              <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap: 8px;")}>
                <div style={css("border: 1px solid #2a2a2f; border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 7px; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-f244a51d">
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                    {"Identity and contact"}
                  </span>
                  <span style={css("font-family: var(--font-mono); font-size: 12px;")}>
                    {"j••••e@example.com"}
                  </span>
                  <span style={css("font-family: var(--font-mono); font-size: 12px;")}>
                    {"+1 (415) •••-••42"}
                  </span>
                  <span style={css("display: flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: 12px;")}>
                    <img src={asset("../assets/brand/phantom.svg")} alt="" style={css("width: 16px; height: 16px;")} />
                    {"Phantom "}
                    <span style={css("color: #a09f99;")}>
                      {"7xKX…9fQm"}
                    </span>
                  </span>
                </div>
                <div style={css("border: 1px solid #2a2a2f; border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 7px; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-f244a51d">
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                    {"Sources and consent"}
                  </span>
                  <span style={css("display: flex; flex-wrap: wrap; gap: 5px;")}>
                    {(sources).map((x: any, xIndex: number) => (
                      <Fragment key={xIndex}>
                        <span title={x.name} style={css("width: 26px; height: 26px; border-radius: 8px; background: #f5f4f1; display: inline-flex; align-items: center; justify-content: center;")}>
                          <span aria-hidden="true" style={css(`display: block; width: 15px; height: 15px; background: url(${x.logo}) center / contain no-repeat;`)} />
                        </span>
                      </Fragment>
                    ))}
                    <span title="Web SDK" style={css("width: 26px; height: 26px; border-radius: 8px; background: rgba(107,154,124,0.2); color: #9cc4a9; display: inline-flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 12px;")}>
                      {"⌘"}
                    </span>
                  </span>
                  <span style={css("font-family: var(--font-mono); font-size: 12px;")}>
                    <span style={css("color: #6b9a7c;")}>
                      {"✓"}
                    </span>
                    {" analytics "}
                    <span style={css("color: #6b9a7c; margin-left: 6px;")}>
                      {"✓"}
                    </span>
                    {" marketing"}
                  </span>
                  <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                    {"fresh 2h · 6 sources · tenant:sandbox"}
                  </span>
                </div>
              </div>
              <div style={css("border: 1px solid rgba(201,151,90,0.45); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 6px; background: rgba(201,151,90,0.08);")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #c9975a;")}>
                  {"○ What the graph found"}
                </span>
                <span style={css("font-size: 13px; line-height: 1.55;")}>
                  {"A top customer is two steps away from a flagged payment group, through an AI agent acting for her. No single tool shows this."}
                </span>
                <button type="button" onClick={goRisk} style={css("font-family: inherit; align-self: flex-start; display: inline-flex; gap: 6px; align-items: center; white-space: nowrap; min-height: 30px; padding: 0 12px; border-radius: 999px; font-size: 12px; font-weight: 500; background: #c9975a; color: #1a1a1e; border: 0; cursor: pointer;")}>
                  {"See why"}
                  <span style={css("font-family: var(--font-mono);")}>
                    {"→"}
                  </span>
                </button>
              </div>
              <div style={css("display: flex; flex-direction: column; gap: 7px;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {"Recent evidence"}
                </span>
                {(timeline).map((e: any, eIndex: number) => (
                  <Fragment key={eIndex}>
                    <div style={css("display: grid; grid-template-columns: 22px minmax(0,1fr) auto; gap: 8px; font-family: var(--font-mono); font-size: 12px; align-items: center; padding: 5px 6px; margin: 0 -6px; border-radius: 4px; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-de76f755">
                      {(e.isAgent) ? (
                        <>
                          <span style={css(e.agentStyle)}>
                            {"⬡"}
                          </span>
                        </>
                      ) : null}
                      {(e.isLogo) ? (
                        <>
                          <span style={css("width: 22px; height: 22px; border-radius: 6px; background: #f5f4f1; display: inline-flex; align-items: center; justify-content: center;")}>
                            <span aria-hidden="true" style={css(`display: block; width: 13px; height: 13px; background: url(${e.logo}) center / contain no-repeat;`)} />
                          </span>
                        </>
                      ) : null}
                      {(e.isGlyph) ? (
                        <>
                          <span style={css(e.dot)}>
                            {e.g}
                          </span>
                        </>
                      ) : null}
                      <span style={css("overflow: hidden; text-overflow: ellipsis; white-space: nowrap;")}>
                        {e.x}
                      </span>
                      <span style={css("color: #a09f99;")}>
                        {e.t}
                      </span>
                    </div>
                  </Fragment>
                ))}
              </div>
            </>
          ) : null}
          {(tRels) ? (
            <>
              <div style={css("display: flex; flex-wrap: wrap; gap: 6px;")}>
                {(filters).map((f: any, fIndex: number) => (
                  <Fragment key={fIndex}>
                    <button type="button" onClick={f.go} style={css(f.style)}>
                      {f.label}{" "}
                      <span style={css("opacity: 0.7;")}>
                        {f.n}
                      </span>
                    </button>
                  </Fragment>
                ))}
              </div>
              <div style={css("display: flex; flex-direction: column; border: 1px solid #2a2a2f; border-radius: 10px; overflow: hidden;")}>
                {(rels).map((r: any, rIndex: number) => (
                  <Fragment key={rIndex}>
                    <button type="button" onClick={r.go} style={css(r.style)} className="hv-de76f755">
                      <span style={css(r.avatar)}>
                        {r.g}
                      </span>
                      <span style={css("display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; text-align: left;")}>
                        <span style={css("font-size: 13px; font-weight: 500; color: #e8e6e1;")}>
                          {r.name}
                        </span>
                        <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;")}>
                          {r.id}{" · "}{r.role}
                        </span>
                      </span>
                      <span style={css(r.kindStyle)}>
                        {r.kind}
                      </span>
                      <span style={css(r.riskStyle)}>
                        {r.risk}
                      </span>
                    </button>
                    {(r.open) ? (
                      <>
                        <div style={css(r.detailStyle)}>
                          <span style={css("font-size: 13px; line-height: 1.55; color: #e8e6e1;")}>
                            {r.desc}
                          </span>
                          <div style={css("display: flex; flex-wrap: wrap; gap: 6px;")}>
                            {(r.facts).map((k: any, kIndex: number) => (
                              <Fragment key={kIndex}>
                                <span style={css("font-family: var(--font-mono); font-size: 11px; padding: 3px 7px; border-radius: 6px; background: #1a1a1e; border: 1px solid #2a2a2f; color: #e8e6e1; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-7f0f7148">
                                  {k}
                                </span>
                              </Fragment>
                            ))}
                          </div>
                          {(r.hasActions) ? (
                            <>
                              <div style={css("display: flex; flex-direction: column; gap: 5px; padding-top: 4px;")}>
                                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                                  {"What it has done"}
                                </span>
                                {(r.actions).map((a: any, aIndex: number) => (
                                  <Fragment key={aIndex}>
                                    <div style={css("display: grid; grid-template-columns: 16px minmax(0,1fr) auto; gap: 8px; font-size: 12px; align-items: baseline;")}>
                                      <span style={css(a.gStyle)}>
                                        {a.g}
                                      </span>
                                      <span>
                                        {a.x}
                                      </span>
                                      <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                                        {a.t}
                                      </span>
                                    </div>
                                  </Fragment>
                                ))}
                              </div>
                            </>
                          ) : null}
                          {(r.hasMembers) ? (
                            <>
                              <div style={css("display: flex; flex-wrap: wrap; gap: 5px; padding-top: 4px;")}>
                                {(r.members).map((m: any, mIndex: number) => (
                                  <Fragment key={mIndex}>
                                    <span style={css(m.style)}>
                                      {m.g}{" "}{m.n}
                                    </span>
                                  </Fragment>
                                ))}
                              </div>
                            </>
                          ) : null}
                        </div>
                      </>
                    ) : null}
                  </Fragment>
                ))}
              </div>
            </>
          ) : null}
          {(tJourneys) ? (
            <>
              <div style={css("display: flex; gap: 6px;")}>
                {(jTabs).map((j: any, jIndex: number) => (
                  <Fragment key={jIndex}>
                    <button type="button" onClick={j.go} style={css(j.style)}>
                      <span style={css("width: 20px; height: 20px; border-radius: 999px; background: #f5f4f1; display: inline-flex; align-items: center; justify-content: center; box-shadow: 0 0 0 1px #d8d6d0;")}>
                        <span aria-hidden="true" style={css(`display: block; width: 12px; height: 12px; background: url(${j.logo}) center / contain no-repeat;`)} />
                      </span>
                      {j.label}
                    </button>
                  </Fragment>
                ))}
              </div>
              <div style={css("border: 1px solid #2a2a2f; border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 12px; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-f244a51d">
                <div style={css("display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; align-items: baseline;")}>
                  <span style={css("display: flex; flex-direction: column; gap: 2px;")}>
                    <span style={css("font-size: 14px; font-weight: 500;")}>
                      {jr.name}
                    </span>
                    <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                      {jr.campaign}
                    </span>
                  </span>
                  <span style={css(jr.stStyle)}>
                    {jr.status}
                  </span>
                </div>
                <div style={css("display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 6px;")}>
                  {(jr.kpis).map((k: any, kIndex: number) => (
                    <Fragment key={kIndex}>
                      <div style={css(k.style)}>
                        <span style={css(k.vStyle)}>
                          {k.v}
                        </span>
                        <span style={css("font-size: 10px; color: #a09f99;")}>
                          {k.k}
                        </span>
                      </div>
                    </Fragment>
                  ))}
                </div>
                <div style={css("display: flex; flex-direction: column; gap: 5px;")}>
                  {(jr.steps).map((s: any, sIndex: number) => (
                    <Fragment key={sIndex}>
                      <div style={css("display: grid; grid-template-columns: 22px minmax(0,1fr) 64px 50px; gap: 8px; align-items: center; font-size: 12px; padding: 5px 6px; margin: 0 -6px; border-radius: 4px; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-de76f755">
                        <span style={css("width: 22px; height: 22px; border-radius: 6px; background: #f5f4f1; display: inline-flex; align-items: center; justify-content: center;")}>
                          <span aria-hidden="true" style={css(`display: block; width: 13px; height: 13px; background: url(${s.logo}) center / contain no-repeat;`)} />
                        </span>
                        <span style={css("display: flex; flex-direction: column; gap: 3px; min-width: 0;")}>
                          <span style={css("display: flex; gap: 6px; align-items: baseline;")}>
                            <span style={css("font-weight: 500;")}>
                              {s.label}
                            </span>
                            {(s.jane) ? (
                              <>
                                <span style={css("font-family: var(--font-mono); font-size: 10px; color: #9fbad6;")}>
                                  {"● Jane · "}{s.d}
                                </span>
                              </>
                            ) : null}
                          </span>
                          <span style={css("height: 5px; border-radius: 999px; background: #2a2a2f; overflow: hidden;")}>
                            <span style={css(s.bar)} />
                          </span>
                        </span>
                        <span style={css("font-family: var(--font-mono); text-align: right;")}>
                          {s.n}
                        </span>
                        <span style={css(s.rateStyle)}>
                          {s.rate}
                        </span>
                      </div>
                    </Fragment>
                  ))}
                </div>
                <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                  {jr.meta}
                </span>
              </div>
            </>
          ) : null}
          {(tRisk) ? (
            <>
              <div style={css("display: flex; align-items: center; gap: 14px;")}>
                <span style={css("font-size: 34px; font-weight: 500; letter-spacing: -1px; color: #c9975a;")}>
                  {"72"}
                </span>
                <span style={css("display: flex; flex-direction: column; gap: 6px; flex: 1;")}>
                  <span style={css("font-size: 12px; color: #a09f99;")}>
                    {"Risk score · elevated · worked out by Aether"}
                  </span>
                  <span style={css("height: 6px; border-radius: 999px; background: #2a2a2f; overflow: hidden;")}>
                    <span style={css("display: block; width: 72%; height: 100%; background: linear-gradient(90deg, #6b9a7c, #c9975a 60%, #b5564a);")} />
                  </span>
                </span>
              </div>
              <div style={css("display: flex; flex-direction: column; gap: 6px;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {"What drives it"}
                </span>
                {(drivers).map((d: any, dIndex: number) => (
                  <Fragment key={dIndex}>
                    <div style={css("display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 8px; font-size: 12px; padding: 8px 10px; border-radius: 8px; background: #1a1a1e; border: 1px solid transparent; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-7f0f7148">
                      <span>
                        {d.x}
                      </span>
                      <span style={css(d.vStyle)}>
                        {d.v}
                      </span>
                    </div>
                  </Fragment>
                ))}
              </div>
              <div style={css("border: 1px solid rgba(58,104,150,0.5); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 8px; background: rgba(58,104,150,0.1);")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #9fbad6;")}>
                  {"◉ Observed · worth a look"}
                </span>
                <span style={css("font-size: 13px;")}>
                  {"Mordred’s message pattern with syn_dxb4 changed. Aether records it; nothing is held or blocked."}
                </span>
                <div style={css("display: flex; flex-wrap: wrap; gap: 6px; align-items: center;")}>
                  {(pending) ? (
                    <>
                      <button type="button" onClick={approve} style={css("font-family: inherit; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; min-height: 32px; padding: 0 14px; border-radius: 999px; font-size: 12px; font-weight: 500; background: #6b9a7c; color: #111114; border: 0; cursor: pointer;")}>
                        {"✓ Mark reviewed"}
                      </button>
                      <button type="button" onClick={decline} style={css("font-family: inherit; display: inline-flex; align-items: center; white-space: nowrap; min-height: 32px; padding: 0 14px; border-radius: 999px; font-size: 12px; font-weight: 500; background: transparent; color: #e8e6e1; border: 1px solid #3a3a40; cursor: pointer;")}>
                        {"⚑ Flag"}
                      </button>
                    </>
                  ) : null}
                  <span style={css(decisionStyle)}>
                    {decision}
                  </span>
                </div>
              </div>
            </>
          ) : null}
          {(tValue) ? (
            <>
              <div style={css("display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 8px;")}>
                <div style={css("border-radius: 10px; padding: 12px; background: rgba(107,154,124,0.12); display: flex; flex-direction: column; gap: 4px; border: 1px solid transparent; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-3defd665">
                  <span style={css("font-size: 20px; font-weight: 500; color: #6b9a7c;")}>
                    {"$18,420"}
                  </span>
                  <span style={css("font-size: 11px; color: #a09f99;")}>
                    {"lifetime value"}
                  </span>
                </div>
                <div style={css("border-radius: 10px; padding: 12px; background: rgba(58,104,150,0.14); display: flex; flex-direction: column; gap: 4px; border: 1px solid transparent; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-3defd665">
                  <span style={css("font-size: 20px; font-weight: 500; color: #9fbad6;")}>
                    {"$14.6K"}
                  </span>
                  <span style={css("font-size: 11px; color: #a09f99;")}>
                    {"via supplier syndicate"}
                  </span>
                </div>
                <div style={css("border-radius: 10px; padding: 12px; background: rgba(201,151,90,0.14); display: flex; flex-direction: column; gap: 4px; border: 1px solid transparent; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-3defd665">
                  <span style={css("font-size: 20px; font-weight: 500; color: #c9975a;")}>
                    {"$1.8K"}
                  </span>
                  <span style={css("font-size: 11px; color: #a09f99;")}>
                    {"agent-sourced"}
                  </span>
                </div>
              </div>
              <div style={css("display: flex; flex-direction: column; gap: 6px;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {"What led to the sale · worked out by Aether"}
                </span>
                {(attribution).map((a: any, aIndex: number) => (
                  <Fragment key={aIndex}>
                    <div style={css("display: grid; grid-template-columns: 22px 96px minmax(0,1fr) 40px; gap: 8px; align-items: center; font-size: 12px; padding: 5px 6px; margin: 0 -6px; border-radius: 4px; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1), color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-de76f755">
                      <span style={css("width: 22px; height: 22px; border-radius: 6px; background: #f5f4f1; display: inline-flex; align-items: center; justify-content: center;")}>
                        <span aria-hidden="true" style={css(`display: block; width: 13px; height: 13px; background: url(${a.logo}) center / contain no-repeat;`)} />
                      </span>
                      <span style={css("font-family: var(--font-mono); color: #a09f99;")}>
                        {a.src}
                      </span>
                      <span style={css("height: 8px; border-radius: 999px; background: #2a2a2f; overflow: hidden;")}>
                        <span style={css(a.bar)} />
                      </span>
                      <span style={css("font-family: var(--font-mono); text-align: right;")}>
                        {a.w}
                      </span>
                    </div>
                  </Fragment>
                ))}
              </div>
            </>
          ) : null}
        </div>
        {(hasNote) ? (
          <>
            <div role="status" style={css("border-top: 1px solid #2a2a2f; padding: 8px 16px; font-family: var(--font-mono); font-size: 11px; color: #9cc4a9; background: rgba(107,154,124,0.08);")}>
              {note}
            </div>
          </>
        ) : null}
        <div style={css("padding: 10px 16px; border-top: 1px solid #2a2a2f; font-family: var(--font-mono); font-size: 11px; color: #a09f99; display: flex; flex-wrap: wrap; gap: 14px; align-items: center;")} className="p360-legend">
          <span style={css("color: #9cc4a9;")}>
            {"◉ live · updated 2h ago"}
          </span>
          <span>
            <span style={css("color: #6b9a7c;")}>
              {"●"}
            </span>
            {" observed"}
          </span>
          <span>
            <span style={css("color: #c9975a;")}>
              {"○"}
            </span>
            {" inferred"}
          </span>
          <span>
            <span style={css("color: #5a85a8;")}>
              {"✓"}
            </span>
            {" approved"}
          </span>
          <span>
            <span style={css("color: #a88a5a;")}>
              {"◉"}
            </span>
            {" outcome"}
          </span>
          <span>
            <span style={css("color: #c9975a;")}>
              {"⬡"}
            </span>
            {" agent"}
          </span>
        </div>
      </div>
    </div>
    </div>
  );
}
