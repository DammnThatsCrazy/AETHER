/**
 * Managed connectors (docs/CONNECTORS.md, "Available connectors"), as the
 * marketing pages describe them. The generic signed webhook is listed apart:
 * it connects any other system rather than one provider.
 */
export type ConnectorDirection = 'in' | 'out' | 'both';

export interface Connector {
  name: string;
  category: string;
  direction: ConnectorDirection;
  carries: string;
}

export const MANAGED_CONNECTORS: Connector[] = [
  { name: 'HubSpot', category: 'CRM', direction: 'both', carries: 'contacts, companies, deals, lifecycle' },
  { name: 'Salesforce', category: 'CRM', direction: 'in', carries: 'leads, accounts, opportunities' },
  { name: 'Shopify', category: 'Commerce', direction: 'in', carries: 'products, carts, orders, customers' },
  { name: 'Stripe', category: 'Billing', direction: 'in', carries: 'customers, invoices, payments, refunds, disputes' },
  { name: 'Klaviyo', category: 'Marketing', direction: 'in', carries: 'campaigns, flows, sends, opens' },
  { name: 'Segment', category: 'Analytics', direction: 'in', carries: 'track, identify, page, group' },
  { name: 'PostHog', category: 'Analytics', direction: 'in', carries: 'events, persons, feature flags' },
  { name: 'GA4', category: 'Analytics', direction: 'in', carries: 'sessions, conversions, sources' },
  { name: 'Zendesk', category: 'Support', direction: 'in', carries: 'tickets, satisfaction, agents' },
  { name: 'Intercom', category: 'Support', direction: 'in', carries: 'conversations, users, tags' },
  { name: 'Jira', category: 'Project', direction: 'out', carries: 'create issues from approvals' },
  { name: 'Linear', category: 'Project', direction: 'out', carries: 'create issues from approvals' },
  { name: 'Slack', category: 'Messaging', direction: 'out', carries: 'notify and route decisions' },
];
