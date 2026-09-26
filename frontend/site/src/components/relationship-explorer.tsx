import { useState, type CSSProperties } from 'react';
import { ACCENTS, tint, type Accent } from '@site/site/palette';

/**
 * The four relationship kinds between people and agents, with a synthetic
 * example of each (Relationship Explorer.dc.html). Used on Olympus Home and
 * Aether Home; reused in /app.
 */

interface Party {
  glyph: '●' | '⬡';
  label: string;
  sub: string;
  agent: boolean;
}

const human = (label: string, sub: string): Party => ({ glyph: '●', label, sub, agent: false });
const agent = (label: string, sub: string): Party => ({ glyph: '⬡', label, sub, agent: true });

type LayerId = 'events' | 'entities' | 'graph' | 'intelligence' | 'governance';

interface RelationshipType {
  id: 'h2h' | 'h2a' | 'a2a' | 'a2h';
  code: string;
  name: string;
  short: string;
  accent: Accent;
  from: Party;
  to: Party;
  verb: string;
  strength: string;
  means: string;
  example: string;
  value: string;
  evidence: string[];
  layers: LayerId[];
}

export const RELATIONSHIP_TYPES: RelationshipType[] = [
  {
    id: 'h2h', code: 'H → H', name: 'Human to human', short: 'collaboration', accent: 'sage',
    from: human('Jane Doe', 'account owner'), to: human('Percival', 'risk analyst'), verb: 'co-approves with', strength: '0.74',
    means: 'People collaborating, communicating, and sharing decisions across teams and organizations.',
    example: 'Jane and Percival co-approve settlement batches above $10k — 14 shared approvals in 90 days, across Slack and the CRM.',
    value: 'Shows who actually decides, and who each decision depends on.',
    evidence: ['approval_recorded ×14', 'slack · shared thread', 'crm · same account'],
    layers: ['events', 'entities', 'graph', 'governance'],
  },
  {
    id: 'h2a', code: 'H → A', name: 'Human to agent', short: 'delegation', accent: 'cobalt',
    from: human('Jane Doe', 'usr_4f21a9'), to: agent('Ptolemy', 'agt_2f18e'), verb: 'delegates to', strength: '0.90',
    means: 'A person hands a task to an agent while keeping the authority behind it.',
    example: 'Jane delegated application scoring to Ptolemy. It takes 42 actions a day, and each one traces back to her grant and scope.',
    value: 'Every agent action stays tied to the human authority that allowed it.',
    evidence: ['delegation_granted', 'agent_tool_called ×42/day', 'scope: scoring.read'],
    layers: ['events', 'entities', 'graph', 'intelligence', 'governance'],
  },
  {
    id: 'a2a', code: 'A → A', name: 'Agent to agent', short: 'orchestration', accent: 'ochre',
    from: agent('Mordred', 'agt_88ce1'), to: agent('Settlement agent', 'external'), verb: 'messages', strength: '0.68',
    means: 'Agents orchestrating, depending on, and handing work to other agents.',
    example: 'Mordred began an unusual message pattern with an external settlement agent that belongs to a flagged cluster. Inferred at 0.88 confidence.',
    value: 'Surfaces machine-to-machine patterns no person would see in a single log.',
    evidence: ['agent_message ×212', 'new counterparty', 'inferred · conf 0.88'],
    layers: ['events', 'graph', 'intelligence'],
  },
  {
    id: 'a2h', code: 'A → H', name: 'Agent to human', short: 'escalation', accent: 'ember',
    from: agent('Mordred', 'agt_88ce1'), to: human('Percival', 'risk analyst'), verb: 'escalates to', strength: '0.81',
    means: 'Agents notifying, recommending, or escalating to people for a decision.',
    example: 'Mordred escalated the pattern to Percival with its evidence attached. The settlement batch is on hold until he decides.',
    value: 'Consequential actions wait for a person, so the loop stays accountable.',
    evidence: ['escalation_created', '▲ review required', 'outcome: pending'],
    layers: ['events', 'intelligence', 'governance'],
  },
];

const LAYERS: Array<[LayerId, string, string, string]> = [
  ['events', '◉', 'Events', 'Ingestion and the operational timeline.'],
  ['entities', '⬡', 'Entities', 'Humans, organizations, agents, devices.'],
  ['graph', '↔', 'Graph', 'Resolution and relationship edges.'],
  ['intelligence', '◈', 'Intelligence', 'Patterns, attribution, and risk.'],
  ['governance', '✓', 'Governance', 'Consent, policy, approval, audit.'],
];

const eyebrow = 'text-label uppercase';

