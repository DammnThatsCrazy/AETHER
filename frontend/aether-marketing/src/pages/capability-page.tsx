import { Link, useParams } from 'react-router-dom';
import { Button } from '@aether/ui';
import { CtaBand, Eyebrow, PageHero, type CtaLink } from '@aether-marketing/components/marketing-section';
import { CAPABILITIES, findCapability, type CapabilityCopy } from '@aether-marketing/content/capabilities';
import { usePageMeta } from '@aether-marketing/lib/meta';

const NOT_FOUND_TITLE = 'Capability not found — Aether by Olympus Labs';

/**
 * One capability-family deep page at /platform/<slug>.
 *
 * The page body only — AetherShell owns the header, nav, and footer for the
 * route. Each family renders itself in the one consistent form the /platform
 * copy promises, and the six canonical section headings come from the record's
 * data rather than being hardcoded here.
 */
export function CapabilityPage() {
  const { capabilitySlug } = useParams<{ capabilitySlug: string }>();
  const capability = findCapability(capabilitySlug ?? '');

  usePageMeta(
    capability !== undefined
      ? { title: `${capability.title} — Aether by Olympus Labs`, description: capability.description }
      : { title: NOT_FOUND_TITLE },
  );

  if (capability === undefined) {
    return (
      <div className="mkt-container py-24 md:py-32">
        <h1 className="mkt-display">Capability not found</h1>
        <p className="mkt-lead mt-4 max-w-xl">This capability family does not exist yet.</p>
        <p className="mt-8">
          <Button asChild variant="primary">
            <Link to="/platform">Back to the platform overview</Link>
          </Button>
        </p>
      </div>
    );
  }

  return (
    <>
      <PageHero eyebrow="Capability family" title={capability.title} lead={capability.lead} />
      <CapabilityStatus status={capability.status} />
      {capability.sections.map((section) => (
        <section key={section.heading} className="border-b border-border-default">
          <div className="mkt-container py-16 md:py-20">
            <div className="mkt-measure">
              <h2 className="mkt-h2">{section.heading}</h2>
              <p className="mkt-body mt-4 text-text-secondary">{section.body}</p>
            </div>
          </div>
        </section>
      ))}
      <CapabilityExplorer current={capability} />
      <CapabilityCtaBand />
    </>
  );
}

/** One honest status line about the runtime's current state for this family,
 * rendered as a `.mkt-chip`. */
function CapabilityStatus({ status }: { readonly status: string }) {
  return (
    <section className="border-b border-border-default bg-surface-sunken">
      <div className="mkt-container py-8">
        <Eyebrow>Status</Eyebrow>
        <p className="mt-4 max-w-3xl">
          <span className="mkt-chip">{status}</span>
        </p>
      </div>
    </section>
  );
}

/** Back-link to the platform overview plus the sibling families, so the family
 * explorer stays navigable from any deep page. */
function CapabilityExplorer({ current }: { readonly current: CapabilityCopy }) {
  const siblings = CAPABILITIES.filter((capability) => capability.slug !== current.slug);
  return (
    <section className="border-b border-border-default">
      <div className="mkt-container py-16 md:py-20">
        <Eyebrow>The platform</Eyebrow>
        <h2 className="mkt-h2 mt-4">All capability families</h2>
        <p className="mkt-lead mt-4 max-w-2xl">
          Every family is documented in the same consistent form, so practitioners can compare
          honestly across the platform.
        </p>
        <p className="mt-6">
          <Button asChild variant="secondary" size="md">
            <Link to="/platform">Back to the platform overview</Link>
          </Button>
        </p>
        <ul className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {siblings.map((capability) => (
            <li key={capability.slug} className="rounded-md border border-border-default p-6">
              <Link
                to={`/platform/${capability.slug}`}
                className="group block mkt-motion-color"
              >
                <h3 className="mkt-body font-medium text-text-primary group-hover:text-accent">
                  {capability.shortName}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                  {capability.description}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** Every capability deep page closes with the same governed next step. */
function CapabilityCtaBand() {
  const primary: CtaLink = { label: 'Start building', to: '/signup' };
  const secondary: CtaLink = { label: 'Explore the capability families', to: '/platform' };
  return (
    <CtaBand
      title="Start building on Aether"
      body="Aether is not yet generally available. When it opens to customers, this is the front door — create your workspace here and the Aether application takes over from there."
      primary={primary}
      secondary={secondary}
    />
  );
}
