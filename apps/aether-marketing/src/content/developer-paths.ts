/**
 * Aether developer-path selector content.
 *
 * The /developers marketing page uses these paths to answer, in a guarded and
 * truthful way, the integration questions a practitioner asks first: which SDK
 * to use, what the event model is, how identity resolution works, how consent
 * works and how integrations behave, and how to validate a first event.
 *
 * Content is honest by construction. Nothing here claims an SDK artifact,
 * install command, code API, or endpoint by name; a path describes integration
 * in terms of real concepts (events, identity resolution, consent, connectors,
 * validation) and always defers the canonical, currently authoritative
 * reference to the Aether documentation site, which these paths orient toward
 * rather than replace. Every sentence is written in the same disciplined voice
 * as the /developers SECTIONS copy it sits beside.
 */

export interface DeveloperPath {
  /** kebab id used as the selector value, e.g. 'send-events'. */
  readonly id: string;
  /** selector tab/button label. */
  readonly label: string;
  /** short context, e.g. 'First step'. */
  readonly eyebrow: string;
  /** honest 1-2 sentence summary of this path. */
  readonly description: string;
  /** 3-5 steps, each truthful about what exists (configuration, credentials,
   * validation) and written in the guarded Aether voice. */
  readonly steps: readonly { readonly heading: string; readonly text: string }[];
  /** ONE honest sentence: what is real today for this path (where it needs a
   * workspace/credential, what the docs cover). Never claims a live feature
   * that does not exist. */
  readonly state: string;
}

/**
 * The developer paths in the order a practitioner would encounter them. The
 * tuple type keeps the module honest: the selector default and page fallbacks
 * depend on this list being non-empty and in a fixed order, so the length is
 * part of the type rather than an accident.
 */
