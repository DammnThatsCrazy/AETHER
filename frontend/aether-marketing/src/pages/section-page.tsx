import { Link, useLocation } from 'react-router-dom';
import { Button } from '@aether/ui';
import { CtaBand, PageHero, type CtaLink } from '@aether-marketing/components/marketing-section';
import { findSection, type SectionCopy } from '@aether-marketing/content/sections';
import { AETHER_DOCS_URL } from '@aether-marketing/lib/env';
import { usePageMeta } from '@aether-marketing/lib/meta';

/** Renders one top-level Aether marketing section from src/content/sections.ts. */
export function SectionPage() {
  const { pathname } = useLocation();
  const section = findSection(pathname);

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
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          {section.paragraphs !== undefined && (
            <div className="mkt-measure space-y-5">
              {section.paragraphs.map((p) => (
                <p key={p} className="mkt-body text-text-secondary">
                  {p}
                </p>
              ))}
            </div>
          )}
          {section.bullets !== undefined && (
            <ul className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {section.bullets.map((b) => (
                <li key={b.heading} className="rounded-md border border-border-default p-6">
                  <h2 className="mkt-body font-medium text-text-primary">{b.heading}</h2>
                  <p className="mt-2 text-sm leading-relaxed text-text-secondary">{b.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
      <SectionCtaBand section={section} />
    </>
  );
}

/** One section’s closing call-to-action band, driven by `section.cta` when a
 * truthful next step is declared, otherwise the shared sign-up fallback. */
function SectionCtaBand({ section }: { readonly section: SectionCopy }) {
  const { cta } = section;

  if (cta === undefined) {
    // Default fallback. "Start building" routes through the public /signup
    // threshold (the architecture's single entry to the application), never
    // straight to the application origin. The platform overview does not point
    // back at itself, so its "Explore the platform" secondary link is dropped.
    const secondary =
      section.slug === '/platform' ? undefined : { label: 'Explore the platform', to: '/platform' };
    return (
      <CtaBand
        title="Start building on Aether"
        body="Aether is not yet generally available. When it opens to customers, this is the front door — create your workspace here and the Aether application takes over from there."
        primary={{ label: 'Start building', to: '/signup' }}
        {...(secondary !== undefined ? { secondary } : {})}
      />
    );
  }

  const bandCopy = ctaBandCopy(cta);
  const secondary =
    cta.external === true ? undefined : { label: 'Start building', to: '/signup' };
  return (
    <CtaBand
      title={bandCopy.title}
      body={bandCopy.body}
      primary={externalLink(cta.label, cta.to, cta.external)}
      {...(secondary !== undefined ? { secondary } : {})}
    />
  );
}

function externalLink(label: string, to: string, external?: boolean): CtaLink {
  return external === true ? { label, to, external: true } : { label, to };
}

/** Band copy is chosen to match the declared CTA destination so the closing
 * message never contradicts the button that carries it. */
function ctaBandCopy(cta: CtaLink): { readonly title: string; readonly body: string } {
  const { to, external } = cta;
  if (external === true && (to === AETHER_DOCS_URL || to.startsWith(`${AETHER_DOCS_URL}/`))) {
    return {
      title: 'Go deeper in the documentation',
      body: 'Aether’s documentation site carries the technical depth behind the platform — the event model, identity resolution, consent, connectors, and validation.',
    };
  }
  return {
    title: 'Keep exploring Aether',
    body: 'The platform and its solution pages are sections of one governed whole — resolve, understand, act, and measure under shared governance.',
  };
}