export function RelationshipExplorer() {
  const [selected, setSelected] = useState<RelationshipType['id']>('h2a');
  const cur = RELATIONSHIP_TYPES.find((t) => t.id === selected) ?? RELATIONSHIP_TYPES[1]!;
  const c = ACCENTS[cur.accent];

  const node = (party: Party) => (
    <span
      aria-hidden="true"
      className="flex h-[60px] w-[60px] items-center justify-center font-mono text-[22px] text-ink"
      style={{ borderRadius: party.agent ? 14 : 999, background: c.base, boxShadow: `0 0 0 5px ${tint(cur.accent, 0.16)}` }}
    >
      {party.glyph}
    </span>
  );

  const partyColumn = (party: Party) => (
    <div className="flex flex-col items-center gap-2 text-center">
      {node(party)}
      <span className="text-[14px] font-medium text-bone">{party.label}</span>
      <span className="font-mono text-[11px] text-mist">{party.sub}</span>
    </div>
  );

  return (
    <div className="flex flex-col gap-3 font-sans text-ink">
      <div role="tablist" aria-label="Relationship types" className="flex flex-wrap gap-3">
        {RELATIONSHIP_TYPES.map((t) => {
          const on = t.id === cur.id;
          const tc = ACCENTS[t.accent];
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => setSelected(t.id)}
              className={
                'flex flex-[1_1_200px] cursor-pointer items-center gap-3 rounded-card border px-3.5 py-3 text-left transition-colors duration-120 ease-site ' +
                (on ? 'text-stone-50' : 'border-line bg-stone-100 text-ink hover:[background:var(--tint)] hover:[border-color:var(--base)]')
              }
              style={
                on
                  ? { background: tc.ink, borderColor: tc.ink }
                  : ({ '--tint': tint(t.accent, 0.16), '--base': tc.base } as CSSProperties)
              }
            >
              <span
                className="whitespace-nowrap rounded-lg px-[9px] py-1.5 font-mono text-body-sm font-medium"
                style={{ background: on ? '#f5f4f1' : tint(t.accent, 0.16), color: tc.ink }}
              >
                {t.code}
              </span>
              <span className="flex flex-col items-start gap-0.5">
                <span className="text-[14px] font-medium">{t.name}</span>
                <span className={'font-mono text-[11px] ' + (on ? 'text-stone-50/85' : 'text-slate')}>{t.short}</span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-3">
        <div
          data-theme="dark"
          className="flex min-w-0 flex-[1_1_380px] flex-col gap-[18px] rounded-lg border border-graphite-hairline bg-ink p-6 text-bone"
        >
          <div className="flex items-center justify-between gap-2">
            <span className={`${eyebrow} text-mist`}>Synthetic example</span>
            <span className="rounded-full px-[9px] py-[3px] font-mono text-caption text-ink" style={{ background: c.base }}>
              {cur.code}
            </span>
          </div>
          <div className="grid items-center gap-2 [grid-template-columns:minmax(0,1fr)_minmax(90px,1.2fr)_minmax(0,1fr)]">
            {partyColumn(cur.from)}
            <div className="flex flex-col items-center gap-1.5">
              <span className="text-center text-caption font-medium" style={{ color: c.base }}>
                {cur.verb}
              </span>
              <span
                aria-hidden="true"
                className="h-0.5 w-full rounded-sm"
                style={{ background: `linear-gradient(90deg, ${c.base} 0 88%, transparent 88%)` }}
              />
              <span className="font-mono text-[11px] text-mist">strength {cur.strength}</span>
            </div>
            {partyColumn(cur.to)}
          </div>
          <div className="flex flex-col gap-2 border-t border-graphite-hairline pt-3.5">
            <span className={`${eyebrow} text-mist`}>Evidence on the edge</span>
            <div className="flex flex-wrap gap-1.5">
              {cur.evidence.map((e) => (
                <span key={e} className="rounded-control border border-graphite-hairline bg-graphite-base px-2 py-1 font-mono text-[11px] text-bone">
                  {e}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="flex min-w-0 flex-[1_1_340px] flex-col gap-2">
          <div className="flex flex-col gap-1.5 rounded-lg border border-line bg-stone-100 p-[22px]">
            <span className={`${eyebrow} text-slate`}>What it means</span>
            <span className="text-[15px] leading-[1.55]">{cur.means}</span>
          </div>
          <div className="flex flex-col gap-1.5 rounded-lg border border-line bg-stone-50 p-[22px]">
            <span className={`${eyebrow} text-slate`}>In the example</span>
            <span className="text-[14px] leading-[1.6] text-[#3a3935]">{cur.example}</span>
          </div>
          <div
            className="flex flex-1 flex-col gap-1.5 rounded-lg border p-[22px]"
            style={{ background: tint(cur.accent, 0.16), borderColor: tint(cur.accent, 0.4) }}
          >
            <span className={eyebrow} style={{ color: c.ink }}>
              → What comes from it
            </span>
            <span className="text-[15px] font-medium leading-[1.55] text-ink">{cur.value}</span>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className={`${eyebrow} text-slate`}>Aether layers this relationship uses</span>
        <div className="flex flex-wrap gap-3">
          {LAYERS.map(([id, glyph, name, role]) => {
            const on = cur.layers.includes(id);
            return (
              <div
                key={id}
                data-active={on}
                className={
                  'flex flex-[1_1_160px] flex-col gap-1 rounded-card px-3.5 py-3 transition-[background-color,border-color,opacity] duration-200 ease-site ' +
                  (on ? 'border opacity-100' : 'border border-dashed border-line bg-stone-50 opacity-60')
                }
                style={on ? { background: tint(cur.accent, 0.16), borderColor: c.base } : undefined}
              >
                <span aria-hidden="true" className="font-mono text-[16px]" style={{ color: on ? c.ink : '#9c9b95' }}>
                  {glyph}
                </span>
                <span className="text-body-sm font-medium">{name}</span>
                <span className="text-caption leading-[1.45] text-slate">{role}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
