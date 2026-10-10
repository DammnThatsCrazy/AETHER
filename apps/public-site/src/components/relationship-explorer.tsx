/**
 * Built from design/designs/Relationship Explorer.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, hoverClass, useDesignState } from '@site/design/runtime';

import './relationship-explorer.css';

type Tone = [base: string, ink: string, soft: string];
interface Endpoint {
  g: string;
  label: string;
  sub: string;
  agent: boolean;
}
interface RelType {
  id: string;
  code: string;
  name: string;
  short: string;
  c: Tone;
  from: Endpoint;
  to: Endpoint;
  verb: string;
  strength: string;
  means: string;
  example: string;
  value: string;
  evidence: string[];
  layers: string[];
}

const TONES: Record<'sage' | 'cobalt' | 'ochre' | 'ember', Tone> = {
  sage: ['#6b9a7c', '#4f7a5e', 'rgba(107,154,124,0.16)'],
  cobalt: ['#3a6896', '#2d5373', 'rgba(58,104,150,0.14)'],
  ochre: ['#c9975a', '#8a6433', 'rgba(201,151,90,0.18)'],
  ember: ['#b5564a', '#a3473c', 'rgba(181,86,74,0.14)'],
};
const H = (label: string, sub: string): Endpoint => ({ g: '●', label, sub, agent: false });
const A = (label: string, sub: string): Endpoint => ({ g: '⬡', label, sub, agent: true });

export const RELATIONSHIP_TYPES: RelType[] = [
  { id: 'h2h', code: 'H → H', name: 'Human to human', short: 'working together', c: TONES.sage, from: H('Jane Doe', 'account owner'), to: H('Percival', 'risk analyst'), verb: 'approves together with', strength: '0.74',
    means: 'People working together and sharing decisions across teams and companies.', example: 'Jane and Percival both approve large payment batches — 14 shared approvals in 90 days, seen across Slack and the CRM.', value: 'Shows who really makes decisions, and who each one depends on.',
    evidence: ['approval_recorded ×14', 'slack · shared thread', 'crm · same account'], layers: ['events', 'entities', 'graph', 'governance'] },
  { id: 'h2a', code: 'H → A', name: 'Human to agent', short: 'handing off a task', c: TONES.cobalt, from: H('Jane Doe', 'usr_4f21a9'), to: A('Ptolemy', 'agt_2f18e'), verb: 'hands a task to', strength: '0.90',
    means: 'A person gives a task to an AI agent and stays responsible for it.', example: 'Jane asked Ptolemy to score applications. It takes 42 actions a day, and each one traces back to what she allowed.', value: 'Every agent action stays tied to the person who allowed it.',
    evidence: ['delegation_granted', 'agent_tool_called ×42/day', 'scope: scoring.read'], layers: ['events', 'entities', 'graph', 'intelligence', 'governance'] },
  { id: 'a2a', code: 'A → A', name: 'Agent to agent', short: 'coordinating', c: TONES.ochre, from: A('Mordred', 'agt_88ce1'), to: A('Settlement agent', 'external'), verb: 'messages', strength: '0.68',
    means: 'AI agents coordinating with, relying on, and handing work to other agents.', example: 'Mordred started an unusual pattern of messages with an outside payments agent linked to a flagged group. Aether is 88% sure.', value: 'Shows patterns between machines that no one would spot in a single log.',
    evidence: ['agent_message ×212', 'new counterparty', 'inferred · conf 0.88'], layers: ['events', 'graph', 'intelligence'] },
  { id: 'a2h', code: 'A → H', name: 'Agent to human', short: 'asking for a decision', c: TONES.ember, from: A('Mordred', 'agt_88ce1'), to: H('Percival', 'risk analyst'), verb: 'asks for a decision from', strength: '0.81',
    means: 'AI agents alerting, recommending, or asking people for a decision.', example: 'Mordred passed the pattern to Percival with its evidence. The payment batch is on hold until he decides.', value: 'Big actions wait for a person, so someone is always accountable.',
    evidence: ['escalation_created', '▲ review required', 'outcome: pending'], layers: ['events', 'intelligence', 'governance'] },
];
const LAYERS: [id: string, g: string, name: string, role: string][] = [
  ['events', '◉', 'Events', 'What came in, and when.'], ['entities', '⬡', 'Entities', 'People, companies, agents, devices.'], ['graph', '↔', 'Graph', 'Who is the same, and who is linked.'],
  ['intelligence', '◈', 'Intelligence', 'Patterns, credit, and risk.'], ['governance', '✓', 'Governance', 'Consent, rules, approvals, records.'],
];

export function RelationshipExplorer() {
  const [state, setState] = useDesignState<{ t: string }>({ t: 'h2a' });
  const cur = RELATIONSHIP_TYPES.find((t) => t.id === state.t) ?? RELATIONSHIP_TYPES[1]!;
  const node = (n: Endpoint) =>
    'width: 60px; height: 60px; border-radius: ' + (n.agent ? '14px' : '999px') + '; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 22px; color: #1a1a1e; background: ' + cur.c[0] + '; box-shadow: 0 0 0 5px ' + cur.c[2] + ';';
  const types = RELATIONSHIP_TYPES.map((t) => {
    const on = t.id === cur.id;
    return {
      code: t.code, name: t.name, short: t.short, sel: on, pick: () => setState({ t: t.id }),
      codeStyle: 'font-family: var(--font-mono); font-size: 13px; font-weight: 500; padding: 6px 9px; border-radius: 8px; white-space: nowrap; background: ' + (on ? '#f5f4f1' : t.c[2]) + '; color: ' + t.c[1] + ';',
      subStyle: 'font-family: var(--font-mono); font-size: 11px; color: ' + (on ? 'rgba(245,244,241,0.85)' : '#6b6a65') + ';',
      style: 'font-family: inherit; flex: 1 1 200px; display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 12px; cursor: pointer; text-align: left; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms; ' + (on ? 'background: ' + t.c[1] + '; border: 1px solid ' + t.c[1] + '; color: #f5f4f1;' : 'background: #eceae5; border: 1px solid #d8d6d0; color: #1a1a1e;'),
      hover: on ? 'background: ' + t.c[1] + ';' : 'background: ' + t.c[2] + '; border-color: ' + t.c[0] + ';',
    };
  });
  const fromNode = node(cur.from);
  const toNode = node(cur.to);
  const codePill = 'font-family: var(--font-mono); font-size: 12px; padding: 3px 9px; border-radius: 999px; color: #1a1a1e; background: ' + cur.c[0] + ';';
  const verbStyle = 'font-size: 12px; font-weight: 500; color: ' + cur.c[0] + '; text-align: center;';
  const lineStyle = 'height: 2px; width: 100%; border-radius: 2px; background: linear-gradient(90deg, ' + cur.c[0] + ' 0 88%, transparent 88%); position: relative;';
  const evStyle = 'font-family: var(--font-mono); font-size: 11px; padding: 4px 8px; border-radius: 6px; border: 1px solid #2a2a2f; background: #111114; color: #e8e6e1;';
  const valueBox = 'flex: 1; border-radius: 8px; padding: 22px; display: flex; flex-direction: column; gap: 6px; background: ' + cur.c[2] + '; border: 1px solid ' + cur.c[0] + '66;';
  const valueLabel = 'font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: ' + cur.c[1] + ';';
  const layers = LAYERS.map(([id, g, name, role]) => {
    const on = cur.layers.includes(id);
    return {
      g, name, role,
      glyphStyle: 'font-family: var(--font-mono); font-size: 16px; color: ' + (on ? cur.c[1] : '#9c9b95') + ';',
      style: 'flex: 1 1 160px; display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 12px; transition: background-color 200ms, border-color 200ms, opacity 200ms; ' + (on ? 'background: ' + cur.c[2] + '; border: 1px solid ' + cur.c[0] + '; opacity: 1;' : 'background: #f5f4f1; border: 1px dashed #d8d6d0; opacity: 0.6;'),
    };
  });
  return (
    <div className="dc pg-relationship-explorer">
    <div data-page="relationship-explorer" style={css("display: flex; flex-direction: column; gap: 12px; font-family: var(--font-sans); color: #1a1a1e;")}>
      <div role="tablist" aria-label="Relationship types" style={css("display: flex; flex-wrap: wrap; gap: 12px;")}>
        {(types).map((t: any, tIndex: number) => (
          <Fragment key={tIndex}>
            <button type="button" role="tab" aria-selected={t.sel} onClick={t.pick} style={css(t.style)} className={`${hoverClass(t.hover, 'hover')}`}>
              <span style={css(t.codeStyle)}>
                {t.code}
              </span>
              <span style={css("display: flex; flex-direction: column; align-items: flex-start; gap: 2px;")}>
                <span style={css("font-size: 14px; font-weight: 500;")}>
                  {t.name}
                </span>
                <span style={css(t.subStyle)}>
                  {t.short}
                </span>
              </span>
            </button>
          </Fragment>
        ))}
      </div>
      <div style={css("display: flex; flex-wrap: wrap; gap: 12px;")}>
        <div data-theme="dark" style={css("flex: 1 1 380px; min-width: 0; background: #1a1a1e; border: 1px solid #2a2a2f; border-radius: 8px; padding: 24px; display: flex; flex-direction: column; gap: 18px; color: #e8e6e1;")}>
          <div style={css("display: flex; justify-content: space-between; align-items: center; gap: 8px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
              {"Synthetic example"}
            </span>
            <span style={css(codePill)}>
              {cur.code}
            </span>
          </div>
          <div style={css("display: grid; grid-template-columns: minmax(0,1fr) minmax(90px, 1.2fr) minmax(0,1fr); align-items: center; gap: 8px;")}>
            <div style={css("display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center;")}>
              <span style={css(fromNode)}>
                {cur.from.g}
              </span>
              <span style={css("font-size: 14px; font-weight: 500; color: #e8e6e1;")}>
                {cur.from.label}
              </span>
              <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                {cur.from.sub}
              </span>
            </div>
            <div style={css("display: flex; flex-direction: column; align-items: center; gap: 6px;")}>
              <span style={css(verbStyle)}>
                {cur.verb}
              </span>
              <span style={css(lineStyle)} />
              <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                {"strength "}{cur.strength}
              </span>
            </div>
            <div style={css("display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center;")}>
              <span style={css(toNode)}>
                {cur.to.g}
              </span>
              <span style={css("font-size: 14px; font-weight: 500; color: #e8e6e1;")}>
                {cur.to.label}
              </span>
              <span style={css("font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                {cur.to.sub}
              </span>
            </div>
          </div>
          <div style={css("display: flex; flex-direction: column; gap: 8px; padding-top: 14px; border-top: 1px solid #2a2a2f;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
              {"Evidence on the edge"}
            </span>
            <div style={css("display: flex; flex-wrap: wrap; gap: 6px;")}>
              {(cur.evidence).map((e: any, eIndex: number) => (
                <Fragment key={eIndex}>
                  <span style={css(evStyle)}>
                    {e}
                  </span>
                </Fragment>
              ))}
            </div>
          </div>
        </div>
        <div style={css("flex: 1 1 340px; min-width: 0; display: flex; flex-direction: column; gap: 8px;")}>
          <div style={css("background: #eceae5; border: 1px solid #d8d6d0; border-radius: 8px; padding: 22px; display: flex; flex-direction: column; gap: 6px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"What it means"}
            </span>
            <span style={css("font-size: 15px; line-height: 1.55;")}>
              {cur.means}
            </span>
          </div>
          <div style={css("background: #f5f4f1; border: 1px solid #d8d6d0; border-radius: 8px; padding: 22px; display: flex; flex-direction: column; gap: 6px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"In the example"}
            </span>
            <span style={css("font-size: 14px; line-height: 1.6; color: #3a3935;")}>
              {cur.example}
            </span>
          </div>
          <div style={css(valueBox)}>
            <span style={css(valueLabel)}>
              {"→ What comes from it"}
            </span>
            <span style={css("font-size: 15px; line-height: 1.55; font-weight: 500; color: #1a1a1e;")}>
              {cur.value}
            </span>
          </div>
        </div>
      </div>
      <div style={css("display: flex; flex-direction: column; gap: 8px;")}>
        <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
          {"Aether layers this relationship uses"}
        </span>
        <div style={css("display: flex; flex-wrap: wrap; gap: 12px;")}>
          {(layers).map((l: any, lIndex: number) => (
            <Fragment key={lIndex}>
              <div style={css(l.style)}>
                <span style={css(l.glyphStyle)}>
                  {l.g}
                </span>
                <span style={css("font-size: 13px; font-weight: 500;")}>
                  {l.name}
                </span>
                <span style={css("font-size: 12px; line-height: 1.45; color: #6b6a65;")}>
                  {l.role}
                </span>
              </div>
            </Fragment>
          ))}
        </div>
      </div>
    </div>
    </div>
  );
}
