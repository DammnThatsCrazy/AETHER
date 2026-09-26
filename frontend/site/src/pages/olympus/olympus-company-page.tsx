import { PageShell } from '@site/components/page-shell';
import { ButtonLink, Card, CardRow, ClosingCta, PageHero, Section, SectionHead, accentVars } from '@site/components/ui';
import type { Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';
import { BrandMark } from '@site/components/brand-mark';

/** Olympus Company.dc.html */

const THESIS: Array<[string, string]> = [
  ['The problem', 'Fragmented data, identities, attribution, and awareness — costing visibility, leverage, and adaptability.'],
  ['The answer', 'Connective intelligence infrastructure that sits between existing layers rather than replacing them.'],
  ['The goal', 'Enduring infrastructure for human and agentic coordination.'],
];

const AETHER_LAYERS: Array<[string, Accent]> = [
  ['Events', 'cobalt'],
  ['Entities', 'sage'],
  ['Graph', 'ochre'],
  ['Intelligence', 'ember'],
  ['Governance', 'solar'],
];

const VALUES: Array<[string, string, Accent]> = [
  ['Rigor', 'Claims need evidence, owners, and tests.', 'cobalt'],
  ['Truth-seeking', 'Uncertainty is shown, not hidden.', 'sage'],
  ['Stewardship', 'Customer data is held in trust.', 'ochre'],
  ['Intellectual honesty', 'Direction is never sold as capability.', 'steel'],
  ['Neutrality', 'Olympus Labs is politically neutral.', 'solar'],
];

const ECOMMERCE: Array<[string, string, Accent]> = [
  ['High-volume signals', 'Enough evidence to build a graph quickly.', 'sage'],
  ['Attribution complexity', 'Many touchpoints, unclear credit.', 'ochre'],
  ['Fraud exposure', 'Hidden relationships carry real cost.', 'ember'],
  ['Fragmented identity', 'The same buyer across many systems.', 'steel'],
  ['Fast outcomes', 'Results are measurable within weeks.', 'cobalt'],
];

export function OlympusCompanyPage() {
  const { href } = useSite();
  return (
    <PageShell title="Company — Olympus Labs" active="Company">
      <PageHero
        crumbs={[{ label: 'Olympus Labs', href: href('olympus', '/') }, { label: 'Company' }]}
        accent="cobalt"
        glyph="◈"
        eyebrow="The company"
        title="A research and infrastructure company for human and agentic coordination"
        lede="Olympus Labs builds governed intelligence systems that unify people, organizations, autonomous agents, and economic activity — so relationships can be understood and acted on by the people accountable for them."
        actions={
          <>
            <ButtonLink
              href={href('aether', '/')}
              icon={<BrandMark brand="aether" className="h-4 w-4 rounded bg-stone-50 p-0.5" />}
              arrow
            >
              Meet Aether
            </ButtonLink>
            <ButtonLink href={href('olympus', '/principles')} variant="soft" accent="sage" glyph="✓">
              Principles
            </ButtonLink>
          </>
        }
        toc={[
          { id: 'thesis', label: 'Thesis', accent: 'ochre' },
          { id: 'build', label: 'What we build', accent: 'cobalt' },
          { id: 'work', label: 'How we work', accent: 'sage' },
          { id: 'focus', label: 'Where we start', accent: 'solar' },
        ]}
      />

      <Section id="thesis" tone="dark">
        <SectionHead
          dark
          accent="ochre"
          glyph="◈"
          eyebrow="The thesis"
          title="The future economy will not run only through people."
          lede="It will run through people, autonomous agents, machine systems, and AI-native organizations working together. The organizations that understand those relationships in real time will lead."
        />
        <CardRow>
          {THESIS.map(([label, body]) => (
            <Card key={label} variant="dark" flex="1 1 300px" eyebrow={label} body={body} />
          ))}
        </CardRow>
      </Section>

      <Section id="build">
        <SectionHead accent="cobalt" glyph="⬡" eyebrow="What we build" title="One flagship product, built on a graph" />
        <CardRow>
          <Card
            variant="tint"
            accent="cobalt"
            flex="2 1 460px"
            href={href('aether', '/')}
            title="Aether"
            large
            body="Intelligence graph infrastructure that maps humans, organizations, agents, systems, devices, and value flows — with governance applied to every layer."
            cta="Explore Aether"
          >
            <span className="flex flex-wrap gap-1.5">
              {AETHER_LAYERS.map(([name, accent]) => (
                <span
                  key={name}
                  className="rounded-full border bg-stone-50 px-2.5 py-[5px] text-caption font-medium [border-color:var(--a-line)] [color:var(--a-ink)]"
                  style={accentVars(accent)}
                >
                  {name}
                </span>
              ))}
            </span>
          </Card>
          <Card
            accent="steel"
            flex="1 1 260px"
            href={href('olympus', '/research')}
            glyph="⚗"
            title="Research"
            body="Identity continuity, temporal journeys, attribution, and agent coordination."
            cta="Research directions"
          />
        </CardRow>
      </Section>

      <Section id="work" tone="stone">
        <SectionHead accent="sage" glyph="✓" eyebrow="How we work" title="Quiet excellence over performance" />
        <CardRow>
          {VALUES.map(([title, body, accent]) => (
            <Card key={title} variant="rule" accent={accent} glyph="●" title={title} body={body} />
          ))}
        </CardRow>
      </Section>

      <Section id="focus">
        <SectionHead accent="solar" glyph="↑" eyebrow="Where we start" title="Why ecommerce first" />
        <CardRow>
          {ECOMMERCE.map(([title, body, accent]) => (
            <Card key={title} variant="tint" accent={accent} title={title} body={body} />
          ))}
        </CardRow>
      </Section>

      <ClosingCta
        title="Start with the question, not the package."
        body="Tell us the relationship you need to understand and the systems that hold the evidence."
        primary={{ href: href('olympus', '/contact?type=pilot'), label: 'Start a conversation', accent: 'sage' }}
        secondary={{ href: href('olympus', '/stories'), label: 'Stories and proof' }}
      />
    </PageShell>
  );
}
