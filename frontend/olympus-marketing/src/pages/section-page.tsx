import { Link, useLocation } from 'react-router-dom';
import { Button } from '@aether/ui';
import { CtaBand, PageHero } from '@olympus-marketing/components/marketing-section';
import { findSection, type SectionCta, type SectionLink } from '@olympus-marketing/content/sections';
import { usePageMeta } from '@olympus-marketing/lib/meta';
import { AETHER_MARKETING_URL } from '@olympus-marketing/lib/env';

/**
 * Shared layout for Olympus Labs section routes. Each section's copy lives in
 * `content/sections.ts`; the layout here is consistent so the site reads as one
 * editorial system. Sections carry finished prose — no build-state scaffolding.
 */
export function SectionPage() {
  const { pathname } = useLocation();
  const section = findSection(pathname);

  usePageMeta(
    section === undefined
      ? { title: 'Not found — Olympus Labs' }
      : { title: `${section.title} — Olympus Labs`, description: section.description },
  );

  if (section === undefined) {
    return (
      <section className="mkt-container py-24">
        <h1 className="mkt-display">Page not found.</h1>
        <p className="mkt-lead mt-4">The page you are looking for does not exist on the Olympus Labs site.</p>
      </section>
    );
  }

  const isLegal = section.slug === '/legal';
  const hasOwnCta = section.cta !== undefined;

  return (
    <article>
      <PageHero eyebrow={section.eyebrow} title={section.title} lead={section.lead} />
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          {section.paragraphs !== undefined && (
            <div className="mkt-measure mt-10 space-y-5">
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph} className="mkt-body">
                  {paragraph}
                </p>
              ))}
            </div>
          )}

          {section.bullets !== undefined && (
            <ul className="mt-12 grid gap-6 md:grid-cols-3">
              {section.bullets.map((bullet) => (
                <li key={bullet.heading} className="rounded-lg border border-border-default bg-surface-raised p-6">
                  <h2 className="text-base font-semibold text-text-primary">{bullet.heading}</h2>
                  <p className="mt-2 text-sm leading-relaxed text-text-secondary">{bullet.text}</p>
                </li>
              ))}
            </ul>
          )}

          {section.links !== undefined && (
            <ul className="mt-12 grid gap-4 md:grid-cols-3">
              {section.links.map((link) => (
                <li key={link.heading} className="rounded-lg border border-border-default bg-surface-raised p-6 mkt-motion-color hover:bg-surface-sunken">
                  <SectionLinkCard link={link} />
                </li>
              ))}
            </ul>
          )}

          {hasOwnCta && section.cta !== undefined && (
            <div className="mt-12">
              <SectionCta cta={section.cta} />
            </div>
          )}
        </div>
      </section>

      {!isLegal && !hasOwnCta && (
        <CtaBand
          title="Explore the platform Olympus Labs builds."
          body="Aether is the relationship intelligence platform — see the full product surface on the Aether site, or contact the company directly."
          primary={{ label: 'Explore Aether', to: AETHER_MARKETING_URL, external: true }}
          secondary={{ label: 'Contact Olympus Labs', to: '/contact' }}
        />
      )}
    </article>
  );
}

function SectionCta({ cta }: { readonly cta: SectionCta }) {
  if (cta.external) {
    return (
      <Button asChild variant="primary" size="lg">
        <a href={cta.to} target="_blank" rel="noreferrer">
          {cta.label}
        </a>
      </Button>
    );
  }
  return (
    <Button asChild variant="primary" size="lg">
      <Link to={cta.to}>{cta.label}</Link>
    </Button>
  );
}

function SectionLinkCard({ link }: { readonly link: SectionLink }) {
  const { heading, text, to, external } = link;
  const content = (
    <>
      <span className="block text-sm font-semibold text-text-primary">{heading}</span>
      {text !== undefined && <span className="mt-1 block text-sm leading-relaxed text-text-secondary">{text}</span>}
    </>
  );
  if (external) {
    return (
      <a href={to} target="_blank" rel="noreferrer" className="block">
        {content}
      </a>
    );
  }
  return (
    <Link to={to} className="block">
      {content}
    </Link>
  );
}
