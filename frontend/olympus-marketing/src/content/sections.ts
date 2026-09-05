/**
 * Olympus Labs marketing section copy.
 *
 * Each section carries finished editorial prose in the Olympus corporate voice:
 * calm, serious, and truthful about what the platform can demonstrate today.
 * `slug`, `nav`, `eyebrow`, `title`, and `description` are the stable surface
 * identity (the SEO manifest and shell tests stay in parity with them); `lead`,
 * `paragraphs`, and `bullets` carry the page body. Optional `cta` names the one
 * true next action when a specific one exists; optional `links` point to the
 * real public surfaces this site can actually stand behind.
 */

import { AETHER_APP_URL, AETHER_DOCS_URL, AETHER_MARKETING_URL } from '../lib/env';

export interface SectionCta {
  readonly label: string;
  readonly to: string;
  readonly external?: boolean;
}

export interface SectionLink {
  readonly heading: string;
  readonly text?: string;
  readonly to: string;
  readonly external?: boolean;
}

export interface SectionCopy {
  readonly slug: string;
  readonly nav: string;
  readonly eyebrow: string;
  readonly title: string;
  readonly description: string;
  readonly lead: string;
  readonly paragraphs?: readonly string[];
  readonly bullets?: readonly { readonly heading: string; readonly text: string }[];
  readonly cta?: SectionCta;
  readonly links?: readonly SectionLink[];
}

export interface PrimaryLink {
  readonly to: string;
  readonly label: string;
  readonly external?: boolean;
}

/** Primary marketing navigation — Olympus Labs keeps the most spacious rhythm. */
export const PRIMARY_NAV: readonly PrimaryLink[] = [
  { to: '/company', label: 'Company' },
  { to: '/products', label: 'Products' },
  { to: '/research', label: 'Research' },
  { to: '/principles', label: 'Principles' },
  { to: '/security', label: 'Security' },
];

