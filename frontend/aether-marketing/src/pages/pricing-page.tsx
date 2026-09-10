import { Link } from 'react-router-dom';
import { Button, cn } from '@aether/ui';
import { AvailabilityBadge } from '@aether-marketing/components/availability-badge';
import { CtaBand, Eyebrow, PageHero } from '@aether-marketing/components/marketing-section';
import { WaitlistSection } from '@aether-marketing/components/waitlist-section';
import { findSection } from '@aether-marketing/content/sections';
import { OLYMPUS_SITE_URL } from '@aether-marketing/lib/env';
import { usePageMeta } from '@aether-marketing/lib/meta';

/**
 * Aether /pricing. Aether is not yet generally available, so every number on
 * this page is explicitly labeled illustrative — a planning reference for the
 * shape of pricing, not a live billing system. The dedicated page renders the
 * illustrative tiers and comparison table, then the SECTIONS entry's own
 * paragraphs exactly as SectionPage would, so the honesty language stays in
 * one authored place (src/content/sections.ts).
 */

interface PricingTier {
  readonly id: string;
  readonly name: string;
  readonly tagline: string;
  readonly price: string;
  readonly priceNote: string;
  readonly features: readonly string[];
  readonly cta: { readonly label: string; readonly to: string; readonly external?: boolean };
  readonly highlighted?: boolean;
}

const TIERS: readonly PricingTier[] = [
  {
    id: 'developer',
    name: 'Free / Developer',
    tagline: 'For evaluating the platform and building a first integration.',
    price: '$0',
    priceNote: 'Illustrative',
    features: [
      'Up to 10,000 events / month (illustrative)',
      '1 connected source',
      '7-day data retention',
      'Single workspace, single seat',
      'Community documentation support',
    ],
    cta: { label: 'Start building', to: '/signup' },
  },
  {
    id: 'growth',
    name: 'Growth',
    tagline: 'For teams putting identity resolution and journeys into production.',
    price: 'Illustrative',
    priceNote: 'Final pricing ships at general availability',
    features: [
      'Up to 100,000 events / month (illustrative)',
      'Up to 10 connected sources',
      '90-day data retention',
      'Team access — multiple seats',
      'Priority documentation support',
      'Everything in Free / Developer',
    ],
    cta: { label: 'Start building', to: '/signup' },
    highlighted: true,
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    tagline: 'For organizations with custom volume, deployment, or governance needs.',
    price: 'Custom',
    priceNote: 'Scoped to your volume and requirements',
    features: [
      'Custom event volume and source count',
      'Extended retention and audit requirements',
      'SSO / SAML and custom roles (planned)',
      'Dedicated onboarding and support',
      'Everything in Growth',
    ],
    cta: { label: 'Talk to Olympus Labs', to: `${OLYMPUS_SITE_URL}/contact`, external: true },
  },
];

interface ComparisonRow {
  readonly feature: string;
  readonly values: readonly [string, string, string];
}

const COMPARISON_ROWS: readonly ComparisonRow[] = [
  { feature: 'Events / month', values: ['10,000 (illustrative)', '100,000 (illustrative)', 'Custom'] },
  { feature: 'Connected sources', values: ['1', '10', 'Custom'] },
  { feature: 'Seats', values: ['1', 'Team (multiple)', 'Custom'] },
  { feature: 'Data retention', values: ['7 days', '90 days', 'Custom'] },
  { feature: 'Support', values: ['Community docs', 'Priority docs', 'Dedicated'] },
  { feature: 'SSO / SAML', values: ['—', '—', 'Planned'] },
  { feature: 'Deployment', values: ['Shared', 'Shared', 'Custom (planned)'] },
];

export function PricingPage() {
  const section = findSection('/pricing');

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

      {/* Illustrative tiers */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <div className="flex flex-wrap items-center gap-3">
            <Eyebrow>Plans</Eyebrow>
            <AvailabilityBadge status="coming-soon" label="Illustrative — not yet billed" />
          </div>
          <h2 className="mkt-h2 mt-4 max-w-2xl">Three tiers, sized for where a team is today</h2>
          <p className="mkt-lead mt-4 max-w-2xl">
            Every number below is a planning estimate, not a commitment. Final limits and prices ship with general
            availability.
          </p>

          <div className="mt-12 grid gap-6 lg:grid-cols-3">
            {TIERS.map((tier) => (
              <article
                key={tier.id}
                className={cn(
                  'flex flex-col rounded-lg border p-6 md:p-8',
                  tier.highlighted ? 'border-accent bg-surface-raised' : 'border-border-default bg-surface-base',
                )}
              >
                {tier.highlighted === true && (
                  <p className="mkt-eyebrow mb-2 text-accent">Most teams start here</p>
                )}
                <h3 className="text-xl font-semibold text-text-primary">{tier.name}</h3>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">{tier.tagline}</p>
                <p className="mt-6 text-3xl font-semibold tracking-tight text-text-primary">{tier.price}</p>
                <p className="mt-1 text-xs text-text-muted">{tier.priceNote}</p>
                <ul className="mt-6 flex-1 space-y-3">
                  {tier.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2 text-sm text-text-secondary">
                      <span aria-hidden="true" className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-8">
                  {tier.cta.external === true ? (
                    <Button asChild variant={tier.highlighted === true ? 'primary' : 'secondary'} size="lg" className="w-full">
                      <a href={tier.cta.to} target="_blank" rel="noreferrer">
                        {tier.cta.label}
                      </a>
                    </Button>
                  ) : (
                    <Button asChild variant={tier.highlighted === true ? 'primary' : 'secondary'} size="lg" className="w-full">
                      <Link to={tier.cta.to}>{tier.cta.label}</Link>
                    </Button>
                  )}
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Feature comparison table */}
      <section className="border-b border-border-default bg-surface-sunken">
        <div className="mkt-container py-16 md:py-20">
          <Eyebrow>Compare</Eyebrow>
          <h2 className="mkt-h2 mt-4">Feature comparison</h2>
          <div className="mt-8 overflow-x-auto rounded-md border border-border-default bg-surface-base">
            <table className="w-full min-w-[560px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-border-default">
                  <th scope="col" className="p-4 font-medium text-text-secondary">
                    Feature
                  </th>
                  {TIERS.map((tier) => (
                    <th key={tier.id} scope="col" className="p-4 font-medium text-text-primary">
                      {tier.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {COMPARISON_ROWS.map((row) => (
                  <tr key={row.feature} className="border-b border-border-default last:border-b-0">
                    <th scope="row" className="p-4 text-left font-normal text-text-secondary">
                      {row.feature}
                    </th>
                    {row.values.map((value, index) => (
                      <td key={`${row.feature}-${TIERS[index]?.id ?? index}`} className="p-4 text-text-primary">
                        {value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* /pricing editorial copy — kept identical to section-page.tsx */}
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
        </div>
      </section>

      <WaitlistSection
        id="pricing-early-access"
        variant="early-access"
        eyebrow="Not ready to build yet?"
        title="Get notified when final pricing ships"
        body="Leave your email and Olympus Labs will follow up when general availability and final pricing are live."
      />

      <CtaBand
        title="Ready to see the platform in more depth?"
        body="Pricing is one page of the story — the platform overview walks through identity resolution, the intelligence graph, and every capability family in the loop."
        primary={{ label: 'Explore the platform', to: '/platform' }}
        secondary={{ label: 'Start building', to: '/signup' }}
      />
    </>
  );
}
