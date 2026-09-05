import { Link } from 'react-router-dom';
import { Button } from '@aether/ui';
import { Eyebrow } from '@olympus-marketing/components/marketing-section';
import { usePageMeta } from '@olympus-marketing/lib/meta';
import { AETHER_MARKETING_URL } from '@olympus-marketing/lib/env';

/**
 * Olympus Labs home — company-first, editorial, spacious.
 *
 * Structure follows the ecosystem brief:
 * hero → company thesis → featured product (Aether) → principles → research →
 * security & responsibility → careers/contact. The shell owns chrome; this page
 * owns the company narrative.
 */
export function HomePage() {
  usePageMeta({
    title: 'Olympus Labs — the company that builds Aether',
    description:
      'Olympus Labs builds Aether, a relationship intelligence platform. Serious intelligence infrastructure, governed systems, and measurable outcomes.',
  });

  return (
    <article>
      {/* 1 · Company hero */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-24 md:py-36">
          <Eyebrow>Olympus Labs</Eyebrow>
          <h1 className="mkt-display mt-5 max-w-5xl">
            A serious organization behind the relationship intelligence platform.
          </h1>
          <p className="mkt-lead mt-7 max-w-2xl">
            Olympus Labs is the creator, owner, and operator of Aether. We build intelligence
            infrastructure with a governing philosophy — and we hold ourselves to the same standard of
            proof we ask of our systems.
          </p>
          <div className="mt-10 flex flex-wrap gap-4">
            <Button asChild variant="primary" size="lg">
              <Link to="/company">About the company</Link>
            </Button>
            <Button asChild variant="secondary" size="lg">
              <a href={AETHER_MARKETING_URL}>Explore Aether</a>
            </Button>
          </div>
        </div>
      </section>

      {/* 2 · Company thesis */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-20 md:py-28">
          <div className="grid gap-10 lg:grid-cols-[1fr_1.4fr]">
            <Eyebrow className="lg:pt-2">Thesis</Eyebrow>
            <div className="mkt-measure">
              <p className="mkt-lead">
                Fragmentation → connection → understanding → governed action → measurable outcome.
              </p>
              <p className="mkt-body mt-5">
                Most organizations run dozens of systems that each answer one narrow question. The gap is
                not in any single system — it is the missing layer that relates them. We build that layer,
                and we build it to be governed rather than merely capable.
              </p>
              <p className="mkt-body mt-4">
                Everything we ship shares one lineage: a calm, deliberate, technically credible design
                language, and a status system that says what it knows, what it can prove, and what remains
                uncertain.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 3 · Featured product */}
      <section className="border-b border-border-default bg-surface-raised">
        <div className="mkt-container py-20 md:py-28">
          <Eyebrow>Featured product</Eyebrow>
          <div className="mt-5 grid gap-10 lg:grid-cols-[1.2fr_1fr] lg:items-end">
            <div>
              <h2 className="mkt-h2">Aether — Olympus Labs’ relationship intelligence platform.</h2>
              <p className="mkt-lead mt-5 max-w-2xl">
                Aether connects customer, entity, wallet, agent, campaign, communication, and commerce
                activity into a governed graph — so organizations can understand what happened, why it
                happened, and what to do next.
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button asChild variant="primary" size="lg">
                <Link to="/products/aether">Why Aether exists</Link>
              </Button>
              <Button asChild variant="secondary" size="lg">
                <a href={AETHER_MARKETING_URL}>Explore the platform</a>
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* 4 · Principles */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-20 md:py-28">
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <Eyebrow>Principles</Eyebrow>
              <h2 className="mkt-h2 mt-4">How a company stays coherent across decisions it has not made yet.</h2>
            </div>
            <Button asChild variant="secondary" size="md">
              <Link to="/principles">Read the principles</Link>
            </Button>
          </div>
          <ul className="mt-12 grid gap-px overflow-hidden rounded-lg border border-border-default bg-border-default md:grid-cols-3">
            <PrincipleTile heading="Calm over noise" text="Nothing moves merely because it can. Motion explains, orients, or confirms — or it is removed." />
            <PrincipleTile heading="Truthful status" text="Configured is not verified. Verified is not live. Every surface names the state it is actually in." />
            <PrincipleTile heading="Governed agency" text="Understanding becomes action only through explicit, auditable governance and consent." />
          </ul>
        </div>
      </section>

      {/* 5 · Research */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-20 md:py-28">
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <Eyebrow>Research</Eyebrow>
              <h2 className="mkt-h2 mt-4">Systems thinking, published.</h2>
              <p className="mkt-lead mt-4 max-w-2xl">
                We write publicly about relationship intelligence, identity resolution, governed action,
                and the boundaries of what an intelligence system should claim.
              </p>
            </div>
            <Button asChild variant="secondary" size="md">
              <Link to="/research">View research</Link>
            </Button>
          </div>
        </div>
      </section>

      {/* 6 · Security and responsibility */}
      <section className="border-b border-border-default bg-surface-raised">
        <div className="mkt-container py-20 md:py-28">
          <div className="grid gap-10 lg:grid-cols-[1.2fr_1fr]">
            <div>
              <Eyebrow>Security &amp; responsibility</Eyebrow>
              <h2 className="mkt-h2 mt-4">Responsibility as an architectural property.</h2>
              <p className="mkt-lead mt-5 max-w-2xl">
                Tenant isolation, credential handling, authorization, consent, retention, and audit are
                properties of the platform — and the marketing never claims certainty the runtime cannot
                prove.
              </p>
            </div>
            <div className="flex items-start gap-3 lg:justify-end">
              <Button asChild variant="secondary" size="md">
                <Link to="/security">Security at Olympus Labs</Link>
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* 7 · Company information */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-16 md:py-20">
          <div className="grid gap-8 md:grid-cols-2">
            <div>
              <Eyebrow>Company</Eyebrow>
              <p className="mkt-body mt-4 max-w-md">
                Olympus Labs is the parent company behind Aether. Aether is the customer product; Kyber is
                the private internal operator environment Olympus Labs uses to run the platform.
              </p>
            </div>
            <div className="flex flex-wrap content-end items-center gap-3 md:justify-end">
              <Button asChild variant="secondary" size="md">
                <Link to="/careers">Careers</Link>
              </Button>
              <Button asChild variant="secondary" size="md">
                <Link to="/contact">Contact</Link>
              </Button>
            </div>
          </div>
        </div>
      </section>
    </article>
  );
}

function PrincipleTile({ heading, text }: { readonly heading: string; readonly text: string }) {
  return (
    <li className="bg-surface-base p-8">
      <h3 className="text-lg font-semibold text-text-primary">{heading}</h3>
      <p className="mt-3 text-sm leading-relaxed text-text-secondary">{text}</p>
    </li>
  );
}
