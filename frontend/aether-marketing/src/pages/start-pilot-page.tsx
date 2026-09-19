import { LaunchPackPage } from '../../../marketing/src/LaunchPackPage';
import { getLaunchPackPage } from '../../../marketing/src/content-loader';
import { usePageMeta } from '@aether-marketing/lib/meta';
import { WaitlistSection } from '@aether-marketing/components/waitlist-section';

export function StartPilotPage() {
  const page = getLaunchPackPage('Aether', '/start-pilot');

  usePageMeta({
    title: page?.seoTitle ?? 'Start a pilot — Aether',
    description:
      page?.seoDescription ??
      'Begin an Aether pilot — connect your first source, resolve identities, and measure outcomes on governed infrastructure.',
  });

  if (page === undefined) {
    return (
      <>
        <section className="mkt-container py-24">
          <p className="mkt-eyebrow">Pilot</p>
          <h1 className="mkt-display mt-3">Start an Aether pilot.</h1>
          <p className="mkt-lead mt-4 max-w-2xl">
            A pilot connects one source, resolves identities, runs the intelligence
            graph, and measures an outcome — on governed infrastructure with real
            tenant isolation.
          </p>
        </section>
        <WaitlistSection
          variant="early-access"
          eyebrow="Get started"
          title="Request a pilot brief"
          body="Tell us about your relationship question and we'll prepare a scoped pilot brief with connection plan, identity model, and success criteria."
        />
      </>
    );
  }

  return <LaunchPackPage page={page} />;
}
