import { Link } from 'react-router-dom';
import { Button } from '@aether/ui';
import { CtaBand, PageHero } from '@aether-marketing/components/marketing-section';
import { findSection } from '@aether-marketing/content/sections';
import { SOLUTIONS } from '@aether-marketing/content/solutions';
import { usePageMeta } from '@aether-marketing/lib/meta';

/**
 * The /solutions landing page: hero from the SECTIONS entry, an explorer grid of
 * every solution shape, the section copy rendered exactly as the generic section
 * page renders it, and the section's own closing CTA. Page body only.
 */
export function SolutionsPage() {
  const section = findSection('/solutions');

  usePageMeta(
    section !== undefined
      ? { title: `${section.title} — Aether by Olympus Labs`, description: section.description }
      : { title: 'Aether by Olympus Labs' },
  );

  if (section === undefined) {
    return (
      <div className="mkt-container py-24">
        <h1 className="mkt-display">Page not found</h1>
        <p className="mkt-lead mt-4 max-w-xl">This section does not exist yet.</p>
        <p className="mt-8">
          <Button asChild variant="primary">
            <Link to="/">Back to the Aether home page</Link>
          </Button>
        </p>
      </div>
    );
  }

  return (
    <>
      <PageHero eyebrow={section.eyebrow} title={section.title} lead={section.lead} />

      {/* Explorer grid of the solution shapes */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <h2 className="mkt-h2">Solutions by shape</h2>
          <p className="mkt-lead mt-4 max-w-3xl">
            Every solution follows the same narrative so different situations compare fairly: the
            situation, the friction, the transformation Aether enables, an illustrative product
            scenario, the Aether capabilities involved, the implementation model, the governance
            considerations, and the evidence that exists today.
          </p>
          <ul className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {SOLUTIONS.map((solution) => (
              <li key={solution.slug} className="h-full">
                <Link
                  to={`/solutions/${solution.slug}`}
                  className="group block h-full rounded-md border border-border-default p-6 mkt-motion-color hover:border-accent"
                >
                  <h3 className="mkt-body font-medium text-text-primary group-hover:text-accent">
                    {solution.shortName}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                    {solution.description}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Section copy — paragraphs and bullets rendered exactly like the generic section page */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          {section.paragraphs !== undefined && (
            <div className="mkt-measure space-y-5">
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph} className="mkt-body text-text-secondary">
                  {paragraph}
                </p>
              ))}
            </div>
          )}
          {section.bullets !== undefined && (
            <ul className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {section.bullets.map((bullet) => (
                <li key={bullet.heading} className="rounded-md border border-border-default p-6">
                  <h2 className="mkt-body font-medium text-text-primary">{bullet.heading}</h2>
                  <p className="mt-2 text-sm leading-relaxed text-text-secondary">{bullet.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* The /solutions entry declares an internal CTA to /platform, so the primary
          link stays in the router and the sign-up becomes the secondary through the
          public /signup threshold, mirroring section-page.tsx's handling exactly. */}
      <CtaBand
        title="Keep exploring Aether"
        body="The platform and its solution pages are sections of one governed whole — resolve, understand, act, and measure under shared governance."
        primary={{ label: 'Explore the platform', to: '/platform' }}
        secondary={{ label: 'Start building', to: '/signup' }}
      />
    </>
  );
}
