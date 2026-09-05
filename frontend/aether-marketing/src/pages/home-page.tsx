import { Link } from 'react-router-dom';
import { Button } from '@aether/ui';
import { OlympusAttribution } from '@aether-marketing/components/brand-byline';
import { CtaBand, Eyebrow } from '@aether-marketing/components/marketing-section';
import { OLYMPUS_SITE_URL } from '@aether-marketing/lib/env';
import { usePageMeta } from '@aether-marketing/lib/meta';

const LOOP: readonly { readonly step: string; readonly name: string; readonly text: string }[] = [
  { step: '01', name: 'Connect', text: 'Events, profiles, transactions, communications, agents, and integrations arrive through governed connectors.' },
  { step: '02', name: 'Resolve', text: 'People, accounts, devices, wallets, organizations, and systems resolve into one entity model.' },
  { step: '03', name: 'Understand', text: 'Journeys, graph relationships, campaign movement, behavior, and context become intelligence.' },
  { step: '04', name: 'Act', text: 'Recommendations, rewards, communications, campaign actions, and operational decisions stay governed.' },
  { step: '05', name: 'Measure', text: 'Decisions connect to outcomes, and evidence feeds back into the graph.' },
];

const FRAGMENTS: readonly { readonly title: string; readonly text: string }[] = [
  { title: 'CRM knows the deal', text: 'Support knows the ticket. Commerce knows the order. The wallet knows the balance. None of them know the relationship.' },
  { title: 'Agents act on slices', text: 'Automation can now act at machine speed — on whatever slice of context each system happens to hold.' },
  { title: 'Outcomes go unattributed', text: 'When activity is fragmented, the evidence for what moved an outcome is fragmented too. Decisions run on guesswork.' },
];

const FAMILIES: readonly { readonly name: string; readonly text: string }[] = [
  { name: 'Identity & entity resolution', text: 'Connect fragmented identifiers into people, accounts, devices, wallets, and organizations — with consent and lineage.' },
  { name: 'Intelligence graph', text: 'A governed graph of entities, relationships, and activity that every capability reads from and writes to.' },
  { name: 'Journey & campaign intelligence', text: 'Understand journeys, campaign movement, behavior, and context across touchpoints.' },
  { name: 'Communications & financial observability', text: 'See every communication and every ledger effect as part of the same relationship record.' },
  { name: 'Agent access intelligence', text: 'Know when an agent is acting, under what authorization, and with what guardrails.' },
  { name: 'Outcome attribution & governance', text: 'Trace decisions to outcomes, enforce boundaries, and keep consent and auditability first.' },
];

