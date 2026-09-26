import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ProviderMark } from '@site/components/provider-mark';
import { BrandMark } from '@site/components/brand-mark';

/**
 * Profile 360.dc.html: an interactive, synthetic profile (Jane Doe) that shows
 * how one entity looks once Aether joins its sources. Every value is
 * illustrative; the header says so. Embedded on Aether Home, reused in /app.
 */

type Tab = 'overview' | 'rels' | 'journeys' | 'risk' | 'value';
type Filter = 'all' | 'humans' | 'agents' | 'syndicates';
type JourneyId = 'ig' | 'x';

type BrandSlug = 'hubspot' | 'instagram' | 'phantom' | 'shopify' | 'stripe' | 'x';

const TABS: Array<[Tab, string, string, string]> = [
  ['overview', '◈', 'Overview', '#5a85a8'],
  ['rels', '↔', 'Relationships', '#6b9a7c'],
  ['journeys', '→', 'Journeys', '#a88a5a'],
  ['risk', '▲', 'Risk', '#c9975a'],
  ['value', '↑', 'Value', '#6b9a7c'],
];

const AGENT = { Ptolemy: '#3a6896', Kierkegaard: '#5a85a8', Mordred: '#c9975a' };

interface Relationship {
  key: string;
  glyph: '⬡' | '●' | '◈';
  name: string;
  id: string;
  role: string;
  kind: string;
  type: Exclude<Filter, 'all'>;
  color: string;
  risk: number;
  desc: string;
  facts: string[];
  actions?: Array<[glyph: string, color: string, text: string, when: string]>;
  members?: Array<[glyph: string, name: string, color: string]>;
}

export const RELATIONSHIPS: Relationship[] = [
  { key: 'ptolemy', glyph: '⬡', name: 'Ptolemy', id: 'agt_2f18e', role: 'delegated agent', kind: 'H→A', type: 'agents', color: AGENT.Ptolemy, risk: 28, desc: 'Scores incoming supplier applications on Jane’s behalf and flags exceptions to Osiris.', facts: ['42 actions/day', 'strength 0.90', 'scope: scoring.read'],
    actions: [['✓', '#6b9a7c', 'Scored application app_71c · 0.82', '1h'], ['→', '#9fbad6', 'Flagged exception to Osiris', '5h'], ['✓', '#6b9a7c', 'Onboarded supplier to SF syndicate', '2d']] },
  { key: 'kierkegaard', glyph: '⬡', name: 'Kierkegaard', id: 'agt_5c02f', role: 'delegated agent', kind: 'H→A', type: 'agents', color: AGENT.Kierkegaard, risk: 31, desc: 'Audits cross-border settlement records for irregularities.', facts: ['9 actions/day', '$1.8K value', 'strength 0.82'],
    actions: [['◉', '#a88a5a', 'Audited Stripe payout po_9x2 · clean', '3h'], ['✓', '#6b9a7c', 'Reconciled 14 settlements', '1d']] },
  { key: 'mordred', glyph: '⬡', name: 'Mordred', id: 'agt_88ce1', role: 'flagged relationship', kind: 'A→A', type: 'agents', color: AGENT.Mordred, risk: 91, desc: 'Unusual message pattern with an external settlement agent inside a flagged cluster. Escalated to Percival.', facts: ['conf 0.88', '212 messages', 'strength 0.68'],
    actions: [['↔', '#c9975a', 'Messaged external agent in syn_dxb4 ×212', '6h'], ['▲', '#b5564a', 'Escalated pattern to Percival', '6h'], ['■', '#b5564a', 'Percival held the next settlement batch · observed', 'now']] },
  { key: 'percival', glyph: '●', name: 'Percival', id: 'usr_91b2c', role: 'risk analyst', kind: 'H→H', type: 'humans', color: '#6b9a7c', risk: 12, desc: 'Co-approves settlement batches with Jane. Receives Mordred’s escalations.', facts: ['14 shared approvals', 'slack · crm', 'strength 0.74'] },
  { key: 'osiris', glyph: '●', name: 'Osiris', id: 'usr_c33a0', role: 'compliance', kind: 'H→H', type: 'humans', color: '#6b9a7c', risk: 18, desc: 'Reviews policy exceptions raised by Ptolemy.', facts: ['6 reviews', 'strength 0.52'] },
  { key: 'maya', glyph: '●', name: 'Maya Chen', id: 'usr_a81d3', role: 'referred by Jane', kind: 'H→H', type: 'humans', color: '#6b9a7c', risk: 9, desc: 'Joined through Jane’s referral link on X. Now a repeat buyer.', facts: ['referral', '$2.1K value', '3 orders'] },
  { key: 'supplier', glyph: '◈', name: 'SF supplier syndicate', id: 'syn_sf01', role: '5 humans · 2 agents', kind: 'cluster', type: 'syndicates', color: '#a88a5a', risk: 36, desc: 'Supplier network run through Ptolemy. Most common path: sourced → contracted → active.', facts: ['$14.6K value', '11 journeys'],
    members: [['●', 'Jane Doe', '#6b9a7c'], ['●', 'Osiris', '#6b9a7c'], ['●', '+3 suppliers', '#6b9a7c'], ['⬡', 'Ptolemy', AGENT.Ptolemy], ['⬡', 'Kierkegaard', AGENT.Kierkegaard]] },
  { key: 'settlement', glyph: '◈', name: 'Settlement syndicate', id: 'syn_dxb4', role: '2 humans · 3 agents', kind: 'cluster', type: 'syndicates', color: '#b5564a', risk: 84, desc: 'Flagged cluster in Dubai. Mordred communicates with one of its agents.', facts: ['flagged', '2 hops from Jane'],
    members: [['●', '2 unknown humans', '#a09f99'], ['⬡', 'agt_x41 (external)', '#b5564a'], ['⬡', '+2 agents', '#b5564a']] },
];

