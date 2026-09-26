import type { ReactNode } from 'react';
import { PageShell } from '@site/components/page-shell';
import { ButtonLink, Card, CardRow, ClosingCta, MarkList, PageHero, Section, SectionHead, StepList } from '@site/components/ui';
import { ProviderMark } from '@site/components/provider-mark';
import { ACCENTS, soft, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';

/** Aether How It Works.dc.html */

const PIPELINE: Array<{ title: string; body: string; accent: Accent }> = [
  { title: 'Observe', body: 'SDKs, providers, and connectors produce canonical observation envelopes.', accent: 'sage' },
  { title: 'Ingest', body: 'Envelopes arrive at POST /v1/batch, gated by the consent state declared on the batch.', accent: 'cobalt' },
  { title: 'Normalize and resolve', body: 'Bronze and silver normalization, then identity, campaign, journey, communication, agent, and value resolution.', accent: 'ochre' },
  { title: 'Project', body: 'A graph outbox writes tenant-scoped projections: entities, edges, and their evidence.', accent: 'steel' },
  { title: 'Surface', body: 'Lenses and 360 views feed the app, developer APIs, and MCP.', accent: 'solar' },
];

const LAYERS: Array<[glyph: string, tag: string, title: string, body: string, chips: string[], accent: Accent]> = [
  ['◉', 'layer 1', 'Aether Events', 'Event pipelines, continuity, temporal intelligence, operational sequencing, attribution lineage.', ['signals', 'journeys'], 'sage'],
  ['⬡', 'layer 2', 'Aether Entities', 'Humans, organizations, AI agents, systems, devices, and economic identities.', ['profiles', '360'], 'steel'],
  ['↔', 'layer 3', 'Aether Graph', 'Entity resolution, relationship edges, identity continuity, behavioral mapping.', ['H→H', 'H→A', 'A→A', 'A→H'], 'cobalt'],
  ['◈', 'layer 4', 'Aether Intelligence', 'The primary surface: entity, relationship, and event intelligence with attribution and risk explained.', ['lenses', 'value', 'risk'], 'ochre'],
];

/** The six evidence states. Glyph and accent are the product's legend. */
export const EVIDENCE_STATES: Array<[glyph: string, title: string, body: string, accent: Accent]> = [
  ['●', 'Observed', 'A source recorded it.', 'sage'],
  ['⬡', 'Resolved', 'Joined to an entity, with confidence.', 'steel'],
  ['○', 'Inferred', 'Derived from patterns. Confidence shown.', 'ochre'],
  ['→', 'Recommended', 'Aether suggests an action.', 'solar'],
  ['✓', 'Approved', 'A person or authorized system said yes.', 'cobalt'],
  ['◉', 'Outcome', 'What happened next, observed.', 'ember'],
];

const LIFECYCLE: Array<[string, Accent]> = [
  ['requested', 'cobalt'],
  ['authorized', 'sage'],
  ['executed', 'ochre'],
  ['verified', 'ember'],
  ['measured', 'solar'],
];

type BrandSlug = 'hubspot' | 'instagram' | 'shopify' | 'stripe';
type ExampleStep = { title: string; detail: ReactNode; state: string; accent: Accent } & ({ logo: BrandSlug } | { glyph: string });

const EXAMPLE: ExampleStep[] = [
  { logo: 'instagram', title: 'Instagram Reel click', detail: <>campaign <code className="text-caption">cmp_spring26</code> · observed</>, state: 'observed', accent: 'sage' },
  { logo: 'shopify', title: 'Product view and cart', detail: 'Shopify connector · observed', state: 'observed', accent: 'sage' },
  { logo: 'stripe', title: 'Payment of $4,200', detail: 'Stripe webhook · observed', state: 'observed', accent: 'sage' },
  { logo: 'hubspot', title: 'Lifecycle moves to customer', detail: 'HubSpot connector · resolved to the same person, conf 0.82', state: 'resolved', accent: 'steel' },
  { glyph: '⬡', title: 'Agent Mordred messages a flagged cluster', detail: 'graph · inferred, conf 0.88', state: 'inferred', accent: 'ochre' },
  { glyph: '✓', title: 'Hold the next settlement batch', detail: 'recommended → approved by an analyst', state: 'approved', accent: 'cobalt' },
];

const chip = 'rounded-full border border-line bg-stone-50 px-2 py-[3px] font-mono text-[11px]';

export function AetherHowItWorksPage() {
  const { href } = useSite();
  return (
    <PageShell title="How it works — Aether" active="How it works">
      <PageHero
        crumbs={[{ label: 'Aether', href: href('aether', '/') }, { label: 'How it works' }]}
        accent="cobalt"
        glyph="⌘"
        eyebrow="How it works"
        title="From evidence to outcome, with every step kept distinct"
        lede="Aether observes what happens across your systems, resolves who and what was involved, maps how they relate, and surfaces a perspective someone can review. Evidence is never shown as inference. Inference is never shown as approval."
        actions={
          <>
            <ButtonLink href={href('aether', '/contact?type=pilot')} arrow>
              Request a pilot
            </ButtonLink>
            <ButtonLink href={href('aether', '/docs/quickstart-web')} variant="soft" accent="sage" glyph="◉">
              Web quickstart
            </ButtonLink>
          </>
        }
        toc={[
          { id: 'pipeline', label: 'The pipeline', accent: 'cobalt' },
          { id: 'layers', label: 'Product layers', accent: 'ochre' },
          { id: 'states', label: 'Evidence states', accent: 'sage' },
          { id: 'authority', label: 'Human authority', accent: 'ember' },
          { id: 'example', label: 'Worked example', accent: 'solar' },
        ]}
      />

      <Section id="pipeline">
        <SectionHead
          accent="cobalt"
          glyph="→"
          eyebrow="The pipeline"
          title="Five stages, one contract"
          lede="Every source — an SDK, a connector, a webhook, an import, or an agent — enters the same pipeline and keeps its source, tenant, consent, and order."
        />
        <StepList steps={PIPELINE} />
      </Section>

      <Section id="layers" tone="stone">
        <SectionHead
          accent="ochre"
          glyph="◈"
          eyebrow="Product layers"
          title="Every feature sits on one of five layers"
          lede="Governance is not a sixth feature. It applies to everything above it."
        />
        <CardRow>
          {LAYERS.map(([glyph, tag, title, body, chips, accent]) => (
            <Card key={title} accent={accent} flex="1 1 220px" glyph={glyph} tag={tag} title={title} body={body}>
              <span className="mt-auto flex flex-wrap gap-1.5">
                {chips.map((c) => (
                  <span key={c} className={chip}>
                    {c}
                  </span>
                ))}
              </span>
            </Card>
          ))}
          <Card
            variant="tint"
            accent="ember"
            flex="1 1 100%"
            glyph="✓"
            tag="applies to all"
            title="Aether Governance"
            body="Consent systems, policy enforcement, explainability, auditability, access controls."
          >
            <span className="flex flex-wrap gap-1.5">
              {['consent', 'audit', 'approval'].map((c) => (
                <span key={c} className={chip}>
                  {c}
                </span>
              ))}
            </span>
          </Card>
        </CardRow>
      </Section>

      <Section id="states">
        <SectionHead
          accent="sage"
          glyph="●"
          eyebrow="Evidence states"
          title="Six states, never blurred"
          lede="Each claim in Aether carries its state. The interface shows it with a glyph and a color, so a reader never mistakes a guess for a fact."
        />
        <CardRow>
          {EVIDENCE_STATES.map(([glyph, title, body, accent]) => (
            <Card key={title} variant="rule" accent={accent} flex="1 1 170px" glyph={glyph} title={title} body={body} />
          ))}
        </CardRow>
      </Section>

      <Section id="authority" tone="dark">
        <SectionHead
          dark
          accent="ember"
          glyph="✓"
          eyebrow="Human authority"
          title="Aether recommends. People decide."
          lede="Critical actions above set thresholds wait for a person. Requested, authorized, executed, verified, and measured are separate states — and where verification is missing, Aether says “executed, verification pending”."
        />
        <CardRow>
          <Card variant="dark" flex="1 1 260px" eyebrow="Aether may">
            <MarkList items={['Recommend', 'Identify', 'Coordinate', 'Predict', 'Analyze']} mark="✓" color={ACCENTS.sage.base} />
          </Card>
          <Card variant="dark" flex="1 1 320px" eyebrow="Aether may not">
            <MarkList
              items={['Execute irreversible, high-impact actions without approval', 'Operate outside governed policy boundaries', 'Remove human oversight from critical decisions']}
              mark="■"
              color={ACCENTS.ember.base}
            />
          </Card>
          <Card variant="dark" flex="1 1 100%" eyebrow="The action lifecycle">
            <ol className="m-0 flex list-none flex-wrap items-center gap-1.5 p-0 font-mono text-caption">
              {LIFECYCLE.map(([state, accent], i) => (
                <li key={state} className="flex items-center gap-1.5">
                  {i > 0 && (
                    <span aria-hidden="true" className="text-slate">
                      →
                    </span>
                  )}
                  <span className="rounded-full border border-graphite-hairline bg-graphite-base px-[9px] py-[5px]" style={{ color: ACCENTS[accent].base }}>
                    {state}
                  </span>
                </li>
              ))}
            </ol>
          </Card>
        </CardRow>
      </Section>

      <Section id="example">
        <SectionHead
          accent="solar"
          glyph="↑"
          eyebrow="Worked example"
          title="One customer, six systems, one perspective"
          lede="A synthetic ecommerce tenant. Each step names the source that produced the evidence."
        />
        <span className="flex items-center gap-2 text-label uppercase text-slate">
          <span className="rounded-full bg-stone-200 px-2 py-[3px] text-ink">Synthetic sample</span>
          not a customer record
        </span>
        <ol className="m-0 flex list-none flex-col overflow-hidden rounded-card border border-line bg-stone-50 p-0">
          {EXAMPLE.map((step, i) => (
            <li
              key={step.title}
              className={`grid items-center gap-3.5 px-[18px] py-3.5 [grid-template-columns:44px_minmax(0,1fr)_auto] ${i ? 'border-t border-stone-200' : ''}`}
            >
              {'logo' in step ? (
                <span className="flex h-9 w-9 items-center justify-center rounded-[10px] border border-stone-200 bg-white">
                  <ProviderMark provider={step.logo} size={18} className="text-graphite-body" />
                </span>
              ) : (
                <span
                  aria-hidden="true"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] font-mono text-[16px]"
                  style={{ background: soft(step.accent), color: ACCENTS[step.accent].ink }}
                >
                  {step.glyph}
                </span>
              )}
              <span className="flex min-w-0 flex-col gap-[3px]">
                <span className="text-[14px] font-medium">{step.title}</span>
                <span className="text-caption text-slate">{step.detail}</span>
              </span>
              <span
                className="whitespace-nowrap rounded-full px-[9px] py-[3px] font-mono text-[11px]"
                style={{ background: soft(step.accent), color: ACCENTS[step.accent].ink }}
              >
                {step.state}
              </span>
            </li>
          ))}
        </ol>
        <CardRow>
          <Card
            variant="tint"
            accent="solar"
            flex="1 1 100%"
            title="What came from it"
            body="Four partial views became one path from customer to agent to cluster. The risk surfaced before the next settlement, and a person made the call with the evidence in front of them."
          />
        </CardRow>
      </Section>

      <ClosingCta
        title="Bring one relationship question."
        body="Describe the question, where the evidence lives, and the outcome that would matter. You do not need to know the package."
        primary={{ href: href('aether', '/contact?type=pilot'), label: 'Request a pilot', accent: 'sage' }}
        secondary={{ href: href('aether', '/connections'), label: 'See connections' }}
      />
    </PageShell>
  );
}