export function HomePage() {
  usePageMeta({
    title: 'Aether — Relationship intelligence by Olympus Labs',
    description:
      'Aether connects customer, entity, wallet, agent, campaign, and commerce activity into a governed graph — identity resolution, intelligence, governed action, and outcome attribution.',
  });

  return (
    <>
      {/* Hero */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-20 md:py-28">
          <Eyebrow>Relationship intelligence</Eyebrow>
          <h1 className="mkt-display mt-4 max-w-4xl">
            One governed graph across everything that shapes an outcome
          </h1>
          <p className="mkt-lead mt-6 max-w-2xl">
            Aether connects customer, entity, wallet, agent, campaign, communication, and commerce
            activity into a governed graph. Identity resolution turns disconnected identifiers into
            people, accounts, devices, wallets, and organizations. Intelligence turns that graph into
            journeys, campaign movement, behavior, and context. Governed action turns understanding
            into recommendations, rewards, communications, and operational decisions — and outcome
            attribution turns decisions back into evidence.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            <Button asChild variant="primary" size="lg">
              <Link to="/signup">Start building</Link>
            </Button>
            <Button asChild variant="secondary" size="lg">
              <Link to="/platform">Explore the platform</Link>
            </Button>
          </div>
          <p className="mt-6 max-w-2xl text-sm leading-relaxed text-text-secondary">
            Aether is not yet generally available — when it opens to customers, starting here takes
            you through sign-up and into the application.
          </p>
          <p className="mt-6 font-mono text-xs uppercase tracking-widest text-text-muted">
            Connect · Resolve · Understand · Act · Measure
          </p>
        </div>
      </section>

      {/* The problem */}
      <section className="border-b border-border-default bg-surface-sunken">
        <div className="mkt-container py-20 md:py-24">
          <Eyebrow>The problem</Eyebrow>
          <h2 className="mkt-h2 mt-4 max-w-2xl">Every relationship leaks across systems</h2>
          <p className="mkt-lead mt-4 max-w-2xl">
            A relationship is not a row in a CRM. It is the accumulation of every signal across every
            system a person, account, or wallet touches — and most of that activity never meets in one
            place.
          </p>
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {FRAGMENTS.map((f) => (
              <article key={f.title} className="rounded-md border border-border-default bg-surface-base p-6">
                <h3 className="mkt-body font-medium text-text-primary">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">{f.text}</p>
              </article>
            ))}
          </div>
          <p className="mkt-body mt-10 max-w-2xl font-medium text-text-primary">
            Fragmentation → Resolution → Governed action → Outcome. Aether exists to close that loop.
          </p>
        </div>
      </section>

      {/* How Aether works — the loop */}
      <section className="border-b border-border-default">
        <div className="mkt-container py-20 md:py-28">
          <Eyebrow>How Aether works</Eyebrow>
          <h2 className="mkt-h2 mt-4 max-w-2xl">A continuous, governed loop</h2>
          <p className="mkt-lead mt-4 max-w-2xl">
            Each turn of the loop resolves more of the graph, understands more of the relationship,
            and makes governed action more precise.
          </p>
          <ol className="mt-12 grid gap-4 lg:grid-cols-5">
            {LOOP.map((item) => (
              <li key={item.step} className="rounded-md border border-border-default p-5">
                <span className="font-mono text-xs text-text-muted">{item.step}</span>
                <h3 className="mt-3 text-base font-semibold text-text-primary">{item.name}</h3>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">{item.text}</p>
              </li>
            ))}
          </ol>
          <p className="mkt-body mt-10 max-w-2xl text-text-secondary">
            Every step states its problem, its inputs, what Aether understands, its output, its
            governance, and its limitations.
          </p>
        </div>
      </section>

      {/* Platform families */}
      <section className="border-b border-border-default bg-surface-sunken">
        <div className="mkt-container py-20 md:py-24">
          <Eyebrow>The platform</Eyebrow>
          <h2 className="mkt-h2 mt-4 max-w-2xl">Capability families across the full loop</h2>
          <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {FAMILIES.map((family) => (
              <Link
                key={family.name}
                to="/platform"
                className="group rounded-md border border-border-default bg-surface-base p-6 mkt-motion-color hover:border-accent"
              >
                <h3 className="mkt-body font-medium text-text-primary group-hover:text-accent">
                  {family.name}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">{family.text}</p>
              </Link>
            ))}
          </div>
          <p className="mt-8">
            <Button asChild variant="secondary" size="md">
              <Link to="/platform">Read the platform overview</Link>
            </Button>
          </p>
        </div>
      </section>

      {/* Governance / security */}
      <section className="border-b border-border-default">
        <div className="mkt-container grid gap-10 py-20 md:py-24 lg:grid-cols-2">
          <div>
            <Eyebrow>Governance</Eyebrow>
            <h2 className="mkt-h2 mt-4">Boundaries are the design</h2>
          </div>
          <div className="space-y-4">
            <p className="mkt-body text-text-secondary">
              Aether separates requested, authorized, executed, verified, and measured. Where
              verification is not available, the platform says <em>executed, verification pending</em> —
              it never visually implies certainty the runtime cannot prove.
            </p>
            <p className="mkt-body text-text-secondary">
              Consent, retention, tenant isolation, credential handling, and auditability are features,
              not afterthoughts.
            </p>
            <p>
              <Button asChild variant="secondary" size="md">
                <Link to="/security">Security model</Link>
              </Button>
            </p>
          </div>
        </div>
      </section>

      {/* Ownership */}
      <section className="border-b border-border-default bg-surface-sunken">
        <div className="mkt-container py-16 md:py-20">
          <Eyebrow>Aether, by Olympus Labs</Eyebrow>
          <div className="mt-6 flex max-w-2xl flex-col gap-6">
            <p className="mkt-lead">
              Aether is the product. Olympus Labs is the company that builds, owns, and operates it —
              including the private internal operator environment used to run the platform. On this
              site, ownership is stated plainly; inside the Aether product environment, Olympus Labs
              branding stays secondary to Aether.
            </p>
            <span className="flex items-center gap-2 text-sm text-text-secondary">
              <OlympusAttribution />
              <span aria-hidden="true">·</span>
              <a href={OLYMPUS_SITE_URL} className="underline underline-offset-2 mkt-motion-color hover:text-text-primary">
                olympuslabs.com
              </a>
            </span>
          </div>
        </div>
      </section>

      <CtaBand
        title="Start building on Aether"
        body="Aether is not yet generally available. When it opens to customers, this is the front door — create your workspace here and the Aether application takes over from there."
        primary={{ label: 'Start building', to: '/signup' }}
        secondary={{ label: 'See pricing', to: '/pricing' }}
      />
    </>
  );
}