interface Journey {
  label: string;
  logo: BrandSlug;
  name: string;
  campaign: string;
  status: string;
  color: string;
  kpis: Array<[value: string, label: string, color: string]>;
  steps: Array<[label: string, source: BrandSlug, count: number, rate: string, date: string]>;
  meta: string;
}

const JOURNEYS: Record<JourneyId, Journey> = {
  ig: { label: 'Instagram · Spring Drop', logo: 'instagram', name: 'Paid social → first purchase', campaign: 'campaign:cmp_spring26 · Instagram Reels + Stories', status: '● converted', color: '#6b9a7c',
    kpis: [['$38.20', 'CAC', '#9cc4a9'], ['5.3%', 'click → purchase', '#9fbad6'], ['3.4×', 'ROAS', '#c9975a'], ['$2,330', 'spend', '#e8e6e1']],
    steps: [['Reel impression', 'instagram', 48200, '100%', 'Mar 9'], ['Link click', 'instagram', 1157, '2.4%', 'Mar 9'], ['Product view', 'shopify', 812, '70.2%', 'Mar 9'], ['Add to cart', 'shopify', 204, '25.1%', 'Mar 10'], ['Checkout started', 'stripe', 96, '47.1%', 'Mar 12'], ['Paid · $4,200', 'stripe', 61, '63.5%', 'Mar 12']],
    meta: 'journey:jrn_ig_01 · sources instagram, shopify, stripe · attribution 0.34 to campaign' },
  x: { label: 'X · Creator referral', logo: 'x', name: 'Creator post → subscription', campaign: 'campaign:cmp_creator_x · referral thread on X', status: '▲ renewal at risk', color: '#c9975a',
    kpis: [['$52.10', 'CAC', '#9cc4a9'], ['3.1%', 'visit → paid', '#9fbad6'], ['$18.4K', 'LTV', '#c9975a'], ['353×', 'LTV / CAC', '#e8e6e1']],
    steps: [['Creator post', 'x', 22400, '100%', 'Feb 2'], ['Landing visit', 'x', 1840, '8.2%', 'Feb 2'], ['Lead captured', 'hubspot', 410, '22.3%', 'Feb 3'], ['Nurture email opened', 'hubspot', 236, '57.6%', 'Feb 6'], ['Demo booked', 'hubspot', 92, '39.0%', 'Feb 9'], ['Subscribed · Beta', 'stripe', 57, '62.0%', 'Feb 14']],
    meta: 'journey:jrn_x_02 · sources x, hubspot, stripe · referral edge → Maya Chen' },
};

const STEP_COLORS = ['#3a6896', '#5a85a8', '#6b9a7c', '#a88a5a', '#c9975a', '#6b9a7c'];

const SEARCH_INDEX: Array<[label: string, where: string, tab: Tab, filter: Filter | null]> = [
  ['Ptolemy · delegated agent', 'relationships', 'rels', 'agents'],
  ['Mordred · flagged', 'relationships', 'rels', 'agents'],
  ['Percival · risk analyst', 'relationships', 'rels', 'humans'],
  ['Settlement syndicate', 'relationships', 'rels', 'syndicates'],
  ['Instagram · Spring Drop', 'journeys', 'journeys', null],
  ['X · creator referral', 'journeys', 'journeys', null],
  ['Risk score 72', 'risk', 'risk', null],
  ['Lifetime value $18,420', 'value', 'value', null],
];

