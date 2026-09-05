/**
 * Aether public marketing section copy.
 *
 * Each top-level section carries real editorial depth in Aether product voice:
 * an eyebrow, title, description, lead, substantive paragraphs, and, where
 * structure helps, bullets plus an optional call-to-action pointing at a real
 * next step. Copy is truthful by construction — it never claims capability,
 * integration, or availability that the platform runtime cannot substantiate.
 */

import { AETHER_DOCS_URL } from '../lib/env';

export interface SectionCopy {
  readonly slug: string;
  readonly nav: string;
  readonly eyebrow: string;
  readonly title: string;
  readonly description: string;
  readonly lead: string;
  readonly paragraphs?: readonly string[];
  readonly bullets?: readonly { readonly heading: string; readonly text: string }[];
  /** Optional primary call-to-action. External destinations open in a new tab;
   * internal section routes navigate with the router. */
  readonly cta?: { readonly label: string; readonly to: string; readonly external?: boolean };
}

export interface PrimaryLink {
  readonly to: string;
  readonly label: string;
  readonly external?: boolean;
}

/** Aether primary product navigation. */
export const PRIMARY_NAV: readonly PrimaryLink[] = [
  { to: '/platform', label: 'Platform' },
  { to: '/solutions', label: 'Solutions' },
  { to: '/developers', label: 'Developers' },
  { to: '/integrations', label: 'Integrations' },
  { to: '/security', label: 'Security' },
  { to: '/pricing', label: 'Pricing' },
];

