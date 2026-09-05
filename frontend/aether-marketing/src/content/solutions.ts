/**
 * Aether public solution copy — the deep pages behind the /solutions section.
 *
 * Each solution states the situation a kind of business is in, the friction that
 * situation creates, and the transformation Aether enables, then walks a
 * realistic scenario in practice, the Aether capability families involved, an
 * implementation model, the governance considerations, and the evidence that
 * exists today.
 *
 * Truth discipline is inherited from the section copy and made stricter here:
 * no fabricated case studies, customer stories, testimonials, metrics, logos, or
 * quotes. Every scenario is labeled with the canonical `SOLUTION_LABEL` — an
 * illustrative product scenario written in Aether's own terms, never a measured
 * customer result. Capability names reference families the platform itself
 * describes (identity and entity resolution, the intelligence graph, journey,
 * campaign, communications, financial observability, agent access, rewards and
 * activation, outcome attribution, governance and consent, and integrations and
 * data quality). A capability Aether cannot substantiate is not claimed.
 */

/** The literal label every scenario carries so no reader mistakes it for a case study. */
export const SOLUTION_LABEL: 'Illustrative product scenario' = 'Illustrative product scenario';

export interface SolutionCopy {
  readonly slug: string; // kebab, e.g. 'customer-intelligence'; becomes /solutions/<slug>
  readonly title: string; // deep-page H1 and SEO <title> base
  readonly shortName: string; // short card label
  readonly description: string; // 1-2 sentence SEO description AND card summary
  readonly audience: string; // who this solution is for (one or two sentences)
  readonly situation: string; // the situation this kind of business is in
  readonly friction: string; // the friction that situation creates
  readonly transformation: string; // the transformation Aether enables
  readonly scenarioLabel: 'Illustrative product scenario'; // literal label used verbatim
  readonly scenario: string; // an illustrative product scenario, not a measured customer result
  readonly capabilities: readonly string[]; // Aether capability families involved, by family name
  readonly implementation: string; // how a team would adopt it, in guarded, truthful terms
  readonly governance: string; // per-audience governance stakes, stated honestly
  readonly evidence: string; // what evidence exists today; explicit when design/product-scenario only
}

