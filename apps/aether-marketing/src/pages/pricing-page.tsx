import { LaunchPackPage } from '../../../marketing/src/LaunchPackPage';
import { getLaunchPackPage } from '../../../marketing/src/content-loader';
import { usePageMeta } from '@aether-marketing/lib/meta';

/**
 * Pricing is intentionally editorial until a deployment-specific commercial
 * plan is approved. The Drive launch pack is the source of truth for package
 * boundaries, commercial language, and the pilot path; this page must not
 * publish stale or unapproved price-card values.
 */
export function PricingPage() {
  const page = getLaunchPackPage('Aether', '/pricing');

  usePageMeta({
    title: page?.seoTitle ?? 'Pricing and packages — Aether',
    description:
      page?.seoDescription ??
      'Aether packages connection and relationship intelligence infrastructure around connected evidence and governed outcomes.',
  });

  if (page === undefined) {
    return (
      <section className="mkt-container py-24">
        <h1 className="mkt-display">Pricing and packages.</h1>
        <p className="mkt-lead mt-4 max-w-2xl">
          Commercial scope is discussed around the relationship question, connected evidence,
          governance, and the deployment model.
        </p>
      </section>
    );
  }

  return <LaunchPackPage page={page} />;
}