const ACCOUNTS: Array<[BrandSlug, string, string, string]> = [
  ['stripe', 'Stripe', 'cus_Q8…4f', 'Billing customer'],
  ['hubspot', 'HubSpot', 'contact 9812', 'CRM contact'],
  ['x', 'X', '@janedoe', 'Social'],
  ['instagram', 'Instagram', '@jane.makes', 'Social'],
  ['phantom', 'Phantom', '7xKX…9fQm', 'Wallet'],
  ['shopify', 'Shopify', '3 orders', 'Commerce'],
];

const TIMELINE: Array<{ logo?: BrandSlug; agent?: string; glyph?: [string, string]; text: string; when: string }> = [
  { logo: 'stripe', text: 'stripe · invoice.paid · $4,200', when: '2h' },
  { agent: AGENT.Mordred, text: 'Mordred ↔ syn_dxb4 · 212 messages', when: '6h' },
  { agent: AGENT.Ptolemy, text: 'Ptolemy · scored app_71c · 0.82', when: '1h' },
  { logo: 'instagram', text: 'instagram · reel click · cmp_spring26', when: '1d' },
  { logo: 'hubspot', text: 'hubspot · lifecycle → customer', when: '2d' },
  { glyph: ['✓', '#5a85a8'], text: 'approval · batch_0912 · Percival', when: '3d' },
];

const DRIVERS: Array<[string, string, string]> = [
  ['Agent Mordred linked to flagged syndicate (2 hops)', '+31', '#b5564a'],
  ['Cross-border settlement velocity ↑ 3.1×', '+18', '#c9975a'],
  ['New counterparty in 7 days', '+9', '#c9975a'],
  ['Verified identity across 6 sources', '−12', '#6b9a7c'],
];

const ATTRIBUTION: Array<[BrandSlug, string, number, string]> = [
  ['instagram', 'instagram', 0.34, '#E4405F'],
  ['x', 'x · referral', 0.26, '#9fbad6'],
  ['hubspot', 'hubspot', 0.22, '#FF7A59'],
  ['shopify', 'shopify', 0.18, '#6b9a7c'],
];

const riskColor = (n: number) => (n >= 80 ? '#b5564a' : n >= 50 ? '#c9975a' : '#6b9a7c');
const eyebrow = 'text-label uppercase text-mist';
const panel = 'flex flex-col gap-[7px] rounded-control border border-graphite-hairline p-3 transition-colors duration-120 ease-site hover:border-[#3a3a40] hover:bg-[#16161a]';

