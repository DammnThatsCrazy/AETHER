import { PageShell } from '@site/components/page-shell';
import { Card, CardRow, ClosingCta, Glyph, MarkList, PageHero, Section, SectionHead, accentVars } from '@site/components/ui';
import { ACCENTS, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';
import { PRINCIPLES } from './olympus-home-content';

/** Olympus Principles.dc.html */

const MAY = ['Recommend', 'Identify', 'Coordinate', 'Predict', 'Analyze'];
const MAY_NOT = [
  'Execute irreversible, high-impact actions without human approval',
  'Operate outside governed policy boundaries',
  'Remove human oversight from critical decisions',
];

const DOCTRINE: Array<[string, string, Accent]> = [
  ['Ownership', 'Customers own raw data, event streams, and records.', 'cobalt'],
  ['Isolation', 'Tenant intelligence stays inside the tenant.', 'steel'],
  ['Consent', 'Capture follows the purposes a person granted.', 'sage'],
  ['Deletion', 'Removes raw data and stops ingestion.', 'ochre'],
];

const LIMITS = [
  'Covert monitoring of people',
  'Political manipulation',
  'Unauthorized enrichment',
  'Unlawful targeting',
  'Cross-tenant intelligence leakage',
];

export function OlympusPrinciplesPage() {
  const { href } = useSite();
  return (
    <PageShell title="Principles — Olympus Labs" active="Principles">
      <PageHero
        crumbs={[{ label: 'Olympus Labs', href: href('olympus', '/') }, { label: 'Principles' }]}
        accent="sage"
        glyph="✓"
        eyebrow="Principles"
        title="Five principles that shape everything we build"
        lede="They decide what Aether will and will not do, how it treats data, and where people stay in control."
        toc={[
          { id: 'principles', label: 'The principles', accent: 'sage' },
          { id: 'loop', label: 'Human in the loop', accent: 'cobalt' },
          { id: 'doctrine', label: 'Data doctrine', accent: 'ochre' },
          { id: 'limits', label: 'Limits', accent: 'ember' },
        ]}
      />

      <Section id="principles">
        <SectionHead accent="sage" glyph="✓" eyebrow="The principles" title="In order of precedence" />
        <ol className="m-0 flex list-none flex-col gap-2 p-0">
          {PRINCIPLES.map((p) => {
            const c = ACCENTS[p.accent];
            return (
              <li
                key={p.numeral}
                className="grid items-start gap-5 rounded-card border px-6 py-[22px] transition-colors duration-120 ease-site [background:var(--a-soft)] [border-color:var(--a-line)] [grid-template-columns:minmax(64px,auto)_minmax(0,1fr)] hover:[border-color:var(--a-base)]"
                style={accentVars(p.accent)}
              >
                <span className="rounded-full px-3 py-1.5 text-center font-mono text-body-sm font-medium text-stone-50" style={{ background: c.ink }}>
                  {p.numeral}
                </span>
                <span className="flex flex-col gap-2">
                  <span className="text-[clamp(18px,2.2vw,24px)] font-medium leading-[1.3] tracking-[-0.3px]">{p.text}</span>
                  <span className="text-[14px] leading-[1.55] text-graphite-body">
                    <Glyph>
                      <span style={{ color: c.ink }}>→</span>
                    </Glyph>{' '}
                    {p.detail}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      </Section>

      <Section id="loop" tone="dark">
        <SectionHead dark accent="cobalt" glyph="◈" eyebrow="Human in the loop" title="What the product may and may not do" />
        <CardRow>
          <Card variant="dark" flex="1 1 300px" eyebrow="Aether may">
            <MarkList items={MAY} mark="✓" color={ACCENTS.sage.base} />
          </Card>
          <Card variant="dark" flex="1 1 300px" eyebrow="Aether may not">
            <MarkList items={MAY_NOT} mark="■" color={ACCENTS.ember.base} />
          </Card>
        </CardRow>
      </Section>

      <Section id="doctrine">
        <SectionHead accent="ochre" glyph="⬡" eyebrow="Data doctrine" title="Customer data is held in trust" />
        <CardRow>
          {DOCTRINE.map(([title, body, accent]) => (
            <Card key={title} variant="rule" accent={accent} flex="1 1 220px" glyph="●" title={title} body={body} />
          ))}
        </CardRow>
      </Section>

      <Section id="limits" tone="stone">
        <SectionHead accent="ember" glyph="■" eyebrow="Limits" title="What we do not build for" />
        <CardRow>
          <Card variant="tint" accent="ember" flex="1 1 380px">
            <MarkList items={LIMITS} mark="■" color={ACCENTS.ember.base} />
          </Card>
          <Card
            accent="steel"
            flex="1 1 300px"
            glyph="◈"
            title="Neutrality"
            body="Olympus Labs is politically neutral. The infrastructure serves lawful, governed operations."
          />
        </CardRow>
      </Section>

      <ClosingCta
        title="Principles are only useful if they hold under review."
        body="Ask us how any of them is enforced in the current deployment."
        primary={{ href: href('olympus', '/contact?type=security'), label: 'Request a security review', accent: 'ember' }}
        secondary={{ href: href('olympus', '/company'), label: 'Company' }}
      />
    </PageShell>
  );
}
