import { PageShell } from '@site/components/page-shell';
import { ButtonLink, Card, CardRow, ClosingCta, PageHero, Section, SectionHead, StepList } from '@site/components/ui';
import type { Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';

/**
 * Olympus Stories.dc.html. No stories are published yet; the page states the
 * proof standard instead of showing placeholder customers.
 */

const STANDARD: Array<[string, string, string, Accent]> = [
  ['◈', 'The question and baseline', 'What the partner needed to understand, and where they started.', 'cobalt'],
  ['●', 'Sources and readiness', 'Which systems were connected, and how ready each was.', 'sage'],
  ['○', 'The perspective', 'What Aether showed, with its uncertainty.', 'ochre'],
  ['✓', 'Who approved what', 'The decisions people made, and when.', 'steel'],
  ['◉', 'The outcome and method', 'What changed, how it was measured, and against what.', 'solar'],
];

const PROCESS: Array<{ title: string; body: string; accent: Accent }> = [
  { title: 'Agree the question', body: 'Scope and baseline in writing before the pilot starts.', accent: 'cobalt' },
  { title: 'Run the loop', body: 'Evidence, perspective, decision, outcome.', accent: 'sage' },
  { title: 'Measure', body: 'Against the baseline, with the method stated.', accent: 'ochre' },
  { title: 'Partner review', body: 'The partner approves every word and number.', accent: 'solar' },
  { title: 'Publish', body: 'Only then does it appear here.', accent: 'steel' },
];

export function OlympusStoriesPage() {
  const { href } = useSite();
  return (
    <PageShell title="Stories and proof — Olympus Labs" active="Stories">
      <PageHero
        crumbs={[{ label: 'Olympus Labs', href: href('olympus', '/') }, { label: 'Stories and proof' }]}
        accent="solar"
        glyph="◉"
        eyebrow="Stories and proof"
        title="No customer stories are published yet"
        lede="Stories appear here only when a proof partner approves them. Until then, this page shows the standard every story must meet."
        actions={
          <ButtonLink href={href('olympus', '/contact?type=proof')} accent="solar" arrow>
            Become a proof partner
          </ButtonLink>
        }
        toc={[
          { id: 'standard', label: 'Proof standard', accent: 'solar' },
          { id: 'process', label: 'How a story is published', accent: 'cobalt' },
        ]}
      />

      <Section id="published">
        <SectionHead accent="solar" glyph="○" eyebrow="Published" title="Published stories" />
        <div className="flex flex-col items-start gap-2 rounded-card border border-dashed border-line-strong bg-stone-100 px-6 py-8">
          <span aria-hidden="true" className="font-mono text-[20px] text-ash">
            ○
          </span>
          <span className="text-[16px] font-medium">Nothing here yet</span>
          <span className="max-w-[520px] text-body-sm leading-[1.55] text-graphite-body">
            The first stories will come from private alpha proof partners. Nothing is described here before it is measured and
            approved.
          </span>
        </div>
      </Section>

      <Section id="standard" tone="stone">
        <SectionHead accent="sage" glyph="✓" eyebrow="Proof standard" title="Every story shows five things" />
        <CardRow>
          {STANDARD.map(([glyph, title, body, accent]) => (
            <Card key={title} variant="rule" accent={accent} glyph={glyph} title={title} body={body} />
          ))}
        </CardRow>
      </Section>

      <Section id="process">
        <SectionHead accent="cobalt" glyph="→" eyebrow="Process" title="How a story is published" />
        <StepList steps={PROCESS} />
      </Section>

      <ClosingCta
        title="Document a governed loop with your own data."
        body="Proof partners get a named contact and a written success plan."
        primary={{ href: href('olympus', '/contact?type=proof'), label: 'Become a proof partner', accent: 'solar' }}
        secondary={{ href: href('olympus', '/research'), label: 'Research' }}
      />
    </PageShell>
  );
}
