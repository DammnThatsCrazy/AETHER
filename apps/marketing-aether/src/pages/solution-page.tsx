import { Link, useParams } from 'react-router-dom';
import { Button } from '@aether/ui';
import { CtaBand, PageHero } from '@aether-marketing/components/marketing-section';
import { findSolution, SOLUTIONS } from '@aether-marketing/content/solutions';
import { usePageMeta } from '@aether-marketing/lib/meta';

/** One narrative field of a solution, rendered as a labeled, readable card. */
function SolutionField({ label, text }: { readonly label: string; readonly text: string }) {
  return (
    <article className="rounded-md border border-border-default bg-surface-raised p-6">
      <h2 className="text-sm font-medium uppercase tracking-wide text-text-secondary">{label}</h2>
      <p className="mt-3 text-sm leading-relaxed text-text-secondary">{text}</p>
    </article>
  );
}

/**
 * Deep page for one solution (`/solutions/:solutionSlug`). Page body only — the
 * shell and footer are mounted by the route layout, never by this component.
 */
export function SolutionPage() {
  const { solutionSlug } = useParams();
  const record = solutionSlug !== undefined ? findSolution(solutionSlug) : undefined;

  usePageMeta(
    record !== undefined
      ? { title: `${record.title} — Aether by Olympus Labs`, description: record.description }
      : { title: 'Aether by Olympus Labs' },
  );

  if (record === undefined) {
    return (
      <div className="mkt-container py-24">
        <h1 className="mkt-display">Page not found</h1>
        <p className="mkt-lead mt-4 max-w-xl">This solution does not exist yet.</p>
        <p className="mt-8">
          <Button asChild variant="primary">
            <Link to="/solutions">Back to the solutions</Link>
          </Button>
        </p>
      </div>
    );
  }

  const siblings = SOLUTIONS.filter((solution) => solution.slug !== record.slug);

  return (
    <>
      <PageHero eyebrow="Solution" title={record.title} lead={record.audience} />

      {/* Situation → friction → transformation */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <div className="grid gap-4 md:grid-cols-3">
            <SolutionField label="The situation" text={record.situation} />
            <SolutionField label="The friction" text={record.friction} />
            <SolutionField label="The transformation" text={record.transformation} />
          </div>
        </div>
      </section>

      {/* The scenario in practice — visibly labeled so it is never mistaken for a case study */}
      <section className="border-b border-border-default bg-surface-sunken">
        <div className="mkt-container py-16 md:py-20">
          <div className="mkt-measure">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-sm font-medium uppercase tracking-wide text-text-secondary">
                The scenario in practice
              </h2>
              <span className="mkt-chip">{record.scenarioLabel}</span>
            </div>
            <p className="mkt-body mt-4 text-text-secondary">{record.scenario}</p>
          </div>
        </div>
      </section>

      {/* Aether capabilities involved — display families; links are reconciled by a
          later integration pass when platform capability slugs are published. */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <h2 className="text-sm font-medium uppercase tracking-wide text-text-secondary">
            The Aether capabilities involved
          </h2>
          <ul className="mt-4 flex flex-wrap gap-2">
            {record.capabilities.map((capability) => (
              <li key={capability} className="mkt-chip">
                {capability}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Implementation model + governance considerations */}
      <section className="border-b border-border-default bg-surface-sunken">
        <div className="mkt-container py-16 md:py-20">
          <div className="grid gap-4 md:grid-cols-2">
            <SolutionField label="Implementation model" text={record.implementation} />
            <SolutionField label="Governance considerations" text={record.governance} />
          </div>
        </div>
      </section>

      {/* Evidence that exists today */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <div className="mkt-measure">
            <h2 className="text-sm font-medium uppercase tracking-wide text-text-secondary">
              The evidence that exists today
            </h2>
            <p className="mkt-body mt-4 text-text-secondary">{record.evidence}</p>
          </div>
        </div>
      </section>

      {/* Back to /solutions plus sibling solutions */}
      <section className="border-b border-border-default bg-surface-raised">
        <div className="mkt-container py-16 md:py-20">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <h2 className="mkt-h2">Related solutions</h2>
            <Link
              to="/solutions"
              className="mt-1 text-sm font-medium text-text-secondary mkt-motion-color hover:text-text-primary"
            >
              ← All solutions
            </Link>
          </div>
          <p className="mkt-lead mt-3 max-w-2xl">
            Each solution follows the same narrative — situation, friction, transformation,
            illustrative product scenario, capabilities, implementation, governance, and evidence —
            so different situations compare fairly.
          </p>
          <ul className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {siblings.map((solution) => (
              <li key={solution.slug} className="h-full">
                <Link
                  to={`/solutions/${solution.slug}`}
                  className="group block h-full rounded-md border border-border-default bg-surface-base p-6 mkt-motion-color hover:border-accent"
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

      <CtaBand
        title="Start building on Aether"
        body="Aether is not yet generally available. When it opens to customers, this is the front door — create your workspace here and the Aether application takes over from there."
        primary={{ label: 'Start building', to: '/signup' }}
        secondary={{ label: 'Explore all solutions', to: '/solutions' }}
      />
    </>
  );
}