export const DEVELOPER_PATHS: readonly [
  DeveloperPath,
  DeveloperPath,
  DeveloperPath,
  DeveloperPath,
] = [
  {
    id: 'send-events',
    label: 'Send events',
    eyebrow: 'First step',
    description:
      'How the activity you report becomes an Aether event — what an event carries, how it is validated, and how you confirm the first one behaves before production traffic.',
    steps: [
      {
        heading: 'Create the workspace the docs describe',
        text: 'Event capture starts in an Aether workspace. The documentation explains how a workspace is created and which credential the path needs, and when a configuration or a credential is required the material says so before you begin rather than leaving it to be discovered.',
      },
      {
        heading: 'Shape an event against the model',
        text: 'An event carries the identity of the actor and the activity you are reporting, and it is validated against the documented schema before it is stored. What an event may carry — and what it may not — is defined in the canonical reference, not improvised at the edge.',
      },
      {
        heading: 'Send the first event',
        text: 'The documentation answers which SDK fits your platform and shows the configuration it needs. Follow that reference from the first event; the intended path into Aether runs from a first event through identity resolution.',
      },
      {
        heading: 'Validate what happened',
        text: 'Validation tells you whether an event was accepted, what it carried, and where it landed in the graph. Error behavior is part of the documented contract: a rejected event is reported as rejected rather than presented as delivered.',
      },
      {
        heading: 'Confirm before production traffic',
        text: 'Check that the integration behaves as documented before scaling to real traffic. The validation material shows what a healthy first event looks like and where to confirm it in your workspace.',
      },
    ],
    state:
      'Sending an event today requires an Aether workspace — with the credential the documented setup describes — and the event schema, SDK choice, and validation flow are documented on the documentation site.',
  },
  {
    id: 'resolve-identity',
    label: 'Resolve identity',
    eyebrow: 'Identity resolution',
    description:
      'How the identifiers an integration already carries resolve into people, accounts, devices, wallets, and organizations — and why resolution carries lineage you can inspect rather than accepting a match you cannot question.',
    steps: [
      {
        heading: 'Know which identifiers you send',
        text: 'Resolution starts with the identifiers your systems actually hold — an account, an email, a device, a wallet address. What you send determines what Aether can connect, so the first step is knowing what is already on the wire.',
      },
      {
        heading: 'Read the entity model',
        text: 'Identifiers resolve into people, accounts, devices, wallets, and organizations within one governed entity model. The documentation defines each entity type and how identifiers map onto it, with lineage recorded rather than a black-box match.',
      },
      {
        heading: 'Inspect why a match happened',
        text: 'A resolution is only useful if it can be questioned. Lineage records why two identifiers were connected, so an operator can inspect the evidence behind a match instead of accepting it on faith.',
      },
      {
        heading: 'Keep consent attached',
        text: 'Consent, retention, and authorization attach to the relationship and travel with the resolution. Governance is part of the developer contract rather than a layer bolted on after the integration works.',
      },
    ],
    state:
      'Identity resolution is documented as the step after a first event, and what resolves today depends on the identifiers an integration sends and the workspace it runs in.',
  },
  {
    id: 'govern-consent',
    label: 'Govern consent',
    eyebrow: 'Consent & governance',
    description:
      'How consent, retention, and authorization attach to the activity an integration brings in — what the integration may capture, store, and act on, stated before you begin.',
    steps: [
      {
        heading: 'Treat consent as part of the contract',
        text: 'Consent is part of what an event carries and how it is validated, not a side channel handled outside the pipeline. The documentation defines the consent fields an integration must honor.',
      },
      {
        heading: 'Let retention follow the relationship',
        text: 'Retention is documented per relationship rather than applied as one blunt global policy. What Aether keeps, and for how long, is a property of the design and is stated rather than implied.',
      },
      {
        heading: 'Keep action inside the boundary',
        text: 'Actions move through requested, authorized, executed, verified, and measured states. Where the runtime cannot verify an action it reports "executed, verification pending" — it does not claim certainty it cannot prove.',
      },
      {
        heading: 'State the configuration before you begin',
        text: 'When a flow requires a configuration or a credential, the material tells you up front. The documentation site is the canonical reference for the consent schema and its validation rules.',
      },
    ],
    state:
      'Consent, retention, and authorization are documented properties of the developer contract today, and the exact fields, defaults, and validation rules an integration must honor are specified in the documentation reference.',
  },
  {
    id: 'connect-integrations',
    label: 'Connect integrations',
    eyebrow: 'Connector availability',
    description:
      'How connectors behave — the capability they support, how they authenticate, how data synchronizes, and what a stated availability state actually means before you wire one in.',
    steps: [
      {
        heading: 'Read the availability state first',
        text: 'Every connector is described at its real availability state — available, beta, credential required, configuration required, planned, or unsupported. A partially configured system is never marked fully active.',
      },
      {
        heading: 'Match capability to your use',
        text: 'An integration entry states which capability it supports, its inputs and outputs, how it authenticates, and its data direction, so you can reason about fit the way you would about a prospective vendor.',
      },
      {
        heading: 'Put the limits beside the capability',
        text: 'Documented limits and error behavior sit next to documented capability. A connector that requires a credential or a configuration is labeled that way, and constraints on direction or authentication are part of the entry.',
      },
      {
        heading: 'Wire against the canonical reference',
        text: 'The documentation site is the canonical reference for a connector’s schemas and configuration. Where the runtime records a connector as planned rather than available, it is described as planned — detail is published as it exists, never invented.',
      },
    ],
    state:
      'Connectors carry stated availability states today, so a specific connector’s real state is whatever its registry entry says, and connector detail is added as it is published rather than promised in advance.',
  },
];

export function findDeveloperPath(id: string): DeveloperPath | undefined {
  return DEVELOPER_PATHS.find((path) => path.id === id);
}

/** First path id; the page opens with this path selected. */
export const DEFAULT_PATH_ID: string = DEVELOPER_PATHS[0].id;
