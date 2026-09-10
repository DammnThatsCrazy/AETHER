import { Link } from 'react-router-dom';
import { Button, cn } from '@aether/ui';
import { CtaBand, Eyebrow, PageHero } from '@aether-marketing/components/marketing-section';
import { WaitlistSection } from '@aether-marketing/components/waitlist-section';
import { findSection } from '@aether-marketing/content/sections';
import { OLYMPUS_SITE_URL } from '@aether-marketing/lib/env';
import { usePageMeta } from '@aether-marketing/lib/meta';

/**
 * Aether /pricing — plan data sourced from the Stripe product catalog
 * (Olympus Labs account, livemode). The dedicated page renders the self-serve
 * tiers and comparison table, then the SECTIONS entry's own paragraphs exactly
 * as SectionPage would, so the editorial language stays in one authored place
 * (src/content/sections.ts).
 */

interface PricingTier {
  readonly id: string;
  readonly name: string;
  readonly tagline: string;
  readonly price: string;
  readonly priceNote: string;
  readonly annualNote?: string;
  readonly features: readonly string[];
  readonly cta: { readonly label: string; readonly to: string; readonly external?: boolean };
  readonly highlighted?: boolean;
}

const TIERS: readonly PricingTier[] = [
  {
    id: 'alpha',
    name: 'Alpha',
    tagline: 'Free tier for individual developers and evaluation.',
    price: '$0',
    priceNote: 'per month',
    features: [
      '2 seats included',
      '3 million raw events / month',
      'Raw-event overage: $0.060 per 1,000',
      'ACU overage: $7.00 per 1,000',
      'Community documentation support',
    ],
    cta: { label: 'Start building', to: '/signup' },
  },
  {
    id: 'beta',
    name: 'Beta',
    tagline: 'Early-production subscription for small teams.',
    price: '$299',
    priceNote: 'per month',
    annualNote: '$3,050 / year (15% off)',
    features: [
      '3 seats included',
      '9 million raw events / month',
      'Raw-event overage: $0.050 per 1,000',
      'ACU overage: $5.00 per 1,000',
      'Priority documentation support',
      'Everything in Alpha',
    ],
    cta: { label: 'Start building', to: '/signup' },
  },
  {
    id: 'gamma',
    name: 'Gamma',
    tagline: 'Recommended production subscription.',
    price: '$899',
    priceNote: 'per month',
    annualNote: '$9,170 / year (15% off)',
    features: [
      '5 seats included',
      '18 million raw events / month',
      'Raw-event overage: $0.040 per 1,000',
      'ACU overage: $4.00 per 1,000',
      'Priority support',
      'Everything in Beta',
    ],
    cta: { label: 'Start building', to: '/signup' },
    highlighted: true,
  },
  {
    id: 'delta',
    name: 'Delta',
    tagline: 'Advanced intelligence and outcomes with productized implementation readiness.',
    price: '$3,449',
    priceNote: 'per month',
    annualNote: '$35,180 / year (15% off)',
    features: [
      '5+ seats (expandable)',
      '27 million raw events / month',
      'Raw-event overage: $0.030 per 1,000',
      'ACU overage: $3.00 per 1,000',
      'Productized implementation readiness',
      'Dedicated support',
      'Everything in Gamma',
    ],
    cta: { label: 'Talk to Olympus Labs', to: `${OLYMPUS_SITE_URL}/contact`, external: true },
  },
];

interface ContactTier {
  readonly id: string;
  readonly name: string;
  readonly description: string;
}

const CONTACT_TIERS: readonly ContactTier[] = [
  {
    id: 'epsilon',
    name: 'Epsilon',
    description: 'Enterprise-grade deployment for organizations with 54M+ raw events per month. Pricing is scoped per engagement.',
  },
  {
    id: 'omega',
    name: 'Omega',
    description: 'Private or regulated deployments with bespoke requirements. Pricing and scope are configured per engagement.',
  },
  {
    id: 'omicron',
    name: 'Omicron',
    description: 'Bespoke deployment for organizations with dedicated infrastructure requirements. Pricing and scope are configured per engagement.',
  },
];

interface ComparisonRow {
  readonly feature: string;
  readonly values: readonly [string, string, string, string];
}

