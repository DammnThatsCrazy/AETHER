/**
 * Static connector dataset for the /integrations marketing directory.
 *
 * DERIVED SNAPSHOT — NOT A LIVE QUERY.
 *
 * Every value below is traced to Aether's real backend connector registry and
 * was cross-checked by running the backend's own derived-catalog projection
 * (build_connector_manifests). Sources:
 *
 * - shared/integration_contracts/catalog.py         (derived ProviderManifest catalog)
 * - services/integrations/connectors/registry.py    (CONNECTORS registry)
 * - services/integrations/connectors/adapters.py    (ALL_CONNECTORS — 21 classes)
 * - services/integrations/connectors/base.py        (ConnectorDescriptor / ImplementationStatus)
 * - services/integrations/connectors/{braze,customerio,iterable,klaviyo,mailchimp,
 *   postmark,sendgrid}.py                            (branded comms descriptors)
 * - shared/certification/readiness.py               (IMPLEMENTATION_STATUS_TO_READINESS,
 *                                                    to_readiness)
 *
 * Derived at backend rev `4aae2dc7` (aether-web-ecosystem), 2026-09-02. This
 * file is a point-in-time snapshot: when the backend registry changes, refresh
 * it against the catalog rather than hand-editing records. The /integrations
 * copy in src/content/sections.ts promises exactly this truthfulness — a
 * connector is described at the availability state the runtime records.
 *
 * Readiness mapping used: each registry connector's descriptor declares
 * ImplementationStatus.CREDENTIAL_GATED, which shared/certification/readiness.py
 * maps onto the CredentialReadiness token "credential_waiting". The catalog's
 * conservative availability rule places credential_waiting at level 3 (visible
 * in local/integration, never staging/production) — none of the 21 connectors is
 * replay/sandbox/partner validated today, so none is shown as live.
 */

export type ConnectorAuth = 'api_key' | 'webhook_only' | 'none';

/** Real readiness tokens (marketing subset of shared/certification/readiness.py
 * CredentialReadiness). The full backend vocabulary also carries
 * credential_supplied / connection_validated / suspended / revoked, but no
 * registry connector is in those states today, so they are not in this union. */
export type ConnectorReadiness =
  | 'scaffolded'
  | 'disabled'
  | 'degraded'
  | 'credential_waiting'
  | 'replay_validated'
  | 'sandbox_validated'
  | 'partner_live';

export interface ConnectorRecord {
  /** connector_type, e.g. 'stripe' — the registry's unique identity key. */
  readonly id: string;
  /** Display label from the descriptor (e.g. "Stripe (ingestion)", "Dune Analytics"). */
  readonly name: string;
  /** Real descriptor category (ConnectorCategory literal), e.g. 'product_analytics'. */
  readonly category: string;
  /** Descriptor description, kept verbatim. Some real descriptors (observe-only
   * comms providers) run to two sentences — the second ("Aether never sends
   * through this connector.") is part of the honest descriptor and is preserved. */
  readonly description: string;
  /** Derived from the descriptor via the catalog's _authentication_for rule:
   * webhook-and-not-pull → 'webhook_only'; requires_secret → 'api_key'; else 'none'. */
  readonly auth: ConnectorAuth;
  /** supports_pull */
  readonly pull: boolean;
  /** supports_webhook */
  readonly webhook: boolean;
  /** Readiness token mapped from implementation_status (see module docstring). */
  readonly status: ConnectorReadiness;
  /** Every registry connector is inbound tenant-BYOD ingestion (DataFlowDirection.INBOUND). */
  readonly dataDirection: 'inbound';
}

/**
 * The 21 registry connectors in registry insertion order (adapters.py
 * ALL_CONNECTORS → registry.py CONNECTORS), projected from the real descriptors.
 */
