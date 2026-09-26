import { PageShell } from '@site/components/page-shell';
import { ButtonLink, ClosingCta, IconTile, PageHero, Section, SectionHead, StepList } from '@site/components/ui';
import { ACCENTS, soft, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';
import { RESEARCH_AREAS } from './olympus-home-content';

/** Olympus Research.dc.html */

const GATES: Array<{ title: string; body: string; accent: Accent }> = [
  { title: 'Owner', body: 'A named person accountable for the capability.', accent: 'cobalt' },
  { title: 'Contract', body: 'A canonical interface other systems can rely on.', accent: 'steel' },
  { title: 'Tests', body: 'Evidence that it behaves as described.', accent: 'sage' },
  { title: 'Deployment evidence', body: 'Proof it runs in a real tenant.', accent: 'ochre' },
];

export function OlympusResearchPage() {
  const { href } = useSite();
  return (
    <PageShell title="Research — Olympus Labs" active="Research">
      <PageHero
        crumbs={[{ label: 'Olympus Labs', href: href('olympus', '/') }, { label: 'Research' }]}
        accent="steel"
        glyph="⚗"
        eyebrow="Research"
        title="Open questions at the edge of relationship intelligence"
        lede="Research is a direction, not a production claim. Each area becomes a capability only with an owner, a contract, tests, and deployment evidence."
        actions={
          <ButtonLink href={href('olympus', '/contact?type=research')} accent="steel" glyph="⚗">
            Discuss a research path
          </ButtonLink>
        }
        toc={[
          { id: 'areas', label: 'Research areas', accent: 'steel' },
          { id: 'gate', label: 'From research to capability', accent: 'ochre' },
        ]}
      />

      <Section id="areas">
        <SectionHead
          accent="steel"
          glyph="⚗"
          eyebrow="Research areas"
          title="Six directions"
          lede="Open any area to see the questions it is working on."
        />
        <div className="flex flex-wrap gap-3">
          {RESEARCH_AREAS.map((r) => {
            const c = ACCENTS[r.accent];
            const count = r.questions.length;
            return (
              <details
                key={r.id}
                className="group box-border min-w-0 flex-[1_1_340px] rounded-card border border-t-[3px] border-line bg-stone-50"
                style={{ borderTopColor: c.base }}
              >
                <summary className="flex cursor-pointer list-none flex-col gap-2.5 p-5 [&::-webkit-details-marker]:hidden">
                  <span className="flex items-center justify-between">
                    <IconTile glyph={r.glyph} accent={r.accent} />
                    <span className="font-mono text-[11px]" style={{ color: c.ink }}>
                      <span className="group-open:hidden">+</span>
                      <span className="hidden group-open:inline">−</span> {count} open {count === 1 ? 'question' : 'questions'}
                    </span>
                  </span>
                  <span className="text-[17px] font-medium">{r.title}</span>
                  <span className="text-body-sm leading-[1.55] text-graphite-body">{r.body}</span>
                </summary>
                <div className="flex flex-col gap-1.5 px-5 pb-5">
                  {r.questions.map((q) => (
                    <span key={q} className="rounded-lg px-3 py-2.5 text-body-sm leading-[1.5]" style={{ background: soft(r.accent), color: c.ink }}>
                      {q}
                    </span>
                  ))}
                </div>
              </details>
            );
          })}
        </div>
      </Section>

      <Section id="gate" tone="stone">
        <SectionHead accent="ochre" glyph="▲" eyebrow="From research to capability" title="Four gates before anything ships" />
        <StepList steps={GATES} />
      </Section>

      <ClosingCta
        title="Collaborate on a research question."
        body="Bring a problem in identity, attribution, or agent coordination."
        primary={{ href: href('olympus', '/contact?type=research'), label: 'Discuss research', accent: 'steel' }}
        secondary={{ href: href('olympus', '/principles'), label: 'Principles' }}
      />
    </PageShell>
  );
}