const COMPARISON_ROWS: readonly ComparisonRow[] = [
  { feature: 'Monthly price', values: ['$0', '$299', '$899', '$3,449'] },
  { feature: 'Annual price', values: ['—', '$3,050 / yr', '$9,170 / yr', '$35,180 / yr'] },
  { feature: 'Seats', values: ['2', '3', '5', '5+'] },
  { feature: 'Raw events / month', values: ['3M', '9M', '18M', '27M'] },
  { feature: 'Event overage (per 1K)', values: ['$0.060', '$0.050', '$0.040', '$0.030'] },
  { feature: 'ACU overage (per 1K)', values: ['$7.00', '$5.00', '$4.00', '$3.00'] },
  { feature: 'Managed workload (per ACU)', values: ['—', '$3.50', '$3.00', '$1.25'] },
  { feature: 'BYOK workload (per ACU)', values: ['—', '$1.75', '$1.50', '$0.625'] },
  { feature: 'Support', values: ['Community', 'Priority docs', 'Priority', 'Dedicated'] },
  { feature: 'Implementation readiness', values: ['—', '—', '—', 'Included'] },
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

      {/* Self-serve tiers */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <Eyebrow>Plans</Eyebrow>
          <h2 className="mkt-h2 mt-4 max-w-2xl">Four self-serve tiers, sized for where a team is today</h2>
          <p className="mkt-lead mt-4 max-w-2xl">
            Each plan includes a monthly raw-event allowance and seat cap. Overage is metered and billed per the
            published rate card — no surprise tiers or hidden multipliers.
          </p>

          <div className="mt-12 grid gap-6 lg:grid-cols-4">
            {TIERS.map((tier) => (
              <article
                key={tier.id}
                className={cn(
                  'flex flex-col rounded-lg border p-6 md:p-8',
                  tier.highlighted ? 'border-accent bg-surface-raised' : 'border-border-default bg-surface-base',
                )}
              >
                {tier.highlighted === true && (
                  <p className="mkt-eyebrow mb-2 text-accent">Recommended</p>
                )}
                <h3 className="text-xl font-semibold text-text-primary">Aether {tier.name}</h3>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">{tier.tagline}</p>
                <p className="mt-6 text-3xl font-semibold tracking-tight text-text-primary">{tier.price}</p>
                <p className="mt-1 text-xs text-text-muted">{tier.priceNote}</p>
                {tier.annualNote !== undefined && (
                  <p className="mt-1 text-xs text-text-secondary">{tier.annualNote}</p>
                )}
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

      {/* Contact-priced tiers */}
      <section className="border-b border-border-default bg-surface-sunken">
        <div className="mkt-container py-16 md:py-20">
          <Eyebrow>Enterprise and specialized</Eyebrow>
          <h2 className="mkt-h2 mt-4 max-w-2xl">For organizations beyond the self-serve tiers</h2>
          <p className="mkt-lead mt-4 max-w-2xl">
            Pricing is scoped per engagement. Reach out to discuss volume, deployment model, and governance requirements.
          </p>

          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {CONTACT_TIERS.map((tier) => (
              <article key={tier.id} className="flex flex-col rounded-lg border border-border-default bg-surface-base p-6 md:p-8">
                <h3 className="text-lg font-semibold text-text-primary">Aether {tier.name}</h3>
                <p className="mt-2 flex-1 text-sm leading-relaxed text-text-secondary">{tier.description}</p>
                <div className="mt-6">
                  <Button asChild variant="secondary" size="lg" className="w-full">
                    <a href={`${OLYMPUS_SITE_URL}/contact`} target="_blank" rel="noreferrer">
                      Contact Olympus Labs
                    </a>
                  </Button>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Add-ons */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <Eyebrow>Add-ons</Eyebrow>
          <h2 className="mkt-h2 mt-4 max-w-2xl">Activation and Harness balance</h2>
          <div className="mt-8 grid gap-6 md:grid-cols-2">
            <div className="rounded-lg border border-border-default bg-surface-base p-6 md:p-8">
              <h3 className="text-lg font-semibold text-text-primary">Delta Activation</h3>
              <p className="mt-2 text-sm text-text-secondary">
                Productized implementation package: architecture and source review, tenant configuration,
                connector validation, graph health check, first intelligence workflow, billing validation,
                and acceptance handoff.
              </p>
              <p className="mt-4 text-2xl font-semibold text-text-primary">$7,500</p>
              <p className="text-xs text-text-muted">One-time — Delta tier only</p>
            </div>
            <div className="rounded-lg border border-border-default bg-surface-base p-6 md:p-8">
              <h3 className="text-lg font-semibold text-text-primary">Harness Balance Top-Up</h3>
              <p className="mt-2 text-sm text-text-secondary">
                Prepaid balance for approved managed or BYOK workload usage.
                Model-provider charges remain separate for BYOK.
              </p>
              <p className="mt-4 text-2xl font-semibold text-text-primary">$25 / $100 / $500</p>
              <p className="text-xs text-text-muted">One-time — all tiers</p>
            </div>
          </div>
        </div>
      </section>

      {/* Feature comparison table */}
      <section className="border-b border-border-default bg-surface-sunken">
        <div className="mkt-container py-16 md:py-20">
          <Eyebrow>Compare</Eyebrow>
          <h2 className="mkt-h2 mt-4">Self-serve plan comparison</h2>
          <div className="mt-8 overflow-x-auto rounded-md border border-border-default bg-surface-base">
            <table className="w-full min-w-[640px] border-collapse text-left text-sm">
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

      {/* /pricing editorial copy */}
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
        title="Get notified when general availability launches"
        body="Leave your email and Olympus Labs will follow up when general availability is live."
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