export const SECTIONS: readonly SectionCopy[] = [
  {
    slug: '/platform',
    nav: 'Platform',
    eyebrow: 'Platform',
    title: 'One governed graph across the activity that shapes outcomes',
    description: 'The Aether platform — identity resolution, intelligence graph, journey, campaign, communications, financial observability, agents, outcomes, and governance.',
    lead: 'Aether connects customer, entity, wallet, agent, campaign, communication, and commerce activity into a governed graph. Identity resolution turns disconnected identifiers into people, accounts, devices, wallets, and organizations. Intelligence turns that graph into journeys, campaign movement, behavior, and context. Governed action turns understanding into recommendations, rewards, communications, and operational decisions — and outcome attribution turns decisions back into evidence.',
    paragraphs: [
      'The platform organizes its surface into capability families: identity and entity resolution, the intelligence graph, journey intelligence, campaign intelligence, communications intelligence, financial observability, agent access intelligence, rewards and activation, outcome attribution, governance and consent, and integrations and data quality. Each family documents itself in one consistent form so practitioners can compare honestly — the problem it addresses, the inputs it consumes, what Aether understands from those inputs, the output it produces, the governance and consent that apply, and the limits the runtime actually honors. A capability is described at the maturity the runtime can demonstrate; nothing on the platform is advertised as fuller than it is.',
      'The graph is the spine every family reads from and writes to. The same resolved identity that holds a wallet address is the identity that received a campaign message, opened a support ticket, and earned a reward, so context accumulates in one place instead of fragmenting across systems. Because relationships carry consent, retention, and lineage with them, an analysis never has to reassemble a person’s history from silos after the fact.',
      'Governance is how the loop stays safe, not a wrapper applied afterward. Actions move through requested, authorized, executed, verified, and measured states, and where the runtime cannot verify an action it reports executed, verification pending rather than implying certainty it does not have. Tenant isolation, credential handling, consent, retention, and auditability are documented properties of the design rather than aspirational notes.',
      'Aether is deliberately read-first: teams resolve, understand, and govern before they act, and operators can inspect the evidence behind any decision. That discipline is what makes a governed relationship graph appropriate where the activity is sensitive and the consequences of action are real. Each capability family described here carries that discipline forward into specific detail.',
    ],
    bullets: [
      { heading: 'Connect', text: 'Events, profiles, transactions, communications, agents, and integrations arrive through governed connectors.' },
      { heading: 'Resolve', text: 'People, accounts, devices, wallets, organizations, and systems resolve into one entity model.' },
      { heading: 'Understand', text: 'Journeys, graph relationships, campaign movement, behavior, and context become intelligence.' },
      { heading: 'Act', text: 'Recommendations, rewards, communications, campaign actions, and operational decisions are governed.' },
      { heading: 'Measure', text: 'Decisions connect to outcomes, and evidence feeds back into the graph.' },
    ],
  },
  {
    slug: '/solutions',
    nav: 'Solutions',
    eyebrow: 'Solutions',
    title: 'Built for the shape of your business',
    description: 'Aether solutions — customer intelligence, commerce, SaaS, fintech, Web3, AI-native, enterprise, and public sector.',
    lead: 'Solutions show how the platform applies to specific situations: the friction you face, the transformation Aether enables, the capabilities involved, and how governance is handled. Where no real customer evidence exists, scenarios are labeled as illustrative product scenarios — never fabricated case studies.',
    paragraphs: [
      'Each solution on this page follows one narrative so different situations can be compared fairly. A solution states the situation a kind of business is in, the friction that situation creates, and the transformation Aether enables. It then walks through a realistic scenario of the transformation in practice, the Aether capabilities involved, an implementation model, the governance considerations, and the evidence that exists today.',
      'Reading one solution teaches the structure of the rest, so the comparison between approaches is explicit rather than buried. Aether publishes no fabricated case studies, customer stories, or testimonials. Where no real customer evidence exists, a solution’s scenario is labeled an illustrative product scenario — a plausible application described in Aether’s own terms and clearly distinguished from a deployed, measured result.',
      'The solution set spans customer intelligence, commerce, SaaS, fintech, Web3, AI-native businesses, the enterprise, and the public sector. The shapes differ, but the discipline is shared: fragmented activity resolves into one governed graph, and action is taken on evidence rather than guesswork. Governance and consent considerations are called out per audience, because the stakes and the regulations differ between a consumer commerce relationship and a regulated public-sector one.',
    ],
    cta: { label: 'Explore the platform', to: '/platform' },
  },
  {
    slug: '/developers',
    nav: 'Developers',
    eyebrow: 'Developers',
    title: 'Integrate once. Resolve everywhere.',
    description: 'Aether developer surface — SDKs, event model, identity resolution, consent, validation, and technical documentation.',
    lead: 'The developer surface answers the integration questions directly: which SDK to use, what the event model is, how identity resolution works, how consent works, how integrations behave, and how to validate a first event.',
    paragraphs: [
      'The developer surface answers integration questions directly: which SDK to use, what the event model is, how identity resolution works, how consent works, how integrations behave, and how to validate a first event. Each answer states its inputs, outputs, error behavior, and limits rather than presenting integration as frictionless. When a step requires a configuration or a credential, the material says so before you begin.',
      'Full technical documentation lives on the documentation site and is the canonical reference for schemas, SDKs, the event model, identity resolution, consent, and validation. The pages here orient you and point to that reference; they do not pretend to replace it. Following the reference from a first event through identity resolution is the intended path into the platform.',
      'Integrations obey the same truthful availability discipline as the rest of the platform. A connector is described at its real availability state, and code paths that the runtime does not yet support are not presented as ready. Consent and governance are part of the developer contract rather than an add-on layer bolted on after the integration works.',
    ],
    bullets: [
      { heading: 'Event model', text: 'What an event carries, how it is validated, and where it lands in the graph.' },
      { heading: 'Identity resolution', text: 'How identifiers resolve into people, accounts, devices, wallets, and organizations — with lineage.' },
      { heading: 'Consent & governance', text: 'How consent, retention, and authorization attach to the activity an integration brings in.' },
      { heading: 'Validation', text: 'How to validate a first event and confirm the integration behaves before production traffic.' },
    ],
    cta: { label: 'Read the technical documentation', to: AETHER_DOCS_URL, external: true },
  },
  {
    slug: '/integrations',
    nav: 'Integrations',
    eyebrow: 'Integrations',
    title: 'Connectors with truthful availability states',
    description: 'Aether integrations directory — search by provider, category, use case, authentication type, data direction, and availability.',
    lead: 'The integration directory tells the truth about every connector: what capability it supports, its inputs and outputs, how it authenticates, how data synchronizes, its limits and error behavior — and its actual availability state.',
    paragraphs: [
      'The integration directory tells the truth about every connector. For each one it states which capability is supported, what the inputs and outputs are, how the connector authenticates, and how data synchronizes. It also records the connector’s limits and error behavior alongside its actual availability state, so entries are useful to the person wiring the connection and not just the person evaluating it at a distance.',
      'Availability is stated as a set of real states: available, beta, credential required, configuration required, planned, and unsupported. A connector that requires a credential or configuration is labeled that way, and a partially configured system is never marked fully active. The states keep the directory honest as integrations move through the lifecycle.',
      'A connector referenced here reflects an availability state from the runtime registry — it is not a blanket promise that every provider is live or partner-live. Where the runtime records a connector as planned rather than available, the directory says planned. Where data direction or authentication constrains a connector, those constraints are part of the entry, and connector detail is added as it is published, never invented.',
      'You can reason about a connector before choosing it the same way you would about a prospective vendor. Category, use case, authentication type, and data direction frame the fit. The documented limits sit beside the documented capability, so the decision is made on what the runtime actually does.',
    ],
    cta: { label: 'Read the integration documentation', to: AETHER_DOCS_URL, external: true },
  },
  {
    slug: '/security',
    nav: 'Security',
    eyebrow: 'Security',
    title: 'Boundaries are the design',
    description: 'Aether security — tenant isolation, credential handling, authorization, consent, retention, auditability, and deployment models.',
    lead: 'Security material explains the boundary: requested → authorized → executed → verified → measured. Where verification is not available, the platform says executed, verification pending. It never visually implies certainty the runtime cannot prove.',
    paragraphs: [
      'Security material explains the boundary the platform actually enforces: requested, authorized, executed, verified, and measured. Where the runtime cannot verify that an action occurred, the platform reports executed, verification pending. It never visually implies certainty it cannot prove — the calm precision of these pages is the point rather than an accident.',
      'The security surface walks through tenant isolation, credential handling, authorization, consent, data retention, auditability, deployment models, and the division of responsibility between customer and platform. Each topic states what the platform does and what it does not do. That lets a reader assess fit instead of absorbing assurances.',
      'Consent, retention, and auditability are product features that live in the graph, not paperwork bolted on after an incident. Because the design carries the boundary, the copy does not need to inflate it. That is why the security pages are intentionally calmer than the rest of the marketing site.',
    ],
  },
  {
    slug: '/pricing',
    nav: 'Pricing',
    eyebrow: 'Pricing',
    title: 'Pricing that matches usage, not guesswork',
    description: 'Aether pricing — plan audience, usage limits, capabilities, support, retention, environments, integration limits, and deployment options.',
    lead: 'Aether is not yet generally available. When it opens to customers, pricing will be separated from account creation: plans will state their intended audience, usage limits, capabilities, support, retention, environments, integration limits, and upgrade triggers, and enterprise options will be described where they exist.',
    paragraphs: [
      'Aether is not yet generally available, and the detailed pricing tables on this page ship with general availability rather than ahead of it. When the platform opens to customers, plans will state their intended audience, usage limits, capabilities, support, retention, environments, and integration limits — and the conditions that trigger a move between plans, so growth does not arrive as a surprise.',
      'The interactive pricing estimator will be based on real plan logic only. Where a precise estimate would require pricing data the platform does not hold, the estimator will say so instead of faking precision, and no tool will pretend to produce a number the logic cannot support.',
      'Enterprise and deployment options will be described where they exist, including the environment and integration questions a procurement or security team will ask. The goal is a pricing page a team can bring into a budget review. A reader should not need a sales conversation to decode what a plan includes and what it does not.',
    ],
  },
  {
    slug: '/resources',
    nav: 'Resources',
    eyebrow: 'Resources',
    title: 'Guides, research, and product notes',
    description: 'Aether resources — guides, research, changelog, webinars, and future case material.',
    lead: 'Aether is not yet generally available. When the resources section is populated, every piece will be labeled by type, topic, audience, reading time, publication or update date, product area, and status, so you can judge before you open it whether it is for you. No case study is fabricated; material that does not yet exist is not listed as customer evidence.',
    paragraphs: [
      'The resources section will carry the kinds of material a platform team actually needs: developer guides that work through real integration problems, product notes that explain how a capability behaves and why it is designed that way, and research that lays out the questions behind the design. Each piece will be labeled by type, topic, audience, reading time, publication or update date, product area, and status, so a reader can judge fit before opening it.',
      'Developer guides will be written toward the event model, identity resolution, consent, and validation — the same discipline the developer pages teach — and will point at the documentation site where the canonical technical reference lives rather than duplicating it. Product notes will describe behavior and limitations honestly, including what the runtime does not yet do.',
      'Aether does not fabricate case studies, customer stories, or testimonials, and nothing is back-dated. Where a scenario is illustrative rather than measured, it is labeled as such. Material that has not been published is simply not listed, and the status label on a published resource tells you what kind of evidence stands behind it.',
      `The canonical technical reference for Aether today lives on the documentation site at ${AETHER_DOCS_URL}. New resource material is added to this section as it is published, never ahead of it.`,
    ],
    bullets: [
      { heading: 'Developer guides', text: 'Walk through real integration problems — event model, identity resolution, consent, and validation — and point to the canonical reference.' },
      { heading: 'Product notes', text: 'Explain how a capability behaves, why it is designed that way, and what it does not yet do.' },
      { heading: 'Research', text: "Aether's own analysis of the questions behind the design — always labeled, never passed off as third-party findings." },
      { heading: 'Changelog & events', text: 'Release-oriented notes and webinars, each labeled with its audience and date so you can judge relevance.' },
    ],
    cta: { label: 'Browse the documentation', to: AETHER_DOCS_URL, external: true },
  },
  {
    slug: '/company',
    nav: 'Company',
    eyebrow: 'Company',
    title: 'Aether is a product of Olympus Labs',
    description: 'The Olympus Labs relationship — who builds and operates Aether.',
    lead: 'Olympus Labs builds Aether. Aether is the product; Olympus Labs is the company — the creator, owner, and operator of the platform, including the private internal operator environment used to run it.',
    paragraphs: [
      'Aether is a product of Olympus Labs. Olympus Labs is the company that builds, owns, and operates the platform, including the private internal operator environment used to run it. On this public site that relationship is stated plainly; inside the Aether product environment, Olympus Labs branding stays secondary to Aether.',
      'The two names mark different things. Aether is the relationship intelligence platform Olympus Labs builds for customers and partners. Olympus Labs is the organization behind it, and the corporate site at olympuslabs.com carries the broader company narrative while this site stays focused on the Aether product.',
      'The relationship is meant to be legible rather than layered. What Olympus Labs says about Aether on a corporate surface has to match what the platform actually does. The same governance discipline that governs customer relationships governs the platform’s own operator environment, so where Aether publishes availability, security, and ownership commitments, those pages describe reality rather than aspiration.',
    ],
    bullets: [
      { heading: 'Creator & operator', text: 'Olympus Labs builds, owns, and operates Aether, including the private internal operator environment used to run the platform.' },
      { heading: 'One brand hierarchy', text: 'Inside the Aether product, Olympus Labs branding stays secondary to Aether; on this public site, ownership is stated plainly.' },
    ],
  },
];

export function findSection(pathname: string): SectionCopy | undefined {
  return SECTIONS.find((s) => s.slug === pathname);
}
