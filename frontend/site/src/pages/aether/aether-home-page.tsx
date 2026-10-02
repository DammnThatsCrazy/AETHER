import { useState, type CSSProperties, type ReactNode } from 'react';
import { PageShell } from '@site/components/page-shell';
import { Profile360 } from '@site/components/profile-360';
import { RelationshipExplorer } from '@site/components/relationship-explorer';
import { ButtonLink, Eyebrow, Glyph, SectionHead } from '@site/components/ui';
import { ACCENTS, tint, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';
import { pilotOnly } from '@site/site/access';

/** Aether Home.dc.html */

type AboutTab = 'what' | 'does' | 'how' | 'value' | 'gov';

const ABOUT_TABS: Array<[AboutTab, string, string, Accent]> = [
  ['what', '◈', 'What it is', 'cobalt'],
  ['does', '→', 'What it does', 'sage'],
  ['how', '⌘', 'How it works', 'solar'],
  ['value', '↑', 'Example of value', 'ochre'],
  ['gov', '✓', 'Governance', 'ember'],
];

type LayerId = 'events' | 'entities' | 'graph' | 'intelligence' | 'governance';

export const PRODUCT_LAYERS: Array<{ id: LayerId; glyph: string; name: string; short: string; accent: Accent; body: string; items: string[] }> = [
  { id: 'events', glyph: '◉', name: 'Aether Events', short: 'ingestion · timeline', accent: 'sage', body: 'The event ingestion and operational timeline layer. Every observation arrives through one contract with its source, consent, and order preserved.', items: ['event pipelines', 'event continuity', 'temporal intelligence', 'operational sequencing', 'attribution lineage'] },
  { id: 'entities', glyph: '⬡', name: 'Aether Entities', short: 'unified identity', accent: 'steel', body: 'The unified operational identity layer. People, organizations, agents, systems, devices, and economic identities become entities you can inspect.', items: ['human entities', 'organizational entities', 'AI agents', 'systems and devices', 'economic entities'] },
  { id: 'graph', glyph: '↔', name: 'Aether Graph', short: 'relationships', accent: 'cobalt', body: 'The relationship intelligence layer. It resolves entities, draws edges between them, and keeps identity continuous as evidence changes.', items: ['entity resolution', 'graph relationships', 'identity continuity', 'behavioral mapping', 'operational lineage'] },
  { id: 'intelligence', glyph: '◈', name: 'Aether Intelligence', short: 'the primary surface', accent: 'ochre', body: 'The primary operational surface: a live feed of entities, relationships, and insights, with attribution and risk explained.', items: ['graph visualization', 'entity intelligence', 'relationship intelligence', 'event intelligence', 'attribution analysis'] },
  { id: 'governance', glyph: '✓', name: 'Aether Governance', short: 'trust and control', accent: 'ember', body: 'The governance and trust layer. Consent, policy, explainability, audit, and access control apply to everything above it.', items: ['consent systems', 'policy enforcement', 'explainability', 'auditability', 'access controls'] },
];

const DOES: Array<[string, string, string, Accent, string]> = [
  ['⬡', 'Resolve identities across systems', 'One person, account, or agent — joined across web, CRM, commerce, and payments, with confidence shown.', 'cobalt', '2 1 360px'],
  ['↔', 'Map relationships between entities', 'Humans, agents, organizations, and devices, with every edge traced to its evidence.', 'sage', '1 1 240px'],
  ['→', 'Explain attribution and behavioral flows', 'Which touchpoints led to value, and which assumptions sit underneath.', 'solar', '1 1 240px'],
  ['▲', 'Detect hidden patterns and risk', 'Clusters, anomalies, and exposure that no single source would show.', 'ember', '1 1 240px'],
  ['◉', 'Understand operational behavior', 'What is happening now, and how it compares to before.', 'ochre', '1 1 240px'],
  ['◈', 'Unify fragmented intelligence', 'One governed perspective instead of four partial dashboards.', 'steel', '2 1 360px'],
  ['✓', 'Coordinate decisions', 'Recommendations wait for people above set thresholds.', 'sage', '1 1 240px'],
];

const MAPS: Array<[string, string, Accent]> = [
  ['●', 'humans', 'cobalt'], ['●', 'organizations', 'sage'], ['⬡', 'AI agents', 'ochre'], ['●', 'systems', 'steel'],
  ['●', 'devices', 'solar'], ['⬡', 'financial activity', 'sage'], ['●', 'events', 'cobalt'], ['●', 'autonomous processes', 'ember'],
];

const FIRST_EXPERIENCE: Array<[string, Accent]> = [
  ['Install the SDK', 'sage'], ['Connect systems', 'cobalt'], ['Ingest events', 'ochre'],
  ['Generate entity relationships', 'ember'], ['Construct the graph', 'solar'], ['Observe relationship intelligence', 'steel'],
];

const WEDGE: Array<[string, string, string]> = [
  ['⬡ Profiles', 'One account and buyer view across web, CRM, commerce, and payments.', '#5a85a8'],
  ['→ Journeys', 'The path from first signal to paid, with evidence for each step.', '#6b9a7c'],
  ['◉ Signals', 'Attribution pathways from campaigns and communications to revenue.', '#c9975a'],
  ['◈ Value', 'Revenue connected to the relationships that produced it.', '#a88a5a'],
  ['▲ Risk', 'Churn, dispute, and exposure indicators — each with its confidence and source.', '#b5564a'],
];

/** Maturity groups (capabilities.ts / capability-state.ts); nothing is described as generally available. */
const SURFACES = {
  alpha: [['◉', 'Signals and Events', 'Canonical observations from SDKs and connectors.', '2 1 340px'], ['⬡', 'Profiles', 'A resolved person, account, or organization.', '1 1 220px'], ['⚙', 'Connectors', 'Authorize, sync, and monitor each source.', '1 1 220px'], ['→', 'Journeys', 'Ordered paths through touchpoints and outcomes.', '1 1 220px']],
  partner: [['◈', 'Lenses', 'Saved perspectives for one question.'], ['✉', 'Communications', 'Messages as part of the relationship record.'], ['↑', 'Value', 'Revenue linked to relationships.'], ['▲', 'Risk', 'Exposure with confidence and source.']],
  direction: [['◈', 'Syndicates.', 'Relationship clusters across people, agents, and organizations.'], ['⚗', 'Wider agent governance.', 'Agent-to-agent authorization beyond observation.']],
} as const;

const PROOF_STANDARD: Array<[string, string, string]> = [
  ['◈', 'The relationship question and baseline', '#3a6896'],
  ['●', 'Sources connected and their readiness', '#6b9a7c'],
  ['○', 'The perspective, with uncertainty shown', '#c9975a'],
  ['✓', 'Who approved what, and when', '#3a6896'],
  ['◉', 'The observed outcome and method', '#a88a5a'],
];

const section = 'border-b border-line';
const inner = 'mx-auto flex max-w-page flex-col px-6';
const pad = 'py-[clamp(64px,9vw,112px)]';
const h2 = 'm-0 text-balance text-[clamp(28px,3.6vw,44px)] font-medium leading-[1.06] tracking-[-0.028em] text-ink';
const ledeClass = 'm-0 text-[15px] leading-[1.6] text-slate';
const cardHover = 'transition-colors duration-120 ease-site hover:border-line-strong hover:bg-stone-200';
const pill = 'rounded-full px-2.5 py-[5px] text-caption';

function MarkRow({ mark, color, children }: { mark: string; color: string; children: string }) {
  return (
    <span className="flex gap-2.5 text-[14px] leading-[1.5]">
      <Glyph>
        <span style={{ color }}>{mark}</span>
      </Glyph>
      <span>{children}</span>
    </span>
  );
}

function AboutPanels({ tab }: { tab: AboutTab }) {
  const [layerId, setLayerId] = useState<LayerId>('graph');
  const layer = PRODUCT_LAYERS.find((l) => l.id === layerId) ?? PRODUCT_LAYERS[2]!;
  const lc = ACCENTS[layer.accent];

  if (tab === 'what') {
    return (
      <div className="flex flex-wrap gap-3">
        <div className="flex min-w-0 flex-[2_1_420px] flex-col gap-2.5 rounded-lg border border-ink bg-ink p-6 text-bone transition-colors duration-120 hover:bg-graphite-hover">
          <span className="text-label uppercase text-mist">Aether is</span>
          <span className="text-h text-bone">The operational intelligence layer, built on a graph that maps how people, agents, and organizations relate.</span>
          <div className="mt-auto flex flex-wrap gap-1.5">
            <span className={`${pill} bg-steel/20 text-[#9fbad6]`}>intelligence graph infrastructure</span>
            <span className={`${pill} bg-sage/20 text-mint`}>relationship intelligence</span>
            <span className={`${pill} bg-ochre/20 text-[#dcb683]`}>governed operational intelligence</span>
          </div>
        </div>
        <div className={`flex min-w-0 flex-[1_1_260px] flex-col gap-2.5 rounded-lg border border-line bg-stone-50 p-6 ${cardHover}`}>
          <span className="text-label uppercase text-slate">Aether is not</span>
          {['A customer data platform', 'An analytics dashboard', 'A marketing platform', 'A chatbot'].map((x) => (
            <MarkRow key={x} mark="■" color={ACCENTS.ember.ink}>
              {x}
            </MarkRow>
          ))}
        </div>
        <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-2.5 rounded-lg border border-cobalt/35 bg-cobalt/[0.08] p-6">
          <span className="text-label uppercase text-cobalt-ink">It maps relationships between</span>
          <div className="flex flex-wrap gap-1.5">
            {MAPS.map(([g, label, accent]) => (
              <span key={label} className={`${pill} border border-line bg-stone-50 text-ink`}>
                <Glyph>
                  <span style={{ color: ACCENTS[accent].base }}>{g}</span>
                </Glyph>{' '}
                {label}
              </span>
            ))}
          </div>
        </div>
        <div className="flex min-w-0 flex-[2_1_420px] flex-col gap-2.5 rounded-lg border border-ochre/40 bg-ochre/10 p-6">
          <span className="text-label uppercase text-ochre-ink">What it replaces</span>
          <span className="text-[15px] leading-[1.55]">
            The manual stitching of analytics, attribution, identity, fraud intelligence, and disconnected event pipelines. Aether
            becomes the connective layer across them, rather than one more silo.
          </span>
        </div>
      </div>
    );
  }

  if (tab === 'does') {
    return (
      <div className="flex flex-wrap gap-3">
        {DOES.map(([g, title, body, accent, flex]) => (
          <div key={title} className={`flex min-w-0 flex-col gap-2.5 rounded-lg border border-line bg-stone-100 p-6 ${cardHover}`} style={{ flex }}>
            <span
              aria-hidden="true"
              className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[10px] font-mono text-[16px]"
              style={{ background: tint(accent, 0.15), color: ACCENTS[accent].ink }}
            >
              {g}
            </span>
            <span className="mt-auto text-[16px] font-medium">{title}</span>
            <span className="text-body-sm leading-[1.55] text-slate">{body}</span>
          </div>
        ))}
      </div>
    );
  }

  if (tab === 'how') {
    return (
      <>
        <div className="flex flex-wrap gap-3" role="group" aria-label="Product layers">
          {PRODUCT_LAYERS.map((l) => {
            const on = l.id === layer.id;
            const c = ACCENTS[l.accent];
            return (
              <button
                key={l.id}
                type="button"
                aria-pressed={on}
                onClick={() => setLayerId(l.id)}
                className="flex min-h-[130px] flex-[1_1_180px] cursor-pointer flex-col items-start gap-1.5 rounded-card border border-b-[3px] p-4 text-left text-ink transition-colors duration-120 hover:[background:var(--hover-bg)]"
                style={
                  {
                    background: on ? tint(l.accent, 0.16) : '#f5f4f1',
                    borderColor: on ? c.base : '#d8d6d0',
                    borderBottomColor: c.base,
                    '--hover-bg': tint(l.accent, 0.16),
                  } as CSSProperties
                }
              >
                <span
                  aria-hidden="true"
                  className="flex h-[34px] w-[34px] items-center justify-center rounded-[10px] font-mono text-[16px]"
                  style={{ background: on ? c.base : tint(l.accent, 0.16), color: on ? '#f5f4f1' : c.base }}
                >
                  {l.glyph}
                </span>
                <span className="mt-auto text-[15px] font-medium">{l.name}</span>
                <span className="text-caption text-slate">{l.short}</span>
              </button>
            );
          })}
        </div>
        <div className="flex flex-col gap-2.5 rounded-lg border p-6" style={{ background: tint(layer.accent, 0.16), borderColor: `${lc.base}66` }}>
          <span className="flex items-center gap-2.5">
            <Glyph className="text-[20px]">
              <span style={{ color: lc.base }}>{layer.glyph}</span>
            </Glyph>
            <span className="text-[18px] font-medium">{layer.name}</span>
            <span className="font-mono text-caption text-slate">layer {PRODUCT_LAYERS.indexOf(layer) + 1} / 5</span>
          </span>
          <span className="max-w-[720px] text-[14px] leading-[1.6] text-[#3a3935]">{layer.body}</span>
          <div className="flex flex-wrap gap-1.5">
            {layer.items.map((x) => (
              <span key={x} className={`${pill} border border-line bg-stone-50`}>
                {x}
              </span>
            ))}
          </div>
        </div>
        <ol className="m-0 flex list-none flex-wrap items-center gap-1.5 p-0 text-body-sm" aria-label="First experience">
          <li className="text-label uppercase text-slate">First experience</li>
          {FIRST_EXPERIENCE.map(([label, accent], i) => (
            <li key={label} className="flex items-center gap-1.5">
              {i > 0 && (
                <span aria-hidden="true" className="font-mono text-ash">
                  →
                </span>
              )}
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-[11px] py-1.5 font-medium"
                style={{ background: tint(accent, 0.16), color: ACCENTS[accent].ink }}
              >
                <span className="font-mono">{String(i + 1).padStart(2, '0')}</span>
                {label}
              </span>
            </li>
          ))}
        </ol>
      </>
    );
  }

  if (tab === 'value') {
    return (
      <>
        <div className="flex flex-wrap gap-3">
          <div className="flex min-w-0 flex-[2_1_440px] flex-col gap-3.5 rounded-lg border border-ink bg-ink p-6 text-bone">
            <span className="flex justify-between gap-2">
              <span className="text-label uppercase text-mist">Example · synthetic ecommerce tenant</span>
              <span className="font-mono text-[11px] text-ochre">the moment it clicks</span>
            </span>
            <span className="text-h text-bone">
              A top customer looks healthy in every dashboard. The graph shows she is two hops from a flagged settlement cluster —
              through an agent acting for her.
            </span>
            <div className="mt-auto grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-1.5 rounded-[10px] border border-graphite-hairline p-3">
                <span className="font-mono text-[11px] text-ember">■ before</span>
                <span className="text-body-sm leading-[1.5] text-mist">
                  Analytics, CRM, payments, and fraud tooling — four partial views, no relationship between them.
                </span>
              </div>
              <div className="flex flex-col gap-1.5 rounded-[10px] border border-sage/50 bg-sage/10 p-3">
                <span className="font-mono text-[11px] text-sage">● with Aether</span>
                <span className="text-body-sm leading-[1.5] text-bone">
                  One path from customer to agent to cluster, with each edge&apos;s evidence and confidence.
                </span>
              </div>
            </div>
          </div>
          <div className="grid flex-[1_1_280px] grid-cols-2 gap-2">
            {([
              ['4 → 1', 'systems to one perspective', 'cobalt'],
              ['2 hops', 'to the hidden cluster', 'ochre'],
              ['0.88', 'confidence, shown not hidden', 'ember'],
              ['1', 'human decision, recorded', 'sage'],
            ] as Array<[string, string, Accent]>).map(([v, k, accent]) => (
              <div
                key={k}
                className="flex flex-col gap-1 rounded-card border p-4"
                style={{ background: tint(accent, 0.12), borderColor: tint(accent, 0.38) }}
              >
                <span className="text-[28px] font-medium tracking-[-0.5px]" style={{ color: ACCENTS[accent].ink }}>
                  {v}
                </span>
                <span className="text-caption text-[#3a3935]">{k}</span>
              </div>
            ))}
          </div>
        </div>
        <span className="text-body-sm text-slate">
          Open the Profile 360 at the top of this page and use the Risk tab to walk through the same example.
        </span>
      </>
    );
  }

  return (
    <div className="flex flex-wrap gap-3">
      <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-2.5 rounded-lg border border-sage/40 bg-sage/10 p-6">
        <span className="text-label uppercase text-sage-ink">Aether may</span>
        {['Recommend', 'Identify', 'Coordinate', 'Predict', 'Analyze'].map((x) => (
          <MarkRow key={x} mark="✓" color={ACCENTS.sage.ink}>
            {x}
          </MarkRow>
        ))}
      </div>
      <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-2.5 rounded-lg border border-ember/35 bg-ember/[0.08] p-6">
        <span className="text-label uppercase text-ember-ink">Aether may not</span>
        {['Execute irreversible, high-impact actions without human approval', 'Operate outside governed policy boundaries', 'Remove human oversight from critical decisions'].map((x) => (
          <MarkRow key={x} mark="■" color={ACCENTS.ember.ink}>
            {x}
          </MarkRow>
        ))}
      </div>
      <div className={`flex min-w-0 flex-[1_1_300px] flex-col gap-2.5 rounded-lg border border-line bg-stone-100 p-6 ${cardHover}`}>
        <span className="text-label uppercase text-slate">Your data</span>
        <MarkRow mark="◈" color={ACCENTS.cobalt.base}>
          You own raw data, event streams, and records.
        </MarkRow>
        <MarkRow mark="⬡" color={ACCENTS.cobalt.base}>
          Tenant intelligence never crosses tenants.
        </MarkRow>
        <MarkRow mark="↺" color={ACCENTS.cobalt.base}>
          Deletion removes raw data and stops ingestion.
        </MarkRow>
      </div>
      <div className="flex min-w-0 flex-[1_1_100%] flex-row flex-wrap items-center gap-2 rounded-lg border border-line bg-stone-50 p-6">
        <span className="text-label uppercase text-slate">Deployment models</span>
        {([
          ['multi-tenant cloud', 'sage'],
          ['enterprise isolated', 'cobalt'],
          ['regulated cloud · planned', 'ochre'],
          ['on-premise · planned', 'ember'],
          ['air-gapped · planned', 'solar'],
        ] as Array<[string, Accent]>).map(([label, accent]) => (
          <span key={label} className={`${pill} font-medium`} style={{ background: tint(accent, 0.16), color: ACCENTS[accent].ink }}>
            {label}
          </span>
        ))}
        <span className="ml-auto text-caption text-slate">Designed for GDPR and SOC 2 readiness · no certification claimed</span>
      </div>
    </div>
  );
}

export function AetherHomePage() {
  const { href } = useSite();
  const [about, setAbout] = useState<AboutTab>('what');

  return (
    <PageShell title="Aether — Connection and relationship intelligence">
      {/* Hero */}
      <section className={section}>
        <div className="mx-auto grid max-w-page items-center gap-[clamp(32px,5vw,56px)] px-6 pb-[clamp(56px,8vw,96px)] pt-[clamp(56px,9vw,120px)] [grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))]">
          <div className="flex min-w-0 flex-col gap-6">
            <span className="inline-flex items-center gap-2 text-label uppercase text-slate">
              <Glyph className="text-body-sm text-cobalt">◈</Glyph>
              Connection and relationship intelligence
            </span>
            <h1 className="m-0 text-balance text-[clamp(44px,6.4vw,80px)] font-medium leading-[0.98] tracking-[-0.042em]">
              Connect the systems. See the relationships.
            </h1>
            <p className="m-0 max-w-[520px] text-pretty text-[17px] leading-[1.55] text-slate">
              Aether connects where people, agents, organizations, and value flows create evidence — then turns that evidence into
              governed relationships, perspectives, and observable outcomes.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <ButtonLink href="#connections" variant="ink" arrow className="min-h-[42px] px-[18px]">
                Explore connections
              </ButtonLink>
              <ButtonLink href={href('aether', '/how-it-works')} variant="stone" className="min-h-[42px] px-[18px]">
                See how Aether works
              </ButtonLink>
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              {([
                ['◈', 'Revenue leaders', 'journeys, value, risk', '#3a6896'],
                ['⌘', 'Data and engineering', 'what connects, and how', '#8a6433'],
                ['✓', 'Security and procurement', 'scope, consent, authority', '#4f8466'],
              ] as const).map(([g, title, sub, color]) => (
                <span key={title} className="flex flex-[1_1_150px] flex-col gap-1 rounded-control border border-line p-3 text-caption text-slate">
                  <Glyph>
                    <span style={{ color }}>{g}</span>
                  </Glyph>
                  <span className="text-body-sm font-medium text-ink">{title}</span>
                  {sub}
                </span>
              ))}
            </div>
          </div>
          <div className="flex min-w-0 flex-col">
            <Profile360 />
          </div>
        </div>
        <div className="border-t border-line">
          <dl className="m-0 mx-auto grid max-w-page px-6 [grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr))]">
            {([
              ['5', 'product layers', '#2d5373'],
              ['4', 'relationship types', '#4f8466'],
              ['13', 'managed connectors', '#8a6433'],
              ['4', 'first-party SDKs', '#7d6538'],
            ] as const).map(([v, k, color], i) => (
              <div key={k} className={`flex flex-row-reverse items-baseline justify-end gap-2.5 py-[22px] ${i ? 'border-l border-line pl-6' : ''}`}>
                <dt className="text-body-sm text-slate">{k}</dt>
                <dd className="m-0 text-[32px] font-medium tracking-[-0.04em]" style={{ color }}>
                  {v}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* About */}
      <section id="about" className={`${section} scroll-mt-14`}>
        <div className={`${inner} ${pad} gap-6`}>
          <div className="flex max-w-[760px] flex-col gap-3">
            <span className="text-label uppercase text-cobalt">About Aether</span>
            <h2 className={h2}>Intelligence graph infrastructure for organizations operating in an AI-native world</h2>
          </div>
          <div role="tablist" aria-label="About Aether" className="flex max-w-full flex-wrap gap-1.5 self-start rounded-[14px] border border-line bg-stone-100 p-1">
            {ABOUT_TABS.map(([id, g, label, accent]) => {
              const on = about === id;
              const base = ACCENTS[accent].base;
              return (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  id={`about-tab-${id}`}
                  aria-selected={on}
                  aria-controls="about-panel"
                  onClick={() => setAbout(id)}
                  className={`inline-flex min-h-[38px] cursor-pointer items-center gap-2 whitespace-nowrap rounded-[10px] border-0 px-3.5 text-body-sm font-medium transition-colors duration-120 ${on ? 'text-stone-50' : 'bg-transparent text-ink hover:bg-stone-200'}`}
                  style={on ? { background: base } : undefined}
                >
                  <Glyph>
                    <span style={{ color: on ? '#f5f4f1' : base }}>{g}</span>
                  </Glyph>
                  {label}
                </button>
              );
            })}
          </div>
          <div id="about-panel" role="tabpanel" aria-labelledby={`about-tab-${about}`} className="flex flex-col gap-6">
            <AboutPanels tab={about} />
          </div>
        </div>
      </section>

      {/* Relationships */}
      <section id="relationships" className={`${section} scroll-mt-14 bg-stone-100`}>
        <div className={`${inner} ${pad} gap-6`}>
          <SectionHead
            accent="sage"
            eyebrow="Human and agentic relationships"
            title="Four kinds of relationship. One graph."
            lede="The economy no longer runs only person to person. Pick a relationship to see what it means, what Aether learns from it, and which layers of the product light up."
          />
          <RelationshipExplorer />
        </div>
      </section>

      {/* Connections */}
      <section id="connections" className={`${section} scroll-mt-14`}>
        <div className={`${inner} ${pad} gap-7`}>
          <SectionHead
            eyebrow="Connections"
            title="The SDK is one path. The relationship layer is the value."
            lede="The connection method answers where evidence came from. Value appears when that evidence keeps its context, joins the right relationships, and supports a perspective someone can review."
          />
          <div className="flex flex-wrap gap-3">
            <a
              href={href('aether', '/docs/quickstart')}
              className={`box-border flex min-h-[220px] flex-[1_1_460px] flex-col gap-2.5 rounded-control border border-line bg-stone-100 p-5 text-ink no-underline hover:text-ink ${cardHover}`}
            >
              <ConnectionHead glyph="⌘" accent="cobalt" label="01 · first-party" />
              <span className="mt-auto text-[20px] font-medium tracking-[-0.3px]">Your applications</span>
              <span className="text-body-sm leading-[1.55] text-slate">
                Web, iOS, Android, and React Native SDKs send consent-gated observations to <code className="text-caption">/v1/batch</code>.
              </span>
              <span className="flex flex-wrap gap-1.5">
                {['@aether/web', 'AetherSDK', 'sdk-android', '@aether/react-native'].map((x) => (
                  <span key={x} className="rounded border border-line bg-stone-50 px-[7px] py-[3px] font-mono text-[11px]">
                    {x}
                  </span>
                ))}
              </span>
            </a>
            <div className={`box-border flex min-h-[220px] flex-[1_1_300px] flex-col gap-2.5 rounded-control border border-line bg-stone-100 p-5 ${cardHover}`}>
              <ConnectionHead glyph="◈" accent="ochre" label="02 · business systems" />
              <span className="mt-auto text-[20px] font-medium tracking-[-0.3px]">Where the work is recorded</span>
              <span className="text-body-sm leading-[1.55] text-slate">
                Commerce, payments, CRM, analytics, support, campaigns, and communications through managed connectors.
              </span>
            </div>
            <div className="box-border flex min-h-[200px] flex-[1_1_300px] flex-col gap-2.5 rounded-control border border-line bg-stone-50 p-5 transition-colors duration-120 hover:border-line-strong hover:bg-stone-100">
              <ConnectionHead glyph="↔" accent="sage" label="03 · external" />
              <span className="mt-auto text-[20px] font-medium tracking-[-0.3px]">Beyond your stack</span>
              <span className="text-body-sm leading-[1.55] text-slate">
                Social, community, partner, identity, and market sources — only when authorized and enabled for the tenant.
              </span>
            </div>
            <div className="box-border flex min-h-[200px] flex-[1_1_460px] flex-col gap-2.5 rounded-control border border-ink bg-ink p-5 text-bone transition-colors duration-120 hover:border-graphite-hairline hover:bg-graphite-hover">
              <ConnectionHead glyph="→" accent="solar" label="04 · direct paths" dark />
              <span className="mt-auto text-[20px] font-medium tracking-[-0.3px] text-bone">APIs, webhooks, imports, agents</span>
              <span className="rounded-control border border-graphite-hairline bg-graphite-base px-3 py-2.5 font-mono text-caption text-mist">
                <span className="text-sage">POST</span> /v1/batch · signed · idempotent
              </span>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 text-body-sm text-slate">
            <span>Start with the minimum source set that answers the first question. Readiness is shown per connection and per tenant.</span>
            <a href={href('aether', '/docs/quickstart')} className="inline-flex gap-1.5 text-[14px] font-medium text-ink no-underline hover:text-cobalt">
              Read the connection docs<Glyph>→</Glyph>
            </a>
          </div>
        </div>
      </section>

      {/* Revenue Intelligence Graph */}
      <section id="wedge" data-theme="dark" className="scroll-mt-14 bg-ink text-bone">
        <div className={`mx-auto grid max-w-page gap-10 px-6 ${pad} [grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr))]`}>
          <div className="flex flex-col gap-4">
            <span className="inline-flex items-center gap-2 text-label uppercase text-mist">
              <Glyph className="text-ochre">◈</Glyph>
              The first commercial package
            </span>
            <h2 className={`${h2} text-bone`}>Revenue Intelligence Graph</h2>
            <p className="m-0 max-w-[480px] text-[15px] leading-[1.6] text-mist">
              For digital businesses that need one governed view of how customers move from first signal to revenue — and what puts
              that revenue at risk. A concrete starting point, not the edge of the platform.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <ButtonLink href={href('aether', '/pricing')} variant="bone" arrow className="min-h-[42px] px-[18px]">
                See packages
              </ButtonLink>
              <ButtonLink href={href('aether', '/contact?type=pilot')} variant="ghost-dark" className="min-h-[42px] px-[18px]">
                Request a pilot
              </ButtonLink>
            </div>
          </div>
          <div className="flex flex-wrap content-start gap-2">
            {WEDGE.map(([label, body, color], i) => (
              <div
                key={label}
                className={`flex flex-col gap-1.5 rounded-control border border-graphite-hairline bg-graphite-base p-4 transition-colors duration-120 hover:bg-graphite-hover ${i === WEDGE.length - 1 ? 'flex-[1_1_100%]' : 'flex-[1_1_260px]'}`}
              >
                <span className="font-mono text-caption" style={{ color }}>
                  {label}
                </span>
                <span className="text-[14px] text-bone">{body}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Product surfaces */}
      <section id="surfaces" className={`${section} scroll-mt-14`}>
        <div className={`${inner} ${pad} gap-6`}>
          <div className="flex max-w-[720px] flex-col gap-3">
            <Eyebrow>Product surfaces</Eyebrow>
            <h2 className={h2}>What exists, what is in validation, what is direction</h2>
            <p className={ledeClass}>Aether is in pre-production private alpha. Nothing below is described as generally available.</p>
          </div>
          <SurfaceGroup dot={<span className="h-2 w-2 rounded-full bg-sage" />} label="Private alpha" note="available to alpha tenants">
            {SURFACES.alpha.map(([g, title, body, flex]) => (
              <div key={title} className={`box-border flex min-h-[140px] flex-col gap-2 rounded-control border border-line bg-stone-100 p-[18px] ${cardHover}`} style={{ flex }}>
                <Glyph className="text-[18px] text-sage-ink">{g}</Glyph>
                <span className="mt-auto text-[16px] font-medium">{title}</span>
                <span className="text-body-sm text-slate">{body}</span>
              </div>
            ))}
          </SurfaceGroup>
          <SurfaceGroup dot={<span className="h-2 w-2 rounded-full bg-ochre" />} label="Design partner" note="bounded validation">
            {SURFACES.partner.map(([g, title, body]) => (
              <div
                key={title}
                className="box-border flex min-h-[120px] flex-[1_1_220px] flex-col gap-2 rounded-control border border-line bg-stone-50 p-[18px] transition-colors duration-120 hover:border-line-strong hover:bg-stone-100"
              >
                <Glyph className="text-[16px] text-ochre-ink">{g}</Glyph>
                <span className="mt-auto text-[15px] font-medium">{title}</span>
                <span className="text-body-sm text-slate">{body}</span>
              </div>
            ))}
          </SurfaceGroup>
          <SurfaceGroup dot={<span className="h-2 w-2 rounded-full border border-ash" />} label="Direction" note="not a current capability">
            {SURFACES.direction.map(([g, title, body]) => (
              <div key={title} className="box-border flex flex-[1_1_300px] items-baseline gap-3 rounded-control border border-dashed border-line-strong px-[18px] py-4">
                <Glyph className="text-ash">{g}</Glyph>
                <span className="text-body-sm text-slate">
                  <span className="font-medium text-ink">{title}</span> {body}
                </span>
              </div>
            ))}
          </SurfaceGroup>
        </div>
      </section>

      {/* Go deeper */}
      <section id="deeper" className={`${section} scroll-mt-14 bg-stone-100`}>
        <div className={`${inner} ${pad} gap-7`}>
          <div className="flex max-w-[720px] flex-col gap-3">
            <Eyebrow>Go deeper</Eyebrow>
            <h2 className={h2}>Three ways to evaluate Aether</h2>
          </div>
          <div className="flex flex-wrap gap-3">
            <DeeperCard
              href={href('aether', '/how-it-works')}
              glyph="⌘"
              accent="cobalt"
              audience="For decision makers"
              title="How it works"
              body="The pipeline, the five product layers, the six evidence states, and a worked example from click to approval."
              cta="Read how it works"
            />
            <DeeperCard
              href={href('aether', '/security')}
              glyph="✓"
              accent="ember"
              audience="For reviewers"
              title="Security and trust"
              body="Tenant isolation, consent gating, key scopes, deletion, and deployment models — with no claims beyond the evidence."
              cta="Review security"
            />
            <DeeperCard
              href={href('aether', '/docs/quickstart-web')}
              glyph="◉"
              accent="sage"
              audience="For developers"
              title="A verified event in six steps"
              body="Install an SDK, send a consent-gated observation, and trace it to a perspective you can inspect."
              cta="Open the quickstart"
              dark
            />
          </div>
        </div>
      </section>

      {/* Proof */}
      <section id="proof" className={`${section} scroll-mt-14 bg-stone-100`}>
        <div className="mx-auto grid max-w-page items-start gap-10 px-6 py-[clamp(56px,8vw,96px)] [grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr))]">
          <div className="flex flex-col gap-3.5">
            <Eyebrow>Proof</Eyebrow>
            <h2 className="m-0 text-[clamp(26px,3.2vw,36px)] font-medium leading-[1.1] tracking-[-0.026em]">No customer outcomes are published yet</h2>
            <p className={`${ledeClass} max-w-[460px]`}>Stories appear here only when a proof partner approves them. Each follows the same standard.</p>
            <a href={href('aether', '/contact?type=proof')} className="inline-flex gap-1.5 text-[14px] font-medium text-ink no-underline hover:text-cobalt">
              Become a proof partner<Glyph>→</Glyph>
            </a>
          </div>
          <div className="flex flex-col gap-3 rounded-control border border-dashed border-line-strong bg-stone-50 p-5">
            <Eyebrow>Proof standard</Eyebrow>
            <ul className="m-0 grid list-none gap-x-2.5 gap-y-2 p-0 text-body-sm leading-[1.5] [grid-template-columns:24px_minmax(0,1fr)]">
              {PROOF_STANDARD.map(([g, text, color]) => (
                <li key={text} className="contents">
                  <Glyph>
                    <span style={{ color }}>{g}</span>
                  </Glyph>
                  <span>{text}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Closing */}
      <section>
        <div className="mx-auto flex max-w-page flex-col items-start gap-5 px-6 py-[clamp(72px,10vw,128px)]">
          <h2 className="m-0 max-w-[720px] text-balance text-[clamp(28px,4vw,48px)] font-medium leading-[1.05] tracking-[-0.025em]">
            Bring one relationship question. Start the loop.
          </h2>
          <p className={`${ledeClass} max-w-[560px]`}>
            You do not need to know the package or the connection path. Describe the question, where the evidence lives, and the
            outcome that matters.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <ButtonLink href={href('aether', '/contact?type=pilot')} variant="ink" arrow className="min-h-[42px] px-[18px]">
              Request a pilot
            </ButtonLink>
            <ButtonLink href={href('aether', '/pricing')} variant="stone" className="min-h-[42px] px-[18px]">
              {pilotOnly() ? 'See packages' : 'Start self-service'}
            </ButtonLink>
            {!pilotOnly() && (
              <a href={href('aether', '/app/signup')} className="inline-flex gap-1.5 px-2 text-[14px] font-medium text-ink no-underline hover:text-cobalt">
                Create an account<Glyph>→</Glyph>
              </a>
            )}
          </div>
        </div>
      </section>
    </PageShell>
  );
}

function ConnectionHead({ glyph, accent, label, dark }: { glyph: string; accent: Accent; label: string; dark?: boolean }) {
  return (
    <span className="flex items-center justify-between">
      <span
        aria-hidden="true"
        className="flex h-8 w-8 items-center justify-center rounded-control font-mono text-[16px]"
        style={{ background: tint(accent, dark ? 0.2 : 0.16), color: dark ? ACCENTS.ochre.base : ACCENTS[accent].ink }}
      >
        {glyph}
      </span>
      <span className={`font-mono text-caption ${dark ? 'text-mist' : 'text-slate'}`}>{label}</span>
    </span>
  );
}

function SurfaceGroup({ dot, label, note, children }: { dot: ReactNode; label: string; note: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <span className="flex items-center gap-2 text-body-sm font-medium">
        {dot}
        {label}
        <span className="font-normal text-slate">· {note}</span>
      </span>
      <div className="flex flex-wrap gap-3">{children}</div>
    </div>
  );
}

function DeeperCard(props: { href: string; glyph: string; accent: Accent; audience: string; title: string; body: string; cta: string; dark?: boolean }) {
  const { href, glyph, accent, audience, title, body, cta, dark } = props;
  const c = ACCENTS[accent];
  return (
    <a
      href={href}
      className={
        'box-border flex min-h-[260px] flex-[1_1_320px] flex-col gap-3 rounded-lg border p-7 no-underline transition-colors duration-120 ' +
        (dark
          ? 'border-ink bg-ink text-bone hover:border-graphite-hairline hover:bg-graphite-hover hover:text-bone'
          : 'border-line bg-stone-50 text-ink hover:border-line-strong hover:bg-stone-200 hover:text-ink')
      }
    >
      <span className="flex items-center justify-between">
        <span
          aria-hidden="true"
          className="flex h-10 w-10 items-center justify-center rounded-control font-mono text-[18px]"
          style={{ background: tint(accent, dark ? 0.2 : 0.12), color: dark ? '#9cc4a9' : c.ink }}
        >
          {glyph}
        </span>
        <span className={`text-label uppercase ${dark ? 'text-mist' : 'text-slate'}`}>{audience}</span>
      </span>
      <span className="mt-auto text-[24px] font-medium leading-[1.2] tracking-[-0.4px]">{title}</span>
      <span className={`text-[14px] leading-[1.6] ${dark ? 'text-mist' : 'text-graphite-body'}`}>{body}</span>
      <span className="text-[14px] font-medium" style={{ color: dark ? '#9cc4a9' : c.ink }}>
        {cta} →
      </span>
    </a>
  );
}
