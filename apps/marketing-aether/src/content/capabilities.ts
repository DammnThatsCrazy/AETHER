/**
 * Aether capability-family deep copy.
 *
 * The /platform overview names eleven capability families and promises that each
 * one documents itself in one consistent form: the problem it addresses, the
 * inputs it consumes, what Aether understands, the output it produces, the
 * governance and consent that apply, and the limits the runtime honors.
 *
 * This module is that promise kept. Copy is truthful by construction, in the
 * same discipline as src/content/sections.ts: a capability is described at the
 * maturity the runtime can demonstrate, nothing is advertised as fuller than it
 * is, illustrative behavior is stated as the platform's intended design rather
 * than a shipped customer result, and no connector, provider, metric, or case
 * study is asserted beyond what the platform's own public material
 * substantiates.
 */

export interface CapabilitySection {
  readonly heading: string;
  readonly body: string;
}

export interface CapabilityCopy {
  /** Kebab-case slug, e.g. 'identity-resolution'; becomes /platform/<slug>. */
  readonly slug: string;
  /** Deep-page H1 and SEO <title> base. */
  readonly title: string;
  /** Short index-card label, e.g. 'Identity resolution'. */
  readonly shortName: string;
  /** 1-2 sentence SEO description AND card summary. */
  readonly description: string;
  /** Deep-page intro paragraph. */
  readonly lead: string;
  /** ONE honest sentence stating the runtime's current state for this family:
   * what exists, what is configured vs live, phrased per the platform's truth
   * discipline. */
  readonly status: string;
  /** Exactly the six canonical headings, in order. */
  readonly sections: readonly CapabilitySection[];
}

/** The six canonical section headings every capability deep page carries, in
 * the exact consistent form the /platform copy promises. */
export const CAPABILITY_SECTION_HEADINGS: readonly string[] = [
  'The problem it addresses',
  'The inputs it consumes',
  'What Aether understands',
  'The output it produces',
  'Governance and consent',
  'Limits the runtime honors',
];

