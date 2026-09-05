import { describe, expect, it } from 'vitest';
import type { ConnectorReadiness } from './connectors';
import {
  CONNECTORS,
  CONNECTOR_CATEGORIES,
  CONNECTOR_STATUS_LABELS,
  findConnector,
} from './connectors';

/**
 * The 21 real connector_type values encoded in this dataset, transcribed from
 * services/integrations/connectors/adapters.py ALL_CONNECTORS (14 adapters) plus
 * the seven branded comms connectors (klaviyo, sendgrid, customerio, mailchimp,
 * postmark, iterable, braze). Every dataset id must be in this allowlist and every
 * allowlist id must be present — the directory must never fabricate a provider.
 */
const REAL_CONNECTOR_IDS: readonly string[] = [
  'slack',
  'webhook',
  'shopify',
  'stripe',
  'hubspot',
  'salesforce',
  'klaviyo',
  'segment',
  'posthog',
  'ga4',
  'jira',
  'linear',
  'zendesk',
  'intercom',
  'dune',
  'sendgrid',
  'customerio',
  'mailchimp',
  'postmark',
  'iterable',
  'braze',
];

const datasetIds: readonly string[] = CONNECTORS.map((connector) => connector.id);

describe('connectors dataset', () => {
  it('covers the real registry (21 connectors)', () => {
    expect(CONNECTORS.length).toBeGreaterThanOrEqual(20);
    expect(CONNECTORS.length).toBe(REAL_CONNECTOR_IDS.length);
  });

  it('uses unique registry ids', () => {
    expect(new Set(datasetIds).size).toBe(datasetIds.length);
  });

  it('never fabricates a provider id', () => {
    for (const id of datasetIds) {
      expect(REAL_CONNECTOR_IDS).toContain(id);
    }
    // The reverse direction too — nothing real is missing from the dataset.
    for (const id of REAL_CONNECTOR_IDS) {
      expect(datasetIds).toContain(id);
    }
  });

  it('keeps every status token inside the real readiness vocabulary', () => {
    const knownTokens = Object.keys(CONNECTOR_STATUS_LABELS);
    for (const connector of CONNECTORS) {
      expect(knownTokens).toContain(connector.status);
    }
    // Sanity: the union type and the label map cover the same tokens.
    const tokenUnion: readonly ConnectorReadiness[] = [
      'scaffolded',
      'disabled',
      'degraded',
      'credential_waiting',
      'replay_validated',
      'sandbox_validated',
      'partner_live',
    ];
    expect(tokenUnion.slice().sort()).toEqual(knownTokens.slice().sort());
  });

  it('records every connector as inbound tenant-BYOD ingestion', () => {
    for (const connector of CONNECTORS) {
      expect(connector.dataDirection).toBe('inbound');
    }
  });

  it('gives every connector at least one real ingest path', () => {
    for (const connector of CONNECTORS) {
      expect(connector.pull || connector.webhook).toBe(true);
    }
  });

  it('derives CONNECTOR_CATEGORIES from the real categories in the records', () => {
    const categoriesFromRecords = [
      ...new Set(CONNECTORS.map((connector) => connector.category)),
    ].sort();
    expect(CONNECTOR_CATEGORIES).toEqual(categoriesFromRecords);
  });

  it('resolves real ids through findConnector and rejects unknown ids', () => {
    for (const connector of CONNECTORS) {
      expect(findConnector(connector.id)?.id).toBe(connector.id);
    }
    expect(findConnector('definitely-not-a-connector')).toBeUndefined();
    expect(findConnector('')).toBeUndefined();
  });
});