export const CONNECTORS: readonly ConnectorRecord[] = [
  {
    id: 'slack',
    name: 'Slack',
    category: 'messaging',
    description: 'Ingest Slack messages, reactions, and channel activity as graph signals.',
    auth: 'webhook_only',
    pull: false,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'webhook',
    name: 'Generic Signed Webhook',
    category: 'webhook',
    description: 'Ingest events from any system via an HMAC-signed webhook.',
    auth: 'webhook_only',
    pull: false,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'shopify',
    name: 'Shopify',
    category: 'commerce',
    description: 'Ingest Shopify orders, customers, and checkout events.',
    auth: 'api_key',
    pull: true,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'stripe',
    name: 'Stripe (ingestion)',
    category: 'billing',
    description: 'Ingest Stripe payment, invoice, and subscription events as graph signals.',
    auth: 'webhook_only',
    pull: false,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'hubspot',
    name: 'HubSpot',
    category: 'crm',
    description:
      'Ingest HubSpot contacts, companies, and deals, and observe HubSpot Marketing Hub email engagement. Aether never sends through this connector (ADR-C1).',
    auth: 'api_key',
    pull: true,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'salesforce',
    name: 'Salesforce',
    category: 'crm',
    description: 'Ingest Salesforce leads, accounts, and opportunities.',
    auth: 'api_key',
    pull: true,
    webhook: false,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'klaviyo',
    name: 'Klaviyo',
    category: 'marketing',
    description:
      'Observe Klaviyo email campaigns, flows, messages, and engagement events. Aether never sends through this connector.',
    auth: 'api_key',
    pull: true,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'segment',
    name: 'Segment',
    category: 'product_analytics',
    description: 'Ingest Segment track/identify/page events.',
    auth: 'webhook_only',
    pull: false,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'posthog',
    name: 'PostHog',
    category: 'product_analytics',
    description: 'Ingest PostHog product-usage events and persons.',
    auth: 'api_key',
    pull: true,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'ga4',
    name: 'Google Analytics 4',
    category: 'product_analytics',
    description: 'Ingest GA4 events via the Data API (pull).',
    auth: 'api_key',
    pull: true,
    webhook: false,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'jira',
    name: 'Jira',
    category: 'project',
    description: 'Ingest Jira issue and workflow events.',
    auth: 'api_key',
    pull: true,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'linear',
    name: 'Linear',
    category: 'project',
    description: 'Ingest Linear issues and comments.',
    auth: 'webhook_only',
    pull: false,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'zendesk',
    name: 'Zendesk',
    category: 'support',
    description: 'Ingest Zendesk ticket and support events.',
    auth: 'api_key',
    pull: true,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'intercom',
    name: 'Intercom',
    category: 'support',
    description: 'Ingest Intercom conversations and contacts.',
    auth: 'api_key',
    pull: true,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'dune',
    name: 'Dune Analytics',
    category: 'product_analytics',
    description:
      'Read-only on-chain analytics provider. Pulls query results into Bronze for governed promotion to Silver.',
    auth: 'api_key',
    pull: true,
    webhook: false,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'sendgrid',
    name: 'SendGrid',
    category: 'marketing',
    description:
      'Observe Twilio SendGrid email delivery and engagement events via the Event Webhook (ECDSA-verified). Aether never sends through this connector.',
    auth: 'webhook_only',
    pull: false,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'customerio',
    name: 'Customer.io',
    category: 'marketing',
    description:
      'Observe Customer.io email delivery and engagement events via reporting webhooks (HMAC-verified). Aether never sends through this connector.',
    auth: 'webhook_only',
    pull: false,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'mailchimp',
    name: 'Mailchimp',
    category: 'marketing',
    description:
      'Observe Mailchimp list lifecycle events via Marketing webhooks. Aether never sends through this connector.',
    auth: 'webhook_only',
    pull: false,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'postmark',
    name: 'Postmark',
    category: 'marketing',
    description:
      'Observe Postmark transactional email delivery and engagement events via webhooks. Aether never sends through this connector.',
    auth: 'webhook_only',
    pull: false,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'iterable',
    name: 'Iterable',
    category: 'marketing',
    description:
      'Observe Iterable email delivery and engagement events via signed webhooks and the REST event export API. Aether never sends through this connector.',
    auth: 'api_key',
    pull: true,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
  {
    id: 'braze',
    name: 'Braze',
    category: 'marketing',
    description:
      'Observe Braze email delivery and engagement via REST pull (hard bounces, unsubscribes) and pushed message events. Aether never sends through this connector.',
    auth: 'api_key',
    pull: true,
    webhook: true,
    status: 'credential_waiting',
    dataDirection: 'inbound',
  },
];

/** Sorted unique real categories present in the snapshot (descriptor literals). */
export const CONNECTOR_CATEGORIES: readonly string[] = [
  ...new Set(CONNECTORS.map((connector) => connector.category)),
].sort();

/** Short public label per real readiness token. credential_waiting — the state
 * every registry connector is in today — reads as "Credentials required". */
export const CONNECTOR_STATUS_LABELS: Readonly<Record<ConnectorReadiness, string>> = {
  scaffolded: 'Scaffolded',
  disabled: 'Disabled',
  degraded: 'Degraded',
  credential_waiting: 'Credentials required',
  replay_validated: 'Replay validated',
  sandbox_validated: 'Sandbox validated',
  partner_live: 'Partner live',
};

/** Look up one registry connector by its real connector_type. */
export function findConnector(id: string): ConnectorRecord | undefined {
  return CONNECTORS.find((connector) => connector.id === id);
}