export const SECTIONS: readonly SectionCopy[] = [
  {
    slug: '/company',
    nav: 'Company',
    eyebrow: 'Company',
    title: 'A serious organization behind a long-term thesis',
    description: 'Who Olympus Labs is, what it believes, and why it builds Aether.',
    lead: 'Olympus Labs is the company that builds Aether. We build intelligence infrastructure with a governing philosophy — fragmentation gives way to connection, connection to understanding, understanding to governed action, and governed action to measurable outcomes — and we hold the product, and our own public writing, to the same standard of proof.',
    paragraphs: [
      'Most organizations run dozens of systems that each answer one narrow question: a CRM for accounts, a warehouse for facts, a commerce backend for orders, a queue for support. The result is not a failure of any single system — it is the absence of a layer that relates them. Olympus Labs exists to build that layer, and to build it as governed infrastructure rather than as one more tool running on good intentions.',
      'We are deliberately a product company with a research practice, not a research lab with a demo. The distinction governs how we ship: every capability we name corresponds to an observable behavior in the platform, and everything we claim in public corresponds to what the platform can demonstrate today. Where a capability is configured but not yet verified, or verified but not yet live, we say exactly that.',
      'Olympus Labs is a private, deliberately sized organization. Kyber is its internal operator application — how the company runs the platform day to day; Aether is the customer-facing product the public interacts with. The two share one design system, one status language, and one standard of accountability.',
    ],
    bullets: [
      { heading: 'Creator and operator', text: 'Olympus Labs owns and operates Aether and Kyber. Aether is its customer-facing relationship intelligence platform; Kyber is its private internal operator application.' },
      { heading: 'Research-informed', text: 'Our research and systems practice shapes the product roadmap and appears publicly as principles and written research.' },
      { heading: 'Accountable by design', text: 'We publish what we can prove, mark what remains uncertain, and keep operational claims behind internal surfaces.' },
    ],
  },
  {
    slug: '/products',
    nav: 'Products',
    eyebrow: 'Products',
    title: 'Infrastructure products built on one governed foundation',
    description: 'The Olympus Labs product family, led by Aether.',
    lead: 'Aether is the flagship. Kyber is how Olympus Labs operates the platform. Everything we build shares one design system, one motion philosophy, and one set of truthful status semantics.',
    paragraphs: [
      'Aether connects customer, entity, wallet, agent, campaign, communication, and commerce activity into a governed graph — so organizations can understand what happened, why it happened, and what to do next. It is the customer-facing product, and its full product, developer, integration, security, and pricing surfaces are documented on the Aether public site.',
      'Kyber is the operating environment Olympus Labs uses to run Aether: the internal console, automation, and control surfaces that keep the platform honest. Kyber exists to operate rather than to sell, so it is not exposed through public marketing and is never linked from these pages.',
      'Everything in the family shares one design system and one motion philosophy, so a user who has read one Olympus Labs surface can read the next without relearning the alphabet. The family also shares one status semantics: configured is not verified, verified is not live, and every surface names the state it is actually in.',
    ],
    bullets: [
      { heading: 'Aether', text: 'Olympus Labs’ customer-facing relationship intelligence platform. Public explanation lives on the Aether site.' },
      { heading: 'Kyber', text: 'Olympus Labs’ private internal operator application. It is not a customer product and is not linked from public marketing.' },
      { heading: 'One foundation', text: 'A single design system, motion philosophy, and status language spans the family, so surfaces read as one system.' },
    ],
    cta: { label: 'Read about Aether', to: '/products/aether' },
  },
  {
    slug: '/products/aether',
    nav: 'Aether',
    eyebrow: 'Featured product',
    title: 'Aether — relationship intelligence by Olympus Labs',
    description: 'Aether is Olympus Labs’ relationship intelligence platform.',
    lead: 'Aether is Olympus Labs’ relationship intelligence platform: fragmented systems become connected events and entities, connected events become relationship intelligence, and intelligence becomes governed decisions with verifiable outcomes.',
    paragraphs: [
      'Aether is relationship intelligence, not another database or dashboard. It draws activity from the systems an organization already runs and relates it into a governed graph of customers, entities, wallets, campaigns, and journeys — the raw material for understanding a relationship over time rather than a single transaction within it.',
      'The platform is explicit about what it knows, what it can prove, and what remains uncertain. Recommendations, rewards, communications, and campaign actions run only through explicit governance and consent, and decisions leave an auditable record. That truthfulness is a design principle, not a caveat.',
      'This page is the bridge: the short version of what Aether is and why Olympus Labs built it. The full surface — solutions, developers, integrations, security, and pricing — lives on the Aether public site, which is the front door for evaluating the platform.',
    ],
    bullets: [
      { heading: 'Understand', text: 'Identity, graph, journeys, campaign intelligence — what happened and why.' },
      { heading: 'Act', text: 'Recommendations, rewards, communications, campaign actions — governed decisions.' },
      { heading: 'Measure', text: 'Outcome attribution that feeds evidence back into the graph.' },
    ],
  },
  {
    slug: '/research',
    nav: 'Research',
    eyebrow: 'Research',
    title: 'Systems thinking, published',
    description: 'How Olympus Labs thinks about intelligence, governance, identity, and outcomes.',
    lead: 'Our research practice is public by default. We write about relationship intelligence, identity resolution, governed action, outcome measurement, and the boundaries of what an intelligence system should claim.',
    paragraphs: [
      'The central visual metaphor across the product family is relationships resolving into understandable systems. Research is where the underlying model is stated plainly — not as marketing, but as the reasoning a reader can check against the product and against the world.',
      'The written work starts where the platform starts: fragments of activity resolve into connected entities and journeys; entities and journeys resolve into understanding; and understanding resolves into action only through explicit, auditable governance. Each step in that chain is worth its own careful argument.',
      'Research also constrains marketing. The same standard that governs the product applies to what we publish here: a claim that cannot be substantiated by an observable behavior is a claim we do not make, and a question we cannot yet answer is left open rather than smoothed over.',
    ],
    bullets: [
      { heading: 'Relationship intelligence', text: 'How fragmented activity resolves into entities, journeys, and customer understanding.' },
      { heading: 'Identity resolution', text: 'What a single identifier should and should not be trusted to mean across systems.' },
      { heading: 'Governed agency', text: 'Why understanding becomes action only through consent, review, and audit.' },
      { heading: 'Outcome measurement', text: 'How evidence from decisions flows back into the graph and sharpens the next one.' },
    ],
  },
  {
    slug: '/principles',
    nav: 'Principles',
    eyebrow: 'Principles',
    title: 'The operating philosophy behind the platform',
    description: 'Olympus Labs principles for building governed intelligence systems.',
    lead: 'Principles are how a company stays coherent across products, years, and decisions it has not made yet.',
    paragraphs: [
      'We build calm, deliberate, technically credible systems. Motion explains, orients, or confirms — or it is removed. The visual language stays consistent across the product family because a user should never have to decode a surface before they can use it.',
      'Status is truthful or it is not status. Configured is not verified, and verified is not live; we say which state we are in, in the product, in research, and in marketing, because the credibility of the whole system rests on the accuracy of its smallest status.',
      'Understanding leads to action only through explicit, auditable governance. Autonomy is earned in degrees, each one gated by consent, review, and a record that can be examined later. A capability we cannot substantiate is a capability we do not claim.',
    ],
    bullets: [
      { heading: 'Calm over noise', text: 'Nothing moves merely because it can. Ambience is ambient only where it is appropriate.' },
      { heading: 'Truthful status', text: 'Configured is not verified. Verified is not live. We say which state we are in.' },
      { heading: 'Governed agency', text: 'Understanding leads to action only through explicit, auditable governance.' },
    ],
  },
  {
    slug: '/security',
    nav: 'Security',
    eyebrow: 'Security',
    title: 'Responsibility as an architectural property',
    description: 'How Olympus Labs approaches security, isolation, and accountability.',
    lead: 'Security is not a page on a marketing site; it is an architectural property of tenant isolation, credential handling, authorization, consent, retention, and audit. Marketing describes the boundary. The platform enforces it.',
    paragraphs: [
      'The company treats security as a set of architectural responsibilities rather than a checklist. Tenant boundaries, credential handling, authorization, consent, retention, and audit are properties the platform is designed around, not behaviors bolted on after the fact and described from the outside.',
      'Public security material never implies certainty the runtime cannot prove. Where verification is pending, we say verification pending; where a control is configured but not yet exercised, we say configured. The platform’s own security surface is where controls are documented in full and kept current with what actually ships.',
      'Olympus Labs operates its own systems and the Aether platform under the same discipline it asks of the product. Operational claims live behind internal surfaces, and public statements track only what an external party can reasonably rely on today.',
    ],
    bullets: [
      { heading: 'Tenant isolation', text: 'Data, sessions, and workloads are separated by tenant, with the boundary treated as an enforced platform property rather than an operational nicety.' },
      { heading: 'Consent and audit', text: 'Actions run under explicit, revocable consent and leave records that can be reviewed.' },
      { heading: 'Truthful posture', text: 'Public security copy names only states the platform can demonstrate; verification pending is stated as verification pending.' },
    ],
  },
  {
    slug: '/careers',
    nav: 'Careers',
    eyebrow: 'Company',
    title: 'Work on governed intelligence infrastructure',
    description: 'Careers at Olympus Labs.',
    lead: 'We hire people who care about the difference between a demo and an accountable system. When a role opens, it is posted on this page.',
    paragraphs: [
      'Olympus Labs is a product company with a research practice, building relationship intelligence infrastructure that turns fragmented customer activity into governed, measurable outcomes. We are deliberately sized — small enough that every person carries real surface area, and structured enough that decisions are reviewed and recorded rather than improvised.',
      'We hire for judgment as much as for skill. People who thrive here care about the difference between a demo and an accountable system: they read the same public copy we publish, hold the company to the same standards it holds the platform, and expect their work to be observable, verifiable, and honestly described.',
      'The company operates Aether, its customer-facing platform, and Kyber, its private internal operator environment. Work spans building, operating, writing, and verifying the systems the team ships — the same discipline that keeps marketing honest also shapes engineering. The work is calm and deliberate, and status is truthful or it is not status.',
      'Open roles are shared on this page when they are posted, with the requirements and the team behind each role described plainly — with the same specificity we expect from the surfaces we build.',
    ],
    bullets: [
      { heading: 'Real surface area', text: 'A deliberately sized company means each role spans build, operate, write, and verify — not a narrow slice of one.' },
      { heading: 'Governed, not bureaucratic', text: 'Decisions are reviewed and recorded because trust depends on a record — not for the sake of process.' },
      { heading: 'Honest surfaces', text: 'What we ship publicly must match what the platform can demonstrate. The discipline applies to engineering as much as to marketing.' },
    ],
  },
  {
    slug: '/contact',
    nav: 'Contact',
    eyebrow: 'Company',
    title: 'Contact Olympus Labs',
    description: 'Reach Olympus Labs and explore Aether.',
    lead: 'The fastest path depends on what you need. If your organization uses Aether, product support and documentation are the direct channel; if you are evaluating the platform, the public Aether site is the front door. The real surfaces Olympus Labs maintains are listed on this page.',
    paragraphs: [
      'For customers and partners using Aether, the documentation site and the in-product support surfaces are the direct channel for setup, integration, and troubleshooting, and they are maintained by the platform team. Product sign-in is on the application origin; documentation is where behavior is defined and questions get answered.',
      'A public status page for the Aether platform is in planning and is not yet published. Until it is live, direct an availability question or a suspected incident to the support and documentation surfaces on this page rather than to a surface that does not yet exist.',
      'For company, research, partnership, and press interest, the clearest public starting point is the Aether site and the surfaces linked from these pages. Olympus Labs publishes only the channels it actually maintains and monitors; if a channel is not listed here, it is not a channel we ask you to use.',
    ],
    links: [
      { heading: 'Product sign-in', text: 'Aether users sign in on the application origin.', to: AETHER_APP_URL, external: true },
      { heading: 'Documentation and support', text: 'Setup, integration, and troubleshooting material for the platform.', to: AETHER_DOCS_URL, external: true },
    ],
    cta: { label: 'Explore Aether', to: AETHER_MARKETING_URL, external: true },
  },
  {
    slug: '/legal',
    nav: 'Legal',
    eyebrow: 'Legal',
    title: 'Legal and trust material',
    description: 'Olympus Labs legal notices.',
    lead: 'Terms, privacy, and corporate notices for Olympus Labs and the Aether product family.',
    paragraphs: [
      'This page is the single place where Olympus Labs publishes legal and trust material that governs its public properties — the corporate site, the Aether public site, and the Aether application. Material appears here when it is current and in force; nothing on this page is boilerplate, and nothing is published before it is real.',
      'Olympus Labs keeps its legal writing in the same voice as the rest of the company: plain, specific, and free of claims the product cannot support. Where a notice applies to a single property, it is scoped to that property; corporate-wide notices are collected here so there is one address for trust material rather than a scattering of pages.',
      'The most current operational and trust surfaces live where the product is used and documented: the Aether documentation and public site carry the security and platform material the product references, and a public status page for the platform is in planning. Legal notices that govern a specific surface are presented at the point of acceptance on that surface as the product family ships.',
    ],
    links: [
      { heading: 'Aether documentation', text: 'Platform behavior, setup, and trust material maintained with the product.', to: AETHER_DOCS_URL, external: true },
      { heading: 'Aether public site', text: 'The public Aether platform and its security surfaces.', to: AETHER_MARKETING_URL, external: true },
    ],
  },
];

export function findSection(pathname: string): SectionCopy | undefined {
  return SECTIONS.find((s) => s.slug === pathname);
}