export const SOLUTIONS: readonly SolutionCopy[] = [
  {
    slug: 'customer-intelligence',
    title: 'Customer intelligence on one governed graph',
    shortName: 'Customer intelligence',
    description:
      'How Aether turns fragmented customer activity into one governed graph — resolved identity, journey and campaign intelligence, and communications under shared consent.',
    audience:
      'For product, growth, and data teams in consumer-facing businesses that need a single governed view of a customer across devices, channels, accounts, and support.',
    situation:
      'Customer activity arrives through many systems at once — a web session, an app event, a support ticket, an email, a purchase, a wallet address — and no single system holds the whole relationship.',
    friction:
      'Because identifiers never meet in one place, one person can be counted as several, journeys have to be reassembled from silos after the fact, and consent cannot reliably travel with the person it describes. Every decision is built from a partial picture, and every outbound action risks acting on stale or incomplete context.',
    transformation:
      'Aether resolves the fragments into one governed graph before any analysis begins. Journeys, campaign movement, behavior, and context are then read from that graph — against the same resolved identity, consent, and retention that describe the person — so customer intelligence and the action it supports share one ground truth.',
    scenarioLabel: SOLUTION_LABEL,
    scenario:
      'In an illustrative product scenario, a subscription retailer connects web, app, support, and commerce events into a single Aether workspace. Aether resolves the visitor, the account, the device, and the order history into one profile with visible lineage, and the team reads a journey across every touchpoint under a single consent record before deciding whether to send any message at all.',
    capabilities: [
      'Identity and entity resolution',
      'Intelligence graph',
      'Journey intelligence',
      'Campaign intelligence',
      'Communications intelligence',
      'Governance and consent',
    ],
    implementation:
      'Adoption starts read-first. A team connects one or two event sources in a workspace, validates events against the documented event model, and resolves a bounded set of identities before wiring any outbound capability. Understanding can be built and inspected without taking a single action.',
    governance:
      'Consumer relationships sit inside privacy regulation — the GDPR in the EU, the CCPA/CPRA in California, and sector rules elsewhere. Aether carries consent, retention, and authorization as properties of the graph, and the operating team remains responsible for configuring them to its jurisdiction and for deciding what it acts on.',
    evidence:
      'The evidence that exists today is the platform’s own public material: the documentation on the event model, identity resolution, consent, and connectors, and the design described on these pages. Aether publishes no customer case studies or measured customer outcomes; the scenario above is an illustrative product scenario, not a deployed result.',
  },
  {
    slug: 'commerce',
    title: 'Commerce on a governed relationship graph',
    shortName: 'Commerce',
    description:
      'How Aether connects commerce, payments, support, and rewards activity to one governed graph so lifecycle decisions run on the full relationship.',
    audience:
      'For ecommerce and retail operators — brands, marketplaces, and direct-to-consumer businesses — who need purchase, support, reward, and communication activity in one governed record.',
    situation:
      'Commerce runs across storefront, checkout, payments, fulfillment, support, and post-purchase. Each step records its own slice of the relationship in its own system.',
    friction:
      'A buyer and an account can fragment across order, refund, support ticket, loyalty balance, and marketing list. Retention and lifecycle decisions therefore run on order snapshots rather than on the relationship, and reward or refund actions are hard to connect back to the person who earned them.',
    transformation:
      'Aether links commerce activity — orders, ledgers, rewards, communications, support — to the resolved buyer, so campaigns, rewards, and service actions are governed by one view of the relationship and one consent record.',
    scenarioLabel: SOLUTION_LABEL,
    scenario:
      'In an illustrative product scenario, a merchant connects storefront, payment, and support events to an Aether workspace. Aether resolves the shopper, the account, and the wallet, ties each order and refund to that profile with lineage, and the team launches a lifecycle campaign and a reward program from the same graph it audits.',
    capabilities: [
      'Identity and entity resolution',
      'Intelligence graph',
      'Financial observability',
      'Communications intelligence',
      'Campaign intelligence',
      'Rewards and activation',
      'Outcome attribution',
      'Governance and consent',
    ],
    implementation:
      'A team begins by wiring the connectors whose availability the runtime records and validating events end to end. Rewards and campaign actions are introduced after identities resolve and after the team has set the consent and retention those actions depend on.',
    governance:
      'Commerce activity carries consumer privacy duties and, where payments are involved, financial recordkeeping expectations. Reward balances and refunds move through the same consent and authorization model as every other action, and the operating team remains accountable for the rules of its payment stack and jurisdiction.',
    evidence:
      'Evidence today is Aether’s public documentation and the design on these pages. No merchant case study or measured revenue result is published or implied; the scenario above is illustrative product-scenario material.',
  },
  {
    slug: 'saas',
    title: 'SaaS on a governed account graph',
    shortName: 'SaaS',
    description:
      'How Aether resolves users, accounts, and organizations into one governed graph so product-led businesses read usage, billing, and support as one relationship.',
    audience:
      'For product, growth, and revenue teams in SaaS and subscription software companies who must read usage, billing, support, and sales as one account relationship.',
    situation:
      'A SaaS business records product usage, billing, support, and sales in separate systems, with many users under one paying account and many accounts under one organization.',
    friction:
      'Usage events rarely resolve to the billable account, so expansion and retention signals stay disconnected from the commercial relationship. Sales, support, and product each act on a different slice of the same customer.',
    transformation:
      'Aether resolves users, accounts, and organizations into one entity model, then lets journey and campaign intelligence read product and commercial activity against that model — so adoption, expansion, and churn risk are understood in one place.',
    scenarioLabel: SOLUTION_LABEL,
    scenario:
      'In an illustrative product scenario, a B2B SaaS team connects product usage, billing, and support events to an Aether workspace. Aether resolves each user to the account and each account to the organization with lineage, and the team reads an expansion journey across activation, usage, and support before it triggers a single commercial touch.',
    capabilities: [
      'Identity and entity resolution',
      'Intelligence graph',
      'Journey intelligence',
      'Campaign intelligence',
      'Communications intelligence',
      'Outcome attribution',
      'Governance and consent',
    ],
    implementation:
      'The team starts by resolving a bounded set of accounts and organizations read-first, then layers campaign and lifecycle intelligence once resolution is trustworthy. Because identity is resolved before action, the commercial signals and the actions they feed share one model.',
    governance:
      'SaaS end-user data is still personal data under the GDPR and comparable regimes even in business-to-business contexts, and enterprise contracts add obligations of their own. Aether applies the same consent, retention, and auditability discipline to account and organizational relationships, and the operating team configures it to its contracts and jurisdictions.',
    evidence:
      'The evidence today is Aether’s public documentation and the design on these pages. No SaaS customer outcome is published; the scenario above is an illustrative product scenario, not a measured result.',
  },
  {
    slug: 'fintech',
    title: 'Fintech on one governed graph',
    shortName: 'Fintech',
    description:
      'How Aether keeps financial observability, communications, and customer context in one auditable, consent-governed graph — without overclaiming regulatory function.',
    audience:
      'For fintech product, operations, and compliance-adjacent teams who need financial activity, communications, and customer context in one governed record.',
    situation:
      'Fintech companies move money across accounts, cards, wallets, and rails while support, marketing, and risk teams each keep their own record of the customer.',
    friction:
      'Financial activity is the most sensitive activity a relationship graph can hold. When the ledger view and the customer view do not share an identity, an operator cannot easily show what a customer was told, what happened to their money, and who authorized it — which is exactly what auditors and customers ask.',
    transformation:
      'Aether ties financial observability to the same resolved identity that carries communications and journeys, so ledger effects, messages, and consent live in one relationship record with lineage and auditability by design.',
    scenarioLabel: SOLUTION_LABEL,
    scenario:
      'In an illustrative product scenario, a fintech team connects account, card, and support events to an Aether workspace. Aether resolves the account holder across product lines, and the team can follow a single relationship from a support conversation to the ledger effect it produced, with the authorization and consent trail visible at each step.',
    capabilities: [
      'Identity and entity resolution',
      'Intelligence graph',
      'Financial observability',
      'Communications intelligence',
      'Outcome attribution',
      'Governance and consent',
    ],
    implementation:
      'Because the stakes are high, adoption is deliberately narrow first: a team resolves a bounded population and exercises read-only financial observability before any outbound or money-touching action is wired. Actions are introduced only after authorization, consent, and retention are configured and reviewed.',
    governance:
      'Regulated financial activity carries recordkeeping, reporting, and consumer-protection duties that vary by jurisdiction and product. Aether is not a compliance or anti-money-laundering system and makes no such claim; its auditability and consent model is designed to support the record an operating team is already required to keep, and that team remains accountable for its regulatory obligations.',
    evidence:
      'Evidence today is Aether’s public documentation and the security and governance design on these pages. There are no fintech deployments, metrics, or regulatory endorsements to cite; the scenario above is an illustrative product scenario.',
  },
  {
    slug: 'web3',
    title: 'Web3 on one governed graph',
    shortName: 'Web3',
    description:
      'How Aether resolves wallets, on-chain activity, and off-chain context into one governed graph for Web3 businesses.',
    audience:
      'For Web3 teams — protocols, applications, and communities — who operate across wallets, on-chain activity, tokens, and off-chain product surfaces.',
    situation:
      'A Web3 business sees pseudonymous wallet activity, community and support conversations, and token or reward movement in separate places, often under different identities.',
    friction:
      'A wallet address is an identity, but it rarely arrives with context or consent. Teams struggle to connect on-chain behavior to off-chain service and communication without flattening pseudonymity or guessing at who controls an address.',
    transformation:
      'Aether treats wallets and entities as first-class identities that resolve and carry lineage under the consent the user has actually given. On-chain and off-chain activity can then be read together, and rewards or agent actions are governed by the same model.',
    scenarioLabel: SOLUTION_LABEL,
    scenario:
      'In an illustrative product scenario, a Web3 application connects wallet, community, and support events to an Aether workspace. Aether resolves the wallet to an entity with the consent and lineage that entity granted, and the team views a journey across on-chain and off-chain activity before it sends a communication or distributes a reward.',
    capabilities: [
      'Identity and entity resolution',
      'Intelligence graph',
      'Rewards and activation',
      'Agent access intelligence',
      'Financial observability',
      'Communications intelligence',
      'Governance and consent',
    ],
    implementation:
      'Teams begin read-first: connecting wallet and community events, resolving a bounded set of entities, and inspecting the graph before any reward, message, or agent action is enabled.',
    governance:
      'Web3 spans jurisdictions with sharply different treatments of tokens, rewards, and self-custody; what is a reward in one place can be a regulated instrument in another. Aether keeps consent, authorization, and lineage explicit and stays neutral on legal character, and the operating team obtains its own guidance and remains accountable.',
    evidence:
      'Evidence today is Aether’s public documentation and the design on these pages. No Web3 protocol case study or token outcome is published; the scenario above is an illustrative product scenario.',
  },
  {
    slug: 'ai-native-businesses',
    title: 'AI-native businesses on one governed graph',
    shortName: 'AI-native businesses',
    description:
      'How Aether gives agents and AI-native businesses governed context, explicit authorization, and audit trails across the graph.',
    audience:
      'For teams building agentic or AI-native products that act automatically on customer and entity context and need that action to stay governed and auditable.',
    situation:
      'AI-native businesses run agents and automated systems that act at machine speed on whatever context they are given — often a slice of a relationship held in one system.',
    friction:
      'An agent is only as sound as the context it acts on and the authorization it carries. When context is fragmented, an agent can act confidently on a partial picture, and the audit trail for what it did and under whose authority is thin.',
    transformation:
      'Aether gives agents the governed graph as context and agent access intelligence as a boundary. An agent can read resolved, consent-bearing relationships and act only under explicit authorization, with the requested → authorized → executed → verified → measured states recorded as the action moves.',
    scenarioLabel: SOLUTION_LABEL,
    scenario:
      'In an illustrative product scenario, a team building customer-facing agents connects their agent events to an Aether workspace. Each agent action carries an authorization and a consent context, and the team can replay what the agent read, what it did, and what verification exists — without trusting a log the agent wrote about itself.',
    capabilities: [
      'Agent access intelligence',
      'Identity and entity resolution',
      'Intelligence graph',
      'Communications intelligence',
      'Outcome attribution',
      'Governance and consent',
    ],
    implementation:
      'Teams adopt the boundary before the automation: agents are pointed at governed graph context and operated under the requested-to-verified state model while read-only and low-risk actions are validated first.',
    governance:
      'Automated decisions that produce legal or similarly significant effects carry their own accountability duties, including limits on purely automated decision-making. Aether makes authorization and oversight legible rather than removing the need for them, and the operating team remains responsible for the decisions its agents take.',
    evidence:
      'Evidence today is Aether’s public documentation and the design on these pages, including the limits the agent access intelligence family actually honors. No AI-native deployment is claimed; the scenario above is an illustrative product scenario.',
  },
  {
    slug: 'enterprise',
    title: 'One governed graph across the enterprise',
    shortName: 'Enterprise',
    description:
      'How Aether applies identity resolution, integration, and governance discipline across the systems, units, and geographies of a large organization.',
    audience:
      'For platform, data, security, and architecture teams in large organizations that need a governed relationship graph across business units, systems, and geographies — under procurement-grade constraints.',
    situation:
      'A large organization operates many systems across business units, geographies, and brands, each with its own record of the same customers, accounts, and partners.',
    friction:
      'Entity data fragments across the enterprise, so a single account or organization appears differently to each unit. Security, residency, and procurement constraints make a shared view hard to stand up, and a roll-up too often means copying data into yet another silo.',
    transformation:
      'Aether provides one governed graph that units read from and write to under tenant isolation, credential handling, consent, retention, and auditability — with identity resolution that reflects organizational hierarchy rather than flattening it.',
    scenarioLabel: SOLUTION_LABEL,
    scenario:
      'In an illustrative product scenario, an enterprise platform team connects a customer system, a commerce system, and a support system to a shared Aether workspace. Aether resolves accounts and organizations across the three, each unit reads the same governed relationship, and the audit log shows which tenant and credential accessed which record.',
    capabilities: [
      'Identity and entity resolution',
      'Intelligence graph',
      'Integrations and data quality',
      'Governance and consent',
      'Outcome attribution',
      'Communications intelligence',
      'Agent access intelligence',
    ],
    implementation:
      'Enterprise adoption is scoped before it is scaled: a bounded pilot across two or three systems, with tenant, credential, retention, and deployment questions answered against the security documentation before production traffic.',
    governance:
      'Procurement and security reviews ask about residency, tenant isolation, credential handling, and deletion. Aether documents those properties as design facts, and an enterprise team still runs its own review against its contracts, standards, and the jurisdictions it operates in.',
    evidence:
      'Evidence today is Aether’s public documentation — including the security and deployment material — and the design on these pages. There are no enterprise logos, references, or measured outcomes; the scenario above is an illustrative product scenario.',
  },
  {
    slug: 'public-sector',
    title: 'Public service on one governed graph',
    shortName: 'Public sector',
    description:
      'How Aether helps public-sector teams see constituents across programs on one consent- and audit-governed graph — only where the rules permit.',
    audience:
      'For public-sector teams — agencies and program operators — who serve constituents across programs and need a governed, auditable view without overstepping statutory bounds.',
    situation:
      'A public agency serves a constituent across programs, each governed by its own statute, system, and rules about who may see what.',
    friction:
      'Sensitive personal data is siloed by program precisely because the rules demand care. That makes a cross-program view hard to build lawfully, and any tool that promises to merge everything risks violating the very boundaries that protect the constituent.',
    transformation:
      'Aether approaches the problem boundary-first: a governed graph where consent, retention, authorization, and audit are properties of the record itself, and where a cross-program view exists only to the extent the rules permit it.',
    scenarioLabel: SOLUTION_LABEL,
    scenario:
      'In an illustrative product scenario, a public-sector program team connects two programs that serve the same constituent to an Aether workspace under a strict authorization model. Aether resolves the constituent where the rules allow, keeps the programs’ records separately governed, and produces an audit trail showing exactly which authorized role saw which record.',
    capabilities: [
      'Identity and entity resolution',
      'Intelligence graph',
      'Governance and consent',
      'Outcome attribution',
      'Communications intelligence',
    ],
    implementation:
      'Adoption proceeds only where the legal review says it may. Teams start read-only and within one program, extend resolution to a second program only with authorization in place, and treat audit as a deliverable rather than an afterthought.',
    governance:
      'Public-sector data sits under exacting regimes — records laws, program-specific statutes, and public procurement rules that vary by level of government and jurisdiction. Aether is a general platform, not a certified public-sector system; it makes consent, retention, and audit explicit so the agency’s own legal determination governs what is shared.',
    evidence:
      'Evidence today is Aether’s public documentation and the governance and security design on these pages. No agency deployment or endorsement is claimed; the scenario above is an illustrative product scenario.',
  },
];

export function findSolution(slug: string): SolutionCopy | undefined {
  return SOLUTIONS.find((solution) => solution.slug === slug);
}
