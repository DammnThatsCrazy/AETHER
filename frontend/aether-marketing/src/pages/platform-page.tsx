import { Link } from 'react-router-dom';
import { Button } from '@aether/ui';
import { CtaBand, PageHero } from '@aether-marketing/components/marketing-section';
import { CAPABILITIES } from '@aether-marketing/content/capabilities';
import { findSection } from '@aether-marketing/content/sections';
import { usePageMeta } from '@aether-marketing/lib/meta';

/**
 * The /platform overview. AetherShell owns the header, nav, and footer for the
 * route; this component is the page body only.
 *
 * The page leads with the shared /platform hero, then the signature family
 * explorer — one card per capability family linking to its deep page — followed
 * by the platform overview prose and bullets rendered exactly as SectionPage
 * renders them, and the default sign-up band.
 */
export function PlatformPage() {
  const section = findSection('/platform');

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
      <CapabilityExplorer />
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
      <CtaBand
        title="Start building on Aether"
        body="Aether is not yet generally available. When it opens to customers, this is the front door — create your workspace here and the Aether application takes over from there."
        primary={{ label: 'Start building', to: '/signup' }}
      />
    </>
  );
}

/** The signature family explorer: every capability family as a card linking to
 * its deep page, each documented in the one consistent form the page promises. */
function CapabilityExplorer() {
  return (
    <section className="border-b border-border-default">
      <div className="mkt-container py-16 md:py-20">
        <h2 className="mkt-h2">Explore the capability families</h2>
        <p className="mkt-lead mt-4 max-w-2xl">
          Each family is documented in one consistent form — the problem it addresses, the inputs it
          consumes, what Aether understands, the output it produces, the governance and consent that
          apply, and the limits the runtime honors.
        </p>
        <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map((capability) => (
            <Link
              key={capability.slug}
              to={`/platform/${capability.slug}`}
              className="group flex flex-col gap-3 rounded-md border border-border-default p-6 mkt-motion-color hover:border-accent"
            >
              <h3 className="mkt-body font-medium text-text-primary group-hover:text-accent">
                {capability.shortName}
              </h3>
              <p className="text-sm leading-relaxed text-text-secondary">{capability.description}</p>
              <span className="mkt-chip mt-auto">{capability.status}</span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