function Mark({ slug, size = 22, round = false }: { slug: BrandSlug; size?: 20 | 22 | 26; round?: boolean }) {
  const inner = size === 26 ? 15 : size === 22 ? 13 : 12;
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center bg-stone-50 ${round ? 'rounded-full' : size === 26 ? 'rounded-lg' : 'rounded-control'}`}
      style={{ width: size, height: size }}
    >
      <ProviderMark provider={slug} size={inner} className="text-graphite-body" />
    </span>
  );
}

export function Profile360() {
  const [tab, setTab] = useState<Tab>('overview');
  const [filter, setFilter] = useState<Filter>('all');
  const [open, setOpen] = useState<string | null>('mordred');
  const [decision, setDecision] = useState<'approved' | 'declined' | null>(null);
  const [journey, setJourney] = useState<JourneyId>('ig');
  const [watching, setWatching] = useState(false);
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState('');
  const [note, setNote] = useState('');
  const noteTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => () => clearTimeout(noteTimer.current), []);
  useEffect(() => {
    if (searching) searchRef.current?.focus();
  }, [searching]);

  const flash = (text: string) => {
    clearTimeout(noteTimer.current);
    setNote(text);
    noteTimer.current = setTimeout(() => setNote(''), 2600);
  };

  const q = query.trim().toLowerCase();
  const hits = (q ? SEARCH_INDEX.filter(([label]) => label.toLowerCase().includes(q)) : SEARCH_INDEX.slice(0, 4)).map(
    ([label, where, t, f]) => ({
      label,
      where,
      go: () => {
        setTab(t);
        if (f) setFilter(f);
        setSearching(false);
        setQuery('');
      },
    }),
  );

  const onSearchKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      setSearching(false);
      setQuery('');
    }
    if (e.key === 'Enter') hits[0]?.go();
  };

  const onRootKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      setSearching(true);
    }
  };

  const counts: Record<Filter, number> = {
    all: RELATIONSHIPS.length,
    humans: RELATIONSHIPS.filter((r) => r.type === 'humans').length,
    agents: RELATIONSHIPS.filter((r) => r.type === 'agents').length,
    syndicates: RELATIONSHIPS.filter((r) => r.type === 'syndicates').length,
  };
  const shown = RELATIONSHIPS.filter((r) => filter === 'all' || r.type === filter);
  const jr = JOURNEYS[journey];
  const maxCount = jr.steps[0]![2];

  const headAction = (glyph: string, label: string, onClick: () => void, variant: 'primary' | 'default' | 'on') => (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={variant === 'on' ? true : label === 'Watch' ? false : undefined}
      className={
        'inline-flex min-h-7 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded border px-2.5 text-caption font-medium transition-colors duration-120 ease-site ' +
        (variant === 'on'
          ? 'border-steel bg-steel/20 text-[#9fbad6]'
          : variant === 'primary'
            ? 'border-bone bg-bone text-ink hover:border-line hover:bg-line'
            : 'border-graphite-hairline bg-ink text-bone hover:border-[#3a3a40] hover:bg-graphite-hover')
      }
    >
      <span aria-hidden="true" className="font-mono">
        {glyph}
      </span>
      {label}
    </button>
  );

  return (
    <div className="flex min-w-0 flex-col font-sans" onKeyDown={onRootKey}>
      <div data-theme="dark" className="flex items-center gap-2.5 rounded-t-lg border border-b-0 border-graphite-hairline bg-ink px-2.5 py-2 text-caption text-bone">
        <span className="flex min-w-0 items-center gap-1.5 whitespace-nowrap">
          <BrandMark brand="aether" className="h-4 w-4" />
          <span className="text-mist">360</span>
          <span className="text-slate">/</span>
          <span className="font-medium">Jane Doe</span>
        </span>
        <button
          type="button"
          onClick={() => setSearching((v) => !v)}
          aria-expanded={searching}
          className="ml-auto flex min-h-7 min-w-0 max-w-[260px] flex-1 cursor-pointer items-center justify-between gap-2 rounded border border-graphite-hairline bg-graphite-base px-2 text-caption text-mist transition-colors duration-120 ease-site hover:border-[#3a3a40] hover:text-bone"
        >
          <span className="flex gap-1.5 overflow-hidden whitespace-nowrap">
            <span aria-hidden="true" className="font-mono">
              ⌕
            </span>
            Search this profile
          </span>
          <kbd className="rounded-[3px] border border-graphite-hairline px-1 font-mono text-[10px]">⌘K</kbd>
        </button>
        <span
          title="Illustrative data — not a customer record"
          className="whitespace-nowrap rounded-full border border-dashed border-[#3a3a40] px-[7px] py-0.5 font-mono text-[10px] text-mist"
        >
          synthetic
        </span>
      </div>

      <div data-theme="dark" className="overflow-hidden rounded-b-lg border border-graphite-hairline bg-graphite-base text-body-sm text-bone">
        {searching && (
          <div className="flex flex-col gap-1 border-b border-graphite-hairline bg-[#16161a] px-3 py-2.5">
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onSearchKey}
              placeholder="Search relationships, agents, journeys"
              aria-label="Search this profile"
              className="min-h-8 rounded border border-[#3a3a40] bg-graphite-base px-2.5 text-body-sm text-bone outline-none placeholder:text-mist"
            />
            {hits.map((h) => (
              <button
                key={h.label}
                type="button"
                onClick={h.go}
                className="flex cursor-pointer justify-between gap-2 rounded border-0 bg-transparent px-2.5 py-[7px] text-left text-caption text-bone hover:bg-graphite-hover"
              >
                <span>{h.label}</span>
                <span className="font-mono text-[11px] text-mist">{h.where}</span>
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-col gap-3 border-b border-graphite-hairline bg-[#141418] p-4">
          <div className="flex items-center gap-3">
            <span className="relative h-[52px] w-[52px] shrink-0">
              <span className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-cobalt text-[17px] font-medium text-stone-50 shadow-[0_0_0_3px_rgba(58,104,150,0.35)]">
                JD
              </span>
              <span className="absolute -bottom-0.5 -right-0.5 h-3.5 w-3.5 rounded-full border-2 border-graphite-base bg-sage" />
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-[17px] font-medium">Jane Doe</span>
                <span className="rounded-full bg-sage/20 px-2 py-0.5 text-[11px] font-medium text-mint">VIP · Beta</span>
              </span>
              <span className="font-mono text-[11px] text-mist">entity:usr_4f21a9 · San Francisco, US · GMT-7</span>
            </span>
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-ochre/20 px-[9px] py-[3px] font-mono text-[11px] text-ochre">
              ▲ risk 72
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {headAction('↔', 'Open in graph', () => setTab('rels'), 'primary')}
            {headAction(watching ? '●' : '○', watching ? 'Watching' : 'Watch', () => {
              setWatching(!watching);
              flash(watching ? '○ stopped watching Jane Doe' : '● watching Jane Doe · alerts on new risk evidence');
            }, watching ? 'on' : 'default')}
            {headAction('⇩', 'Export', () => flash('⇩ export queued · profiles:usr_4f21a9.jsonl'), 'default')}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {ACCOUNTS.map(([slug, name, handle, title]) => (
              <button
                key={slug}
                type="button"
                title={title}
                onClick={() => flash(`↔ ${name} · ${handle} · ${title.toLowerCase()}`)}
                className="inline-flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border border-graphite-hairline bg-ink py-[3px] pl-[3px] pr-[9px] text-[11px] text-bone transition-colors duration-120 ease-site hover:border-[#3a3a40] hover:bg-graphite-hover"
              >
                <Mark slug={slug} size={20} round />
                <span className="font-medium">{name}</span>
                <span className="font-mono text-mist">{handle}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-4 border-b border-graphite-hairline">
          {([
            ['$18.4K', 'value', '#6b9a7c', 'value'],
            ['8', 'relationships', '#9fbad6', 'rels'],
            ['3', 'agents', '#c9975a', 'rels'],
            ['2', 'journeys', '#a88a5a', 'journeys'],
          ] as Array<[string, string, string, Tab]>).map(([v, k, color, t]) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(t)}
              className="flex cursor-pointer flex-col items-start gap-0.5 border-0 border-r border-graphite-hairline bg-transparent px-3 py-2.5 text-bone last:border-r-0 hover:bg-ink"
            >
              <span className="text-[17px] font-medium" style={{ color }}>
                {v}
              </span>
              <span className="text-[11px] text-mist">{k}</span>
            </button>
          ))}
        </div>

        <div role="tablist" aria-label="Profile sections" className="flex gap-0.5 overflow-x-auto border-b border-graphite-hairline px-2">
          {TABS.map(([id, glyph, label, color]) => {
            const on = tab === id;
            return (
              <button
                key={id}
                type="button"
                role="tab"
                id={`p360-tab-${id}`}
                aria-selected={on}
                aria-controls="p360-panel"
                onClick={() => setTab(id)}
                className={`inline-flex cursor-pointer items-center gap-1.5 whitespace-nowrap border-0 border-b-2 bg-transparent p-2.5 text-caption font-medium hover:text-bone ${on ? 'text-bone' : 'text-mist'}`}
                style={{ borderBottomColor: on ? color : 'transparent' }}
              >
                <span aria-hidden="true" className="font-mono" style={{ color }}>
                  {glyph}
                </span>
                {label}
              </button>
            );
          })}
        </div>

        <div id="p360-panel" role="tabpanel" aria-labelledby={`p360-tab-${tab}`} className="flex min-h-[320px] flex-col gap-3 px-4 py-3.5">
          {tab === 'overview' && (
            <>
              <div className="grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr))]">
                <div className={panel}>
                  <span className={eyebrow}>Identity and contact</span>
                  <span className="font-mono text-caption">j••••e@example.com</span>
                  <span className="font-mono text-caption">+1 (415) •••-••42</span>
                  <span className="flex items-center gap-1.5 font-mono text-caption">
                    <ProviderMark provider="phantom" size={16} className="rounded-control bg-stone-50 text-graphite-body" />
                    Phantom <span className="text-mist">7xKX…9fQm</span>
                  </span>
                </div>
                <div className={panel}>
                  <span className={eyebrow}>Sources and consent</span>
                  <span className="flex flex-wrap gap-[5px]">
                    {(['stripe', 'hubspot', 'x', 'instagram', 'shopify'] as BrandSlug[]).map((slug) => (
                      <span key={slug} title={slug}>
                        <Mark slug={slug} size={26} />
                      </span>
                    ))}
                    <span title="Web SDK" className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-lg bg-sage/20 font-mono text-caption text-mint">
                      ⌘
                    </span>
                  </span>
                  <span className="font-mono text-caption">
                    <span className="text-sage">✓</span> analytics <span className="ml-1.5 text-sage">✓</span> marketing
                  </span>
                  <span className="font-mono text-[11px] text-mist">fresh 2h · 6 sources · tenant:sandbox</span>
                </div>
              </div>
              <div className="flex flex-col gap-1.5 rounded-[10px] border border-ochre/45 bg-ochre/[0.08] p-3">
                <span className="text-label uppercase text-ochre">○ What the graph found</span>
                <span className="text-body-sm leading-[1.55]">
                  A high-value customer is two hops from a flagged settlement cluster, through an agent acting on her behalf. No
                  single source shows this.
                </span>
                <button
                  type="button"
                  onClick={() => setTab('risk')}
                  className="inline-flex min-h-[30px] cursor-pointer items-center gap-1.5 self-start whitespace-nowrap rounded-full border-0 bg-ochre px-3 text-caption font-medium text-ink"
                >
                  See why
                  <span aria-hidden="true" className="font-mono">
                    →
                  </span>
                </button>
              </div>
              <div className="flex flex-col gap-[7px]">
                <span className={eyebrow}>Recent evidence</span>
                {TIMELINE.map((e) => (
                  <div
                    key={e.text}
                    className="-mx-1.5 grid items-center gap-2 rounded px-1.5 py-[5px] font-mono text-caption hover:bg-ink [grid-template-columns:22px_minmax(0,1fr)_auto]"
                  >
                    {e.logo && <Mark slug={e.logo} />}
                    {e.agent && (
                      <span className="inline-flex h-[22px] w-[22px] items-center justify-center rounded-control text-caption text-graphite-base" style={{ background: e.agent }}>
                        ⬡
                      </span>
                    )}
                    {e.glyph && (
                      <span className="w-[22px] text-center" style={{ color: e.glyph[1] }}>
                        {e.glyph[0]}
                      </span>
                    )}
                    <span className="overflow-hidden text-ellipsis whitespace-nowrap">{e.text}</span>
                    <span className="text-mist">{e.when}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {tab === 'rels' && (
            <>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter relationships">
                {(['all', 'humans', 'agents', 'syndicates'] as Filter[]).map((f) => (
                  <button
                    key={f}
                    type="button"
                    aria-pressed={filter === f}
                    onClick={() => setFilter(f)}
                    className={
                      'min-h-7 cursor-pointer rounded-full border px-[11px] text-caption font-medium ' +
                      (filter === f ? 'border-bone bg-bone text-graphite-base' : 'border-graphite-hairline bg-transparent text-bone')
                    }
                  >
                    {f[0]!.toUpperCase() + f.slice(1)} <span className="opacity-70">{counts[f]}</span>
                  </button>
                ))}
              </div>
              <div className="flex flex-col overflow-hidden rounded-[10px] border border-graphite-hairline">
                {shown.map((r, i) => {
                  const isOpen = open === r.key;
                  return (
                    <div key={r.key}>
                      <button
                        type="button"
                        aria-expanded={isOpen}
                        onClick={() => setOpen(isOpen ? null : r.key)}
                        className={`flex w-full cursor-pointer items-center gap-2.5 border-0 px-3 py-[9px] text-inherit transition-colors duration-120 hover:bg-ink ${isOpen ? 'bg-ink' : 'bg-transparent'} ${i ? 'border-t border-graphite-hairline' : ''}`}
                      >
                        <span
                          aria-hidden="true"
                          className={`flex h-[30px] w-[30px] shrink-0 items-center justify-center font-mono text-[14px] text-graphite-base ${r.glyph === '●' ? 'rounded-full' : 'rounded-lg'}`}
                          style={{ background: r.color }}
                        >
                          {r.glyph}
                        </span>
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5 text-left">
                          <span className="text-body-sm font-medium text-bone">{r.name}</span>
                          <span className="overflow-hidden text-ellipsis whitespace-nowrap font-mono text-[11px] text-mist">
                            {r.id} · {r.role}
                          </span>
                        </span>
                        <span className="whitespace-nowrap rounded-control border px-[7px] py-0.5 font-mono text-[11px]" style={{ color: r.color, borderColor: `${r.color}66` }}>
                          {r.kind}
                        </span>
                        <span className="min-w-[52px] whitespace-nowrap text-right font-mono text-[11px]" style={{ color: riskColor(r.risk) }}>
                          risk {r.risk}
                        </span>
                      </button>
                      {isOpen && (
                        <div
                          className="flex flex-col gap-2 border-t border-graphite-hairline bg-[#16161a] pb-3 pl-[50px] pr-3 pt-2.5"
                          style={{ boxShadow: `inset 2px 0 0 ${r.color}` }}
                        >
                          <span className="text-body-sm leading-[1.55] text-bone">{r.desc}</span>
                          <div className="flex flex-wrap gap-1.5">
                            {r.facts.map((k) => (
                              <span key={k} className="rounded-control border border-graphite-hairline bg-ink px-[7px] py-[3px] font-mono text-[11px] text-bone">
                                {k}
                              </span>
                            ))}
                          </div>
                          {r.actions && (
                            <div className="flex flex-col gap-[5px] pt-1">
                              <span className={eyebrow}>What it has done</span>
                              {r.actions.map(([g, color, text, when]) => (
                                <div key={text} className="grid items-baseline gap-2 text-caption [grid-template-columns:16px_minmax(0,1fr)_auto]">
                                  <span aria-hidden="true" className="font-mono" style={{ color }}>
                                    {g}
                                  </span>
                                  <span>{text}</span>
                                  <span className="font-mono text-[11px] text-mist">{when}</span>
                                </div>
                              ))}
                            </div>
                          )}
                          {r.members && (
                            <div className="flex flex-wrap gap-[5px] pt-1">
                              {r.members.map(([g, n, color]) => (
                                <span key={n} className="rounded-full border bg-ink px-2 py-[3px] font-mono text-[11px] text-bone" style={{ borderColor: `${color}66` }}>
                                  {g} {n}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {tab === 'journeys' && (
            <>
              <div className="flex gap-1.5" role="group" aria-label="Journeys">
                {(Object.entries(JOURNEYS) as Array<[JourneyId, Journey]>).map(([id, j]) => (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={journey === id}
                    onClick={() => setJourney(id)}
                    className={
                      'inline-flex min-h-[30px] cursor-pointer items-center gap-[7px] whitespace-nowrap rounded-full border py-0 pl-[5px] pr-[11px] text-caption font-medium ' +
                      (journey === id ? 'border-bone bg-bone text-graphite-base' : 'border-graphite-hairline bg-transparent text-bone')
                    }
                  >
                    <span className="rounded-full shadow-[0_0_0_1px_#d8d6d0]">
                      <Mark slug={j.logo} size={20} round />
                    </span>
                    {j.label}
                  </button>
                ))}
              </div>
              <div className={`${panel} gap-3`}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="flex flex-col gap-0.5">
                    <span className="text-[14px] font-medium">{jr.name}</span>
                    <span className="font-mono text-[11px] text-mist">{jr.campaign}</span>
                  </span>
                  <span className="font-mono text-[11px]" style={{ color: jr.color }}>
                    {jr.status}
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-1.5">
                  {jr.kpis.map(([v, k, color]) => (
                    <div key={k} className="flex flex-col gap-0.5 rounded-lg bg-ink p-2">
                      <span className="text-[15px] font-medium" style={{ color }}>
                        {v}
                      </span>
                      <span className="text-[10px] text-mist">{k}</span>
                    </div>
                  ))}
                </div>
                <div className="flex flex-col gap-[5px]">
                  {jr.steps.map(([label, source, count, rate, date], i) => (
                    <div
                      key={label}
                      className="-mx-1.5 grid items-center gap-2 rounded px-1.5 py-[5px] text-caption hover:bg-ink [grid-template-columns:22px_minmax(0,1fr)_64px_50px]"
                    >
                      <Mark slug={source} />
                      <span className="flex min-w-0 flex-col gap-[3px]">
                        <span className="flex items-baseline gap-1.5">
                          <span className="font-medium">{label}</span>
                          <span className="font-mono text-[10px] text-[#9fbad6]">● Jane · {date}</span>
                        </span>
                        <span className="h-[5px] overflow-hidden rounded-full bg-graphite-hairline">
                          <span
                            className="block h-full"
                            style={{ width: `${Math.max(2, Math.sqrt(count / maxCount) * 100)}%`, background: STEP_COLORS[i] }}
                          />
                        </span>
                      </span>
                      <span className="text-right font-mono">{count.toLocaleString('en-US')}</span>
                      <span className={`text-right font-mono text-[11px] ${i === 0 ? 'text-mist' : 'text-mint'}`}>{rate}</span>
                    </div>
                  ))}
                </div>
                <span className="font-mono text-[11px] text-mist">{jr.meta}</span>
              </div>
            </>
          )}

          {tab === 'risk' && (
            <>
              <div className="flex items-center gap-3.5">
                <span className="text-[34px] font-medium tracking-[-1px] text-ochre">72</span>
                <span className="flex flex-1 flex-col gap-1.5">
                  <span className="text-caption text-mist">Risk score · elevated · inferred</span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-graphite-hairline">
                    <span className="block h-full w-[72%] bg-[linear-gradient(90deg,#6b9a7c,#c9975a_60%,#b5564a)]" />
                  </span>
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className={eyebrow}>What drives it</span>
                {DRIVERS.map(([text, v, color]) => (
                  <div
                    key={text}
                    className="grid gap-2 rounded-lg border border-transparent bg-ink px-2.5 py-2 text-caption hover:border-[#3a3a40] hover:bg-graphite-hover [grid-template-columns:minmax(0,1fr)_auto]"
                  >
                    <span>{text}</span>
                    <span className="font-mono" style={{ color }}>
                      {v}
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-2 rounded-[10px] border border-cobalt/50 bg-cobalt/10 p-3">
                <span className="text-label uppercase text-[#9fbad6]">◉ Observed · worth a look</span>
                <span className="text-body-sm">Mordred’s message pattern with syn_dxb4 changed. Aether records it; nothing is held or blocked.</span>
                <div className="flex flex-wrap items-center gap-1.5">
                  {!decision && (
                    <>
                      <button
                        type="button"
                        onClick={() => setDecision('approved')}
                        className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border-0 bg-sage px-3.5 text-caption font-medium text-graphite-base"
                      >
                        ✓ Mark reviewed
                      </button>
                      <button
                        type="button"
                        onClick={() => setDecision('declined')}
                        className="inline-flex min-h-8 cursor-pointer items-center whitespace-nowrap rounded-full border border-[#3a3a40] bg-transparent px-3.5 text-caption font-medium text-bone"
                      >
                        ⚑ Flag
                      </button>
                    </>
                  )}
                  <span
                    role="status"
                    className={`font-mono text-[11px] ${decision === 'approved' ? 'text-sage' : decision === 'declined' ? 'text-ember' : 'text-mist'}`}
                  >
                    {decision === 'approved' ? '✓ reviewed by you · just now' : decision === 'declined' ? '⚑ flagged for follow-up' : 'not yet reviewed'}
                  </span>
                </div>
              </div>
            </>
          )}

          {tab === 'value' && (
            <>
              <div className="grid grid-cols-3 gap-2">
                {([
                  ['$18,420', 'lifetime value', '#6b9a7c', 'rgba(107,154,124,0.12)'],
                  ['$14.6K', 'via supplier syndicate', '#9fbad6', 'rgba(58,104,150,0.14)'],
                  ['$1.8K', 'agent-sourced', '#c9975a', 'rgba(201,151,90,0.14)'],
                ] as const).map(([v, k, color, bg]) => (
                  <div key={k} className="flex flex-col gap-1 rounded-[10px] border border-transparent p-3 hover:border-[#3a3a40]" style={{ background: bg }}>
                    <span className="text-[20px] font-medium" style={{ color }}>
                      {v}
                    </span>
                    <span className="text-[11px] text-mist">{k}</span>
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-1.5">
                <span className={eyebrow}>Attribution path · inferred</span>
                {ATTRIBUTION.map(([slug, src, w, color]) => (
                  <div key={src} className="-mx-1.5 grid items-center gap-2 rounded px-1.5 py-[5px] text-caption hover:bg-ink [grid-template-columns:22px_96px_minmax(0,1fr)_40px]">
                    <Mark slug={slug} />
                    <span className="font-mono text-mist">{src}</span>
                    <span className="h-2 overflow-hidden rounded-full bg-graphite-hairline">
                      <span className="block h-full max-w-full" style={{ width: `${w * 250}%`, background: color }} />
                    </span>
                    <span className="text-right font-mono">{w.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {note && (
          <div role="status" className="border-t border-graphite-hairline bg-sage/[0.08] px-4 py-2 font-mono text-[11px] text-mint">
            {note}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3.5 border-t border-graphite-hairline px-4 py-2.5 font-mono text-[11px] text-mist">
          <span className="text-mint">◉ live · updated 2h ago</span>
          <span>
            <span className="text-sage">●</span> observed
          </span>
          <span>
            <span className="text-ochre">○</span> inferred
          </span>
          <span>
            <span className="text-steel">✓</span> approved
          </span>
          <span>
            <span className="text-solar">◉</span> outcome
          </span>
          <span>
            <span className="text-ochre">⬡</span> agent
          </span>
        </div>
      </div>
    </div>
  );
}