export const CAPABILITIES: readonly CapabilityCopy[] = [
  {
    slug: 'identity-resolution',
    title: 'Identity and entity resolution',
    shortName: 'Identity resolution',
    description:
      'Aether identity resolution — how disconnected identifiers resolve into people, accounts, devices, wallets, and organizations, with lineage, consent, and governed connectors.',
    lead: 'Identity resolution is the first turn of the loop. Aether connects the identifiers a relationship leaves across systems — email, phone, device, wallet address, account — and resolves them into one entity model: people, accounts, devices, wallets, and organizations. Every resolution carries lineage, so the basis for an answer can be inspected rather than assumed.',
    status:
      'Identity resolution is documented as a designed platform capability; it is described at the maturity the runtime can demonstrate, and no live resolution run or live connector is asserted.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'A relationship is not a row in one system. The same person leaves an email in one system, a wallet address in another, and a device identifier in a third, and each system treats those fragments as separate customers. Action taken on a single slice of that identity is action taken on partial evidence.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Identifiers arriving through governed connectors and the event model — email addresses, phone numbers, device identifiers, wallet addresses, account numbers, and profile identifiers — each carrying its own consent, retention, and source lineage.',
      },
      {
        heading: 'What Aether understands',
        body: 'Which identifiers co-refer to a single entity — person, account, device, wallet, or organization — and the confidence the available signals support. Aether treats a resolution as a claim with a basis rather than a certainty, so thin data yields an honest, lower-confidence answer instead of a confident wrong one.',
      },
      {
        heading: 'The output it produces',
        body: 'A resolved entity model in the intelligence graph. Journey, campaign, communications, financial, and agent families read the same resolved identity, so a person’s context accumulates in one place instead of fragmenting across systems. Every merge or split is recorded with lineage.',
      },
      {
        heading: 'Governance and consent',
        body: 'Consent attaches to the activity and identifiers an integration brings in, retention applies to the identifiers themselves, and resolution never crosses a tenant boundary. Because each resolution records lineage, an operator can inspect why two records were joined and reverse the join if governance requires it.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'Resolution quality is bounded by the signals the governed connectors actually deliver. A cold or sparse profile is reported as uncertain rather than resolved by guesswork, ambiguous identifiers are not silently force-merged, and a connector that is not configured and verified is never treated as a live source of identity.',
      },
    ],
  },
  {
    slug: 'intelligence-graph',
    title: 'The intelligence graph',
    shortName: 'Intelligence graph',
    description:
      'The governed graph of entities, relationships, and activity that every Aether capability reads from and writes to — the platform spine.',
    lead: 'The intelligence graph is the spine of the platform. Entities, relationships, and activity live in one governed structure, and relationships carry consent, retention, and lineage with them, so an analysis never has to reassemble a person’s history from silos after the fact.',
    status:
      'The intelligence graph is the documented spine every capability family reads from and writes to; its entity, relationship, and action-state model is stated as design, and its completeness is bounded by the governed connectors that feed it.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'When context lives in silos, no single system can answer what a relationship is worth or what has happened within it. That answer exists only when activity is stored as relationships rather than as rows scattered across systems that never meet.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Resolved entities, relationships, events, ledger effects, communications, agent actions, consent and retention state, and the state of governed actions — requested, authorized, executed, verified, measured — written through governed connectors.',
      },
      {
        heading: 'What Aether understands',
        body: 'Entities and the relationships among them, the activity that has accumulated in a relationship, and the state each governed action is in. Because relationships carry consent, retention, and lineage, the graph understands not only what happened but whether it may still be held and where it came from.',
      },
      {
        heading: 'The output it produces',
        body: 'A queryable, governed relationship graph that every other family reads from and writes to. Journey, campaign, communications, financial, agent, reward, and attribution families all resolve against the same entity model, so context accumulates in one place.',
      },
      {
        heading: 'Governance and consent',
        body: 'Consent, retention, tenant isolation, and auditability are properties of the graph rather than wrappers applied afterward. Activity that has reached its retention limit is not silently kept, actions carry the requested-to-measured state machine, and where verification is not available the runtime records executed, verification pending.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'The graph is only as complete as the connectors and events that feed it. It cannot reconstruct activity that never reached it, and it never fabricates a relationship the evidence does not support. Where a connector or data source is not configured or verified, the graph is documented as partial rather than presented as whole.',
      },
    ],
  },
  {
    slug: 'journey-intelligence',
    title: 'Journey intelligence',
    shortName: 'Journey intelligence',
    description:
      'How Aether turns graph activity into journeys — the path a relationship takes across touchpoints, systems, and time.',
    lead: 'A journey is the shape of a relationship over time: the sequence of touchpoints, systems, and states a person, account, or organization passes through. Journey intelligence reads the graph and renders that path in one place, from first signal to latest state.',
    status:
      'Journey intelligence is documented as a capability family of the platform; journey views are described from graph activity, and no live journey dataset or connector is asserted.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'A relationship’s path is scattered. Support sees a ticket, commerce sees an order, and the wallet sees a balance, and none of them sees the sequence. Without the sequence, a team cannot tell where a relationship is or what it has already been through.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Resolved entities and the events, interactions, communications, orders, ledger effects, and agent actions attached to them, each carrying consent, retention, and timestamps through governed connectors.',
      },
      {
        heading: 'What Aether understands',
        body: 'The sequence of a relationship across touchpoints and systems, its current state, and the steps that led there. Because journeys resolve against the graph, the same identity that holds a wallet address is the identity that opened a ticket or received a message.',
      },
      {
        heading: 'The output it produces',
        body: 'Journey views and journey-level context that other families read — a relationship’s history assembled in one place instead of reassembled from silos after the fact. Campaign movement, communications history, and financial context all hang off the same journey.',
      },
      {
        heading: 'Governance and consent',
        body: 'A journey is built only from activity the platform is permitted to hold. Consent and retention govern how far back a journey can see, activity past its retention limit drops out of the view, and journey state is tenant-isolated and auditable like the rest of the graph.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'A journey is only as complete as the events that reached the platform. Activity from a system that is not connected, or a connector that is not configured or verified, is absent from the journey — and the runtime does not pretend to reconstruct it.',
      },
    ],
  },
  {
    slug: 'campaign-intelligence',
    title: 'Campaign intelligence',
    shortName: 'Campaign intelligence',
    description:
      'How Aether tracks campaign movement and behavior — what a campaign did to a relationship and what the relationship did in response — as governed evidence.',
    lead: 'Campaign intelligence tracks the movement of a campaign across the audience it reaches and the behavior that follows. It reads the graph, so a campaign is understood not as impressions in isolation but as activity against resolved relationships.',
    status:
      'Campaign intelligence is documented as a capability family; campaign movement and response are described from graph events, and no live campaign result or connector is asserted.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'Campaign results live in the sending system while the response lives in commerce, support, and the wallet. Fragmented that way, a team sees delivery numbers but not whether a campaign moved a relationship.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Campaign events, audience lists, delivery and engagement signals, and the downstream behavior that follows — orders, support contacts, wallet activity, agent interactions — through governed connectors.',
      },
      {
        heading: 'What Aether understands',
        body: 'Which resolved relationships a campaign reached, what each one did afterward, and how that movement compares within the audience. Because responses resolve against the same graph, campaign behavior is understood at the relationship level rather than the aggregate.',
      },
      {
        heading: 'The output it produces',
        body: 'Campaign movement and response evidence attached to the intelligence graph, ready for outcome attribution to connect governed decisions back to outcomes.',
      },
      {
        heading: 'Governance and consent',
        body: 'Campaign activity obeys the consent that governs each recipient and the retention attached to each event. A campaign that reached a person without standing consent, or ran through a connector marked planned rather than available, is never presented as a live campaign result.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'Campaign intelligence measures what the events it received can support. Delivery and engagement data are only as accurate as what a connector reports, response is visible only where downstream activity reaches the graph, and where the runtime cannot verify an action it reports executed it says verification pending.',
      },
    ],
  },
  {
    slug: 'communications-intelligence',
    title: 'Communications intelligence',
    shortName: 'Communications intelligence',
    description:
      'Every communication as part of the relationship record — what was sent, received, and replied to, under consent, across channels.',
    lead: 'Communications are part of the relationship record. Communications intelligence keeps each message — its channel, direction, and reply — attached to the resolved identity it concerns, so history accumulates in the graph rather than in per-channel silos.',
    status:
      'Communications intelligence is documented as a capability family; communication history is described from governed channels, and no channel or provider is asserted live without a verified connector.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'A person’s communications are split across channels — email, chat, support threads, in-product messages — and each channel remembers only its own side. Reconstructing everything a relationship has been told becomes a manual assembly across systems that do not share a record.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Messages, send and delivery signals, replies, channel metadata, and the consent and retention governing each channel, arriving through governed connectors that state their real availability.',
      },
      {
        heading: 'What Aether understands',
        body: 'The history of communication with a resolved relationship across channels, what was sent versus what was received, and the replies that followed. Communications hang off the same identity that holds orders and wallet addresses, so they are understood as relationship context rather than channel traffic.',
      },
      {
        heading: 'The output it produces',
        body: 'A per-relationship communication history on the graph, complete only to the extent the connected channels provide it, which journeys and campaign movement read as context.',
      },
      {
        heading: 'Governance and consent',
        body: 'Every message is held under the consent and retention that govern its channel. A channel without standing consent, or activity past its retention limit, is not retained, and channels that are planned rather than available are not presented as connected.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'A channel that is not connected, or a connector that is not configured and verified, contributes nothing to the record — the runtime documents communication history as partial rather than implying an omniscient archive, and unverifiable sends are labeled verification pending.',
      },
    ],
  },
  {
    slug: 'financial-observability',
    title: 'Financial observability',
    shortName: 'Financial observability',
    description:
      'Ledger effects and balances as part of the relationship record — where value moved, under what authorization, and whether the runtime can verify it.',
    lead: 'Money movement is governed action with real consequences. Financial observability keeps ledger effects — debits, credits, transfers, balances — attached to the resolved relationship that holds them, so financial context sits beside the activity that caused it.',
    status:
      'Financial observability is documented as a capability family; ledger effects are described from governed connectors, and the runtime does not assert a live balance source or payment rail.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'A wallet balance lives in one system, an invoice in another, and a refund in a third. When money movement is fragmented from the activity that caused it, what a relationship actually cost or earned cannot be answered from one place.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Ledger entries, balance and transaction events, invoices, payouts, and settlement signals from governed connectors, each carrying consent, retention, and the authorization that allowed the movement.',
      },
      {
        heading: 'What Aether understands',
        body: 'Where value moved in a relationship, the state of each financial action, and whether the movement is verified or pending verification. Financial activity resolves against the same identity that holds the wallet or account, so context is not siloed from the behavior that produced it.',
      },
      {
        heading: 'The output it produces',
        body: 'Financial context on the graph — ledger effects tied to resolved relationships and to the campaign, journey, or agent action that caused them, ready for outcome attribution.',
      },
      {
        heading: 'Governance and consent',
        body: 'Every financial action runs through the governed state machine: requested, authorized, executed, verified, measured. Where the runtime cannot verify that a transfer or settlement occurred, it records executed, verification pending rather than implying certainty, and credentials follow the platform’s credential-handling discipline under strict tenant isolation.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'The runtime observes what its governed connectors report; it is not a payment processor and does not claim to execute or guarantee a money movement itself. Balances are only as current as the connected source, and a connector that is not configured or verified is not presented as a live financial source.',
      },
    ],
  },
  {
    slug: 'agent-access-intelligence',
    title: 'Agent access intelligence',
    shortName: 'Agent access intelligence',
    description:
      'Knowing when an agent is acting, under what authorization, and with what guardrails — agent activity as governed evidence on the graph.',
    lead: 'Agents act at machine speed, and speed without a boundary is risk. Agent access intelligence makes agent activity legible: when an agent acts, under what authorization, within what guardrails, and with what outcome — all recorded on the graph.',
    status:
      'Agent access intelligence is documented as a capability family; agent authorization, guardrails, and action recording are described as design, and no agent integration is asserted live.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'Automation can now act at machine speed — on whatever slice of context each system happens to hold. Without recorded authorization and guardrails, an agent’s action is hard to attribute, hard to bound, and hard to account for in governance terms.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Agent identity and action requests, the authorization scope granted to each agent, guardrail definitions, and the actions an agent actually takes, arriving through governed connectors.',
      },
      {
        heading: 'What Aether understands',
        body: 'Which agent acted, under which authorization, within which guardrails, and against which resolved relationship. Agent activity is recorded as evidence with the same requested, authorized, executed, verified, and measured states as any other governed action.',
      },
      {
        heading: 'The output it produces',
        body: 'A legible record of agent activity attached to the graph — what acted, why it was permitted to, and what it did — so operators can inspect the evidence behind an agent’s decision rather than trust it at face value.',
      },
      {
        heading: 'Governance and consent',
        body: 'Agents act only within the authorization they were granted, and guardrails are enforced as documented properties rather than aspirations. Consent, retention, tenant isolation, and auditability apply to agent activity exactly as they apply to human activity, and unverifiable agent actions are recorded as executed, verification pending.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'The runtime can only govern an agent whose actions reach it through a governed connector; it does not claim to intercept agents operating outside that surface. Authorization is only as precise as the scope an operator configured, and where the runtime cannot verify what an agent did it says so rather than implying certainty.',
      },
    ],
  },
  {
    slug: 'rewards-and-activation',
    title: 'Rewards and activation',
    shortName: 'Rewards and activation',
    description:
      'Governed rewards — earning, eligibility, issuance, and redemption — attached to resolved relationships and backed by verifiable activity.',
    lead: 'Rewards turn understanding into action: a relationship is recognized, an activity qualifies, and a reward is earned, issued, and redeemed. Rewards and activation keeps each of those steps governed and tied to the resolved relationship behind it.',
    status:
      'Rewards and activation is documented as a capability family; earning, issuance, and redemption are described as governed design, and no rewards program is asserted live.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'A rewards program that cannot see the full relationship rewards fragments. It cannot tell whether an activity qualified, whether a reward was already issued, or whether a redemption is legitimate, because the evidence is scattered across systems.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Qualifying activity and events, reward program rules and eligibility criteria, issuance and redemption events, and the ledger effects rewards create, through governed connectors.',
      },
      {
        heading: 'What Aether understands',
        body: 'What a resolved relationship did, whether that activity qualifies under the program’s rules, and the state of each reward — earned, issued, redeemed, or expired. Because rewards resolve against the graph, a reward is issued to a relationship the runtime can recognize rather than to a guessed identity.',
      },
      {
        heading: 'The output it produces',
        body: 'A governed record of earning, issuance, and redemption attached to the graph, with the activity that qualified each reward held as inspectable evidence.',
      },
      {
        heading: 'Governance and consent',
        body: 'Reward issuance is governed action: it is requested, authorized, executed, and — where the runtime can verify it — verified. Rules and eligibility are enforced as documented, and where verification of an issuance is not available the runtime records executed, verification pending. Consent and retention govern the activity a reward is based on.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'A reward is only as trustworthy as the activity that qualified it and the program rules an operator configured. The runtime does not fabricate qualifying activity and does not assert a live rewards program; where issuance cannot be verified it says so instead of implying a completed outcome.',
      },
    ],
  },
  {
    slug: 'outcome-attribution',
    title: 'Outcome attribution',
    shortName: 'Outcome attribution',
    description:
      'Connecting governed decisions back to the outcomes that followed, as evidence on the graph rather than fabricated correlation.',
    lead: 'Outcome attribution closes the loop. Decisions become actions, actions leave evidence, and evidence connects back to the outcomes that followed. Attribution is stated with its uncertainty, never as a fabricated causal story.',
    status:
      'Outcome attribution is documented as the designed closing of the platform loop; it is described from governed graph evidence, and no measured attribution result is asserted.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'When activity is fragmented, the evidence for what moved an outcome is fragmented too. Teams are left to guess which action changed a result, because the decision, the action, and the outcome never met in one place.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Governed actions and decisions across families — a campaign, a communication, a reward, an agent action — the outcome events that follow, and the resolved relationships both sides attach to.',
      },
      {
        heading: 'What Aether understands',
        body: 'The sequence from decision to action to outcome within a relationship, and what the evidence does and does not support. Attribution is expressed with its limits: a correlation the evidence cannot separate from other causes is labeled as such rather than dressed as causation.',
      },
      {
        heading: 'The output it produces',
        body: 'Attribution evidence on the graph — decisions linked to the outcomes that followed and the strength of that link — feeding back so the next decision starts from what the last one actually produced.',
      },
      {
        heading: 'Governance and consent',
        body: 'Attribution runs on governed evidence only. It never uses activity the platform was not permitted to hold, it does not invent outcomes that were not observed, and an action whose verification is pending is not presented as a measured cause.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'The runtime attributes only what it can observe. A cause that happened off-platform, or an outcome that never reached the graph, is outside the attribution, and the runtime reports what the evidence supports rather than manufacturing a clean causal story where the data is noisy.',
      },
    ],
  },
  {
    slug: 'governance-and-consent',
    title: 'Governance and consent',
    shortName: 'Governance and consent',
    description:
      'The boundaries of the platform — consent, retention, authorization, tenant isolation, and auditability as properties of the graph, not wrappers.',
    lead: 'Governance is how the loop stays safe, not a wrapper applied afterward. Consent, retention, authorization, tenant isolation, and auditability live in the graph, and actions move through requested, authorized, executed, verified, and measured states.',
    status:
      'Governance and consent is the documented boundary every family honors; consent, retention, authorization, tenant isolation, and auditability are stated as graph properties, and the action state machine is the runtime’s stated discipline.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'Trust and compliance break when governance is bolted on after the fact — when a system has already stored what it should not hold or acted without authorization. The remedy is to make the boundary part of the data model from the start.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Consent records, retention policies, authorization scopes, tenant definitions, and the action-state transitions every governed action reports as it moves through the pipeline.',
      },
      {
        heading: 'What Aether understands',
        body: 'What the platform is permitted to hold and for how long, who or what is authorized to act and within what scope, and the state of every governed action — requested, authorized, executed, verified, measured.',
      },
      {
        heading: 'The output it produces',
        body: 'A governed operating surface: activity that carries its consent and retention, actions that carry their authorization and state, and an auditable record operators can inspect — the boundary as a feature rather than paperwork.',
      },
      {
        heading: 'Governance and consent',
        body: 'This family is the governance the other ten honor. Where the runtime cannot verify that an action occurred, it records executed, verification pending rather than implying certainty, and it never visually implies proof it does not have. Tenant isolation, credential handling, retention, and auditability are documented properties of the design.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'Governance is only as strong as what operators configure and what the runtime can actually verify. The platform does not claim to enforce a policy it has not been given, nor to verify an action that happened beyond its reach — and it documents that gap rather than hiding it.',
      },
    ],
  },
  {
    slug: 'integrations-and-data-quality',
    title: 'Integrations and data quality',
    shortName: 'Integrations and data quality',
    description:
      'Governed connectors and the validation that keeps the graph honest — every integration stated at its real availability and data quality.',
    lead: 'Every family depends on data arriving through governed connectors and passing validation. Integrations and data quality keeps that surface honest: each connector states what it supports, how it authenticates, how data synchronizes, its limits — and its actual availability state.',
    status:
      'Integrations are recorded against real availability states from the runtime registry — available, beta, credential required, configuration required, planned, unsupported — and no connector or provider is asserted live.',
    sections: [
      {
        heading: 'The problem it addresses',
        body: 'The graph is only as good as what reaches it. A connector that silently drops fields, a schema that accepts malformed events, or an integration presented as live before it is configured quietly corrupts every downstream family that reads the data.',
      },
      {
        heading: 'The inputs it consumes',
        body: 'Events and records from external systems, connector definitions with their capability, data direction, authentication type, and availability state, and the validation rules applied to incoming events.',
      },
      {
        heading: 'What Aether understands',
        body: 'What each integration actually supports and is actually permitted to do, whether incoming events are valid against the event model, and whether a connector is available, beta, credential required, configuration required, planned, or unsupported. A partially configured system is never understood as fully active.',
      },
      {
        heading: 'The output it produces',
        body: 'A governed ingestion surface feeding the graph — validated events, connectors stated at their true availability, and a directory that tells the truth about each one so a team can reason about a connector before choosing it.',
      },
      {
        heading: 'Governance and consent',
        body: 'Consent and governance are part of the developer contract rather than an add-on bolted on after an integration works. Credential handling follows the platform’s credential discipline, synchronization respects a connector’s stated direction and limits, and retention attaches to everything an integration brings in.',
      },
      {
        heading: 'Limits the runtime honors',
        body: 'The runtime records a connector’s state as the registry knows it. An availability state of planned is not a promise that a provider is live, a capability the runtime does not yet support is not presented as ready, and validation rejects what it cannot confirm rather than passing it through on faith.',
      },
    ],
  },
];

/** Looks up one capability family by its kebab-case slug. */
export function findCapability(slug: string): CapabilityCopy | undefined {
  return CAPABILITIES.find((capability) => capability.slug === slug);
}
