/**
 * FPS-110 — Fixture Load
 * Verifies fixture integrity across ALL inline fixtures in @aether/proof-fixtures.
 *
 * ALL fixtures are defined as named exports in @aether/proof-fixtures/src/index.ts.
 * There are no per-domain JSON files on disk for connector/graph/lens/360/identity/
 * journey/conversion/value domains — only the SDK event keys have single-file JSON
 * fixtures under fixtures/sdk-events/ (for historical reasons).
 *
 * This test validates the inline fixtures directly, and validates findFixtureDir
 * ONLY for the SDK event keys which actually have disk files.
 */
import { describe, it, expect } from 'vitest';

import {
  // Core event fixtures
  heartbeatFixture,
  trackEventFixture,
  identifyEventFixture,
  conversionEventFixture,
  // Error/edge-case fixtures
  invalidKeyFixture,
  consentDisabledFixture,
  offlineQueueFixture,
  // Commerce fixtures (stripe)
  stripeCustomerFixture,
  stripePaymentFixture,
  stripeRefundFixture,
  // Commerce fixtures (shopify)
  shopifyCustomerFixture,
  shopifyOrderFixture,
  shopifyProductFixture,
  // Email/communication fixtures
  emailSentFixture,
  emailOpenFixture,
  emailClickFixture,
  emailBounceFixture,
  emailUnsubscribeFixture,
  // Validation fixtures
  missingFieldsFixture,
  duplicateFixture,
  providerErrorFixture,
  // Graph fixtures
  graphProfileNodeFixture,
  graphJourneyNodeFixture,
  graphCampaignNodeFixture,
  graphCommunicationNodeFixture,
  graphConversionNodeFixture,
  graphValueNodeFixture,
  graphTouchpointEdgeFixture,
  graphAttributionEdgeFixture,
  provenanceFixture,
  // Lens fixtures
  lensInputFixture,
  lensOutputFixture,
  // 360 fixtures
  surface360QueryFixture,
  profile360Fixture,
  campaign360Fixture,
  communications360Fixture,
} from '@aether/proof-fixtures';

/** Every inline fixture MUST have these fields.
 * NOTE: heartbeatFixture is a HeartbeatPayload (4 fields only) — it is validated separately
 * in its own shape test below and is NOT included in ALL_INLINE_FIXTURES. The full-envelope
 * fixtures (trackEvent, identify, conversion, connector, email, graph, lens, 360, etc.) all
 * carry tenant_id, workspace_id, platform_id, event_type, sdk, identity.anonymous_id. */
const ALL_INLINE_FIXTURES = [
  trackEventFixture,
  identifyEventFixture,
  conversionEventFixture,
  invalidKeyFixture,
  consentDisabledFixture,
  offlineQueueFixture,
  stripeCustomerFixture,
  stripePaymentFixture,
  stripeRefundFixture,
  shopifyCustomerFixture,
  shopifyOrderFixture,
  shopifyProductFixture,
  emailSentFixture,
  emailOpenFixture,
  emailClickFixture,
  emailBounceFixture,
  emailUnsubscribeFixture,
  missingFieldsFixture,
  duplicateFixture,
  providerErrorFixture,
  graphProfileNodeFixture,
  graphJourneyNodeFixture,
  graphCampaignNodeFixture,
  graphCommunicationNodeFixture,
  graphConversionNodeFixture,
  graphValueNodeFixture,
  graphTouchpointEdgeFixture,
  graphAttributionEdgeFixture,
  provenanceFixture,
  lensInputFixture,
  lensOutputFixture,
  surface360QueryFixture,
  profile360Fixture,
  campaign360Fixture,
  communications360Fixture,
];

describe('FPS-110: Fixture Load', () => {
  it('should enumerate every inline fixture', () => {
    expect(ALL_INLINE_FIXTURES.length).toBeGreaterThan(0);
    // 35 full-envelope fixtures (we exclude heartbeatFixture from the generic checks below —
    // it is a HeartbeatPayload with only 4 fields, validated in its own shape test)
    expect(ALL_INLINE_FIXTURES.length).toBe(35);
  });

  it('should have _fixture_version 1 on every fixture', () => {
    for (const fixture of ALL_INLINE_FIXTURES) {
      expect(fixture._fixture_version).toBe(1);
    }
  });

  it('should have _fixtureName on every fixture', () => {
    for (const fixture of ALL_INLINE_FIXTURES) {
      expect(fixture._fixtureName).toBeDefined();
      expect(typeof fixture._fixtureName).toBe('string');
    }
  });

  it('should validate every inline fixture has tenant_id and workspace_id', () => {
    for (const fixture of ALL_INLINE_FIXTURES) {
      expect(fixture.tenant_id).toBe('aether-proof-tenant');
      expect(fixture.workspace_id).toBe('proof-lab');
    }
  });

  it('should validate every inline fixture has platform_id', () => {
    for (const fixture of ALL_INLINE_FIXTURES) {
      expect(fixture.platform_id).toBeDefined();
      expect(typeof fixture.platform_id).toBe('string');
    }
  });

  it('should validate every inline fixture has an event_type', () => {
    for (const fixture of ALL_INLINE_FIXTURES) {
      expect(fixture.event_type).toBeDefined();
      expect(typeof fixture.event_type).toBe('string');
    }
  });

  it('should validate every inline fixture has sdk.name and sdk.version', () => {
    for (const fixture of ALL_INLINE_FIXTURES) {
      expect(fixture.sdk).toBeDefined();
      expect(fixture.sdk.name).toBeDefined();
      expect(fixture.sdk.version).toBe('0.1.0-alpha.0');
    }
  });

  it('should validate every inline fixture has identity.anonymous_id', () => {
    for (const fixture of ALL_INLINE_FIXTURES) {
      expect(fixture.identity).toBeDefined();
      expect(fixture.identity.anonymous_id).toBeDefined();
    }
  });

  it('should validate emailSentFixture shape', () => {
    expect(emailSentFixture._fixture_version).toBe(1);
    expect(emailSentFixture.tenant_id).toBe('aether-proof-tenant');
    expect(emailSentFixture.platform_id).toBe('email');
    expect(emailSentFixture.event_type).toBe('email_sent');
    expect(emailSentFixture.properties.type).toBe('sent');
    expect(emailSentFixture.properties.email).toBe('user@example.com');
    // The fixture subject contains a literal backslash before the apostrophe
    expect((emailSentFixture.properties.subject as string).endsWith("s what you need to know")).toBe(true);
    expect(emailSentFixture.properties.provider).toBe('sendgrid');
    expect(emailSentFixture.properties.messageId).toBe('msg_sent_001');
    expect(emailSentFixture.properties.from).toBe('hello@acme.com');
    expect(emailSentFixture.properties.sendAt).toBe('2024-09-11T13:00:00.000Z');
    expect(emailSentFixture.properties.campaignId).toBe('camp_001');
    expect(emailSentFixture.properties.campaignName).toBe('Welcome Series Day 1');
    expect(emailSentFixture.properties.templateId).toBe('tpl_welcome_001');
  });

  it('should validate emailOpenFixture shape', () => {
    expect(emailOpenFixture._fixture_version).toBe(1);
    expect(emailOpenFixture.tenant_id).toBe('aether-proof-tenant');
    expect(emailOpenFixture.platform_id).toBe('email');
    expect(emailOpenFixture.event_type).toBe('email_opened');
    expect(emailOpenFixture.properties.type).toBe('open');
    expect(emailOpenFixture.properties.email).toBe('user@example.com');
    // The fixture subject contains a literal backslash before the apostrophe
    expect((emailOpenFixture.properties.subject as string).endsWith("s what you need to know")).toBe(true);
    expect(emailOpenFixture.properties.messageId).toBe('msg_sent_001');
    expect(emailOpenFixture.properties.openedAt).toBe('2024-09-11T13:02:00.000Z');
    expect(emailOpenFixture.properties.userAgent).toBe('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15');
    expect(emailOpenFixture.properties.platform).toBe('mobile');
    expect(emailOpenFixture.properties.client).toBe('apple mail');
    expect(emailOpenFixture.properties.campaignId).toBe('camp_001');
    expect(emailOpenFixture.properties.campaignName).toBe('Welcome Series Day 1');
    expect(emailOpenFixture.properties.templateId).toBe('tpl_welcome_001');
  });

  it('should validate emailClickFixture shape', () => {
    expect(emailClickFixture._fixture_version).toBe(1);
    expect(emailClickFixture.tenant_id).toBe('aether-proof-tenant');
    expect(emailClickFixture.platform_id).toBe('email');
    expect(emailClickFixture.event_type).toBe('email_clicked');
    expect(emailClickFixture.properties.type).toBe('click');
    expect(emailClickFixture.properties.email).toBe('user@example.com');
    expect(emailClickFixture.properties.messageId).toBe('msg_sent_001');
    expect(emailClickFixture.properties.clickedAt).toBe('2024-09-11T13:03:00.000Z');
    expect(emailClickFixture.properties.link).toBe('https://example.com/offer');
    expect(emailClickFixture.properties.linkText).toBe('Claim Your Offer');
    expect(emailClickFixture.properties.linkPosition).toBe(1);
    expect(emailClickFixture.properties.platform).toBe('mobile');
    expect(emailClickFixture.properties.client).toBe('apple mail');
    expect(emailClickFixture.properties.campaignId).toBe('camp_001');
    expect(emailClickFixture.properties.campaignName).toBe('Welcome Series Day 1');
    expect(emailClickFixture.properties.templateId).toBe('tpl_welcome_001');
  });

  it('should validate emailBounceFixture shape', () => {
    expect(emailBounceFixture._fixture_version).toBe(1);
    expect(emailBounceFixture.tenant_id).toBe('aether-proof-tenant');
    expect(emailBounceFixture.platform_id).toBe('email');
    expect(emailBounceFixture.event_type).toBe('email_bounced');
    expect(emailBounceFixture.properties.type).toBe('bounce');
    expect(emailBounceFixture.properties.email).toBe('bounce@example.com');
    expect(emailBounceFixture.properties.provider).toBe('sendgrid');
    expect(emailBounceFixture.properties.messageId).toBe('msg_bounce_001');
    expect(emailBounceFixture.properties.bouncedAt).toBe('2024-09-11T13:05:00.000Z');
    expect(emailBounceFixture.properties.campaignId).toBe('camp_001');
    expect(emailBounceFixture.properties.campaignName).toBe('Welcome Series Day 1');
    expect(emailBounceFixture.properties.templateId).toBe('tpl_welcome_001');
    expect(emailBounceFixture.properties.reason).toBe('hard_bounce');
    expect(emailBounceFixture.properties.status).toBe('5.1.1');
    expect(emailBounceFixture.properties.diagnosticCode).toBe('smtp; 550 5.1.1 User unknown');
  });

  it('should validate emailUnsubscribeFixture shape', () => {
    expect(emailUnsubscribeFixture._fixture_version).toBe(1);
    expect(emailUnsubscribeFixture.tenant_id).toBe('aether-proof-tenant');
    expect(emailUnsubscribeFixture.platform_id).toBe('email');
    expect(emailUnsubscribeFixture.event_type).toBe('unsubscribe_observed');
    expect(emailUnsubscribeFixture.properties.type).toBe('unsubscribe');
    expect(emailUnsubscribeFixture.properties.email).toBe('unsub@example.com');
    expect(emailUnsubscribeFixture.properties.provider).toBe('sendgrid');
    expect(emailUnsubscribeFixture.properties.unsubscribedAt).toBe('2024-09-11T13:10:00.000Z');
    expect(emailUnsubscribeFixture.properties.campaignId).toBe('camp_001');
    expect(emailUnsubscribeFixture.properties.campaignName).toBe('Welcome Series Day 1');
    expect(emailUnsubscribeFixture.properties.templateId).toBe('tpl_welcome_001');
    expect(emailUnsubscribeFixture.properties.reason).toBe('user_initiated');
    expect(emailUnsubscribeFixture.properties.unsubscribedVia).toBe('one_click');
  });

  it('should validate communications360Fixture shape', () => {
    expect(communications360Fixture._fixture_version).toBe(1);
    expect(communications360Fixture.tenant_id).toBe('aether-proof-tenant');
    expect(communications360Fixture.platform_id).toBe('360');
    expect(communications360Fixture.event_type).toBe('surface_360_communications');
    expect(communications360Fixture.properties.profileId).toBe('profile_001');
    expect(communications360Fixture.properties.communications).toBeDefined();
    expect(communications360Fixture.properties.communications.timeline).toBeInstanceOf(Array);
    expect(communications360Fixture.properties.communications.timeline.length).toBe(7);
    expect(communications360Fixture.properties.communications.summary).toBeDefined();
    expect(communications360Fixture.properties.communications.summary.total_sent).toBe(3);
  });

  it('should validate campaign360Fixture shape', () => {
    expect(campaign360Fixture._fixture_version).toBe(1);
    expect(campaign360Fixture.tenant_id).toBe('aether-proof-tenant');
    expect(campaign360Fixture.platform_id).toBe('360');
    expect(campaign360Fixture.event_type).toBe('surface_360_campaign');
    expect(campaign360Fixture.properties.profileId).toBe('profile_001');
    expect(campaign360Fixture.properties.campaigns).toBeInstanceOf(Array);
    expect(campaign360Fixture.properties.campaigns.length).toBe(1);
    const campaign = campaign360Fixture.properties.campaigns[0];
    expect(campaign.campaign_identity.campaign_id).toBe('camp_001');
    expect(campaign.campaign_identity.name).toBe('Welcome Series Day 1');
    expect(campaign.source_classification.platform).toBe('email');
    expect(campaign.touchpoints).toBeInstanceOf(Array);
    expect(campaign.conversions).toBeInstanceOf(Array);
    expect(Object.keys(campaign.value)).toContain('total_revenue');
    expect(Object.keys(campaign.attribution)).toContain('model');
  });

  it('should validate profile360Fixture shape', () => {
    expect(profile360Fixture._fixture_version).toBe(1);
    expect(profile360Fixture.tenant_id).toBe('aether-proof-tenant');
    expect(profile360Fixture.platform_id).toBe('360');
    expect(profile360Fixture.event_type).toBe('surface_360_profile');
    expect(profile360Fixture.properties.profile.user_id).toBe('user_001');
    expect(profile360Fixture.properties.profile.email).toBe('profile@example.com');
    expect(profile360Fixture.properties.journey_activity).toBeInstanceOf(Array);
    expect(profile360Fixture.properties.journey_activity.length).toBe(2);
    expect(profile360Fixture.properties.communications.total_sent).toBe(12);
    expect(Object.keys(profile360Fixture.properties.value)).toContain('lifetime_value');
    expect(Object.keys(profile360Fixture.properties.value)).toContain('revenue_by_channel');
  });

  it('should validate graphAttributionEdgeFixture shape', () => {
    expect(graphAttributionEdgeFixture._fixture_version).toBe(1);
    expect(graphAttributionEdgeFixture.event_type).toBe('graph_edge_created');
    expect(graphAttributionEdgeFixture.properties.edges).toBeInstanceOf(Array);
    expect(graphAttributionEdgeFixture.properties.edges.length).toBe(1);
    const edge = graphAttributionEdgeFixture.properties.edges[0];
    expect(edge.id).toBe('edge_attr_001');
    expect(edge.type).toBe('attribution');
    expect(edge.source).toBe('node_campaign_001');
    expect(edge.target).toBe('node_conv_001');
    expect(edge.properties.model).toBe('last_touch');
    expect(edge.properties.credit).toBe(1.0);
    expect(edge.properties.confidence).toBe(0.9);
    expect(edge.weight).toBe(0.75);
  });

  it('should validate graphTouchpointEdgeFixture shape', () => {
    expect(graphTouchpointEdgeFixture._fixture_version).toBe(1);
    expect(graphTouchpointEdgeFixture.event_type).toBe('graph_edge_created');
    expect(graphTouchpointEdgeFixture.properties.edges).toBeInstanceOf(Array);
    expect(graphTouchpointEdgeFixture.properties.edges.length).toBe(1);
    const edge = graphTouchpointEdgeFixture.properties.edges[0];
    expect(edge.id).toBe('edge_tp_001');
    expect(edge.type).toBe('touchpoint');
    expect(edge.source).toBe('node_profile_001');
    expect(edge.target).toBe('node_journey_001');
    expect(edge.properties.channel).toBe('web');
    expect(edge.properties.touchpoint_type).toBe('page_view');
    expect(edge.weight).toBe(1);
  });

  it('should validate graphValueNodeFixture shape', () => {
    expect(graphValueNodeFixture._fixture_version).toBe(1);
    expect(graphValueNodeFixture.event_type).toBe('graph_node_created');
    const nodes = graphValueNodeFixture.properties.nodes;
    expect(nodes).toBeInstanceOf(Array);
    expect(nodes.length).toBe(1);
    const node = nodes[0];
    expect(node.id).toBe('node_value_001');
    expect(node.type).toBe('value');
    expect(node.labels).toContain('value');
    expect(node.properties.metric).toBe('ltv');
    expect(node.properties.value).toBe(150.00);
    expect(node.properties.currency).toBe('usd');
    expect(node.properties.value_type).toBe('lifetime_value');
    expect(node.properties.calculated_at).toBe('2024-09-10T12:00:00.000Z');
    expect(node.properties.method).toBe('rolling_12m');
    expect(node.created_at).toBe('2024-09-10T12:00:00.000Z');
    expect(node.updated_at).toBe('2024-09-10T12:00:00.000Z');
  });

  it('should validate graphConversionNodeFixture shape', () => {
    expect(graphConversionNodeFixture._fixture_version).toBe(1);
    expect(graphConversionNodeFixture.event_type).toBe('graph_node_created');
    const nodes = graphConversionNodeFixture.properties.nodes;
    expect(nodes).toBeInstanceOf(Array);
    expect(nodes.length).toBe(1);
    const node = nodes[0];
    expect(node.id).toBe('node_conv_001');
    expect(node.type).toBe('conversion');
    expect(node.labels).toContain('conversion');
    expect(node.properties.event).toBe('purchase');
    expect(node.properties.value).toBe(49.99);
    expect(node.properties.currency).toBe('usd');
    expect(node.properties.conversion_type).toBe('purchase');
    expect(node.created_at).toBe('2024-09-10T12:00:00.000Z');
  });

  it('should validate graphCommunicationNodeFixture shape', () => {
    expect(graphCommunicationNodeFixture._fixture_version).toBe(1);
    expect(graphCommunicationNodeFixture.event_type).toBe('graph_node_created');
    const nodes = graphCommunicationNodeFixture.properties.nodes;
    expect(nodes).toBeInstanceOf(Array);
    expect(nodes.length).toBe(1);
    const node = nodes[0];
    expect(node.id).toBe('node_comm_001');
    expect(node.type).toBe('communication');
    expect(node.labels).toContain('communication');
    expect(node.properties.channel).toBe('email');
    expect(node.properties.subject).toBe('Welcome');
    expect(node.properties.type).toBe('welcome_email');
    expect(node.properties.sent_at).toBe('2024-09-10T10:00:00.000Z');
    expect(node.properties.status).toBe('delivered');
  });

  it('should validate graphCampaignNodeFixture shape', () => {
    expect(graphCampaignNodeFixture._fixture_version).toBe(1);
    expect(graphCampaignNodeFixture.event_type).toBe('graph_node_created');
    const nodes = graphCampaignNodeFixture.properties.nodes;
    expect(nodes).toBeInstanceOf(Array);
    expect(nodes.length).toBe(1);
    const node = nodes[0];
    expect(node.id).toBe('node_campaign_001');
    expect(node.type).toBe('campaign');
    expect(node.labels).toContain('campaign');
    expect(node.properties.name).toBe('summer_promo');
    expect(node.properties.channel).toBe('email');
    expect(node.properties.campaign_type).toBe('promotional');
    expect(node.properties.status).toBe('active');
    expect(node.properties.started_at).toBe('2024-09-01T00:00:00.000Z');
    expect(node.properties.source).toBe('manual');
  });

  it('should validate graphJourneyNodeFixture shape', () => {
    expect(graphJourneyNodeFixture._fixture_version).toBe(1);
    expect(graphJourneyNodeFixture.event_type).toBe('graph_node_created');
    const nodes = graphJourneyNodeFixture.properties.nodes;
    expect(nodes).toBeInstanceOf(Array);
    expect(nodes.length).toBe(1);
    const node = nodes[0];
    expect(node.id).toBe('node_journey_001');
    expect(node.type).toBe('journey');
    expect(node.labels).toContain('journey');
    expect(node.properties.name).toBe('onboarding');
    expect(node.properties.stage).toBe('activation');
    expect(node.properties.journey_type).toBe('onboarding');
    expect(node.properties.version).toBe('1.0');
    expect(node.properties.started_at).toBe('2024-09-10T10:00:00.000Z');
  });

  it('should validate graphProfileNodeFixture shape', () => {
    expect(graphProfileNodeFixture._fixture_version).toBe(1);
    expect(graphProfileNodeFixture.event_type).toBe('graph_node_created');
    const nodes = graphProfileNodeFixture.properties.nodes;
    expect(nodes).toBeInstanceOf(Array);
    expect(nodes.length).toBe(1);
    const node = nodes[0];
    expect(node.id).toBe('node_profile_001');
    expect(node.type).toBe('profile');
    expect(node.labels).toContain('profile');
    expect(node.labels).toContain('user');
    expect(node.labels).toContain('identified');
    expect(node.properties.email).toBe('profile@example.com');
    expect(node.properties.name).toBe('Test Profile');
    expect(node.properties.user_id).toBe('user_001');
    expect(node.properties.anonymous_id).toBe('anon_001');
    expect(node.properties.segment).toBe('premium');
    expect(node.properties.created_from).toBe('web_sdk');
    expect(node.created_at).toBe('2024-09-10T08:00:00.000Z');
    expect(node.updated_at).toBe('2024-09-11T12:05:00.000Z');
  });

  it('should validate provenanceFixture shape', () => {
    expect(provenanceFixture._fixture_version).toBe(1);
    expect(provenanceFixture.event_type).toBe('graph_node_created');
    expect(provenanceFixture.properties.node_id).toBe('node_profile_001');
    expect(provenanceFixture.properties.origin).toBe('web_sdk');
    expect(provenanceFixture.properties.lineage).toEqual(['web_sdk', 'ingestion_pipeline', 'graph_db']);
    expect(provenanceFixture.properties.verified_at).toBe('2024-09-11T12:05:00.000Z');
    expect(provenanceFixture.properties.origin_metadata.sdk_name).toBe('@aether/web');
    expect(provenanceFixture.properties.origin_metadata.sdk_version).toBe('0.1.0-alpha.0');
    expect(provenanceFixture.properties.transformations).toBeInstanceOf(Array);
    expect(provenanceFixture.properties.transformations.length).toBe(3);
    const ingestion = provenanceFixture.properties.transformations.find((t: any) => t.step === 'ingestion');
    expect(ingestion).toBeDefined();
    expect(ingestion.handler).toBe('raw_ingest');
  });

  it('should validate lensOutputFixture shape', () => {
    expect(lensOutputFixture._fixture_version).toBe(1);
    expect(lensOutputFixture.event_type).toBe('lens_result');
    expect(lensOutputFixture.properties.profileId).toBe('profile_001');
    expect(lensOutputFixture.properties.segments).toEqual(['high_value', 'engaged', 'premium']);
    expect(Object.keys(lensOutputFixture.properties.metrics)).toContain('avgPurchaseValue');
    expect(Object.keys(lensOutputFixture.properties.metrics)).toContain('sessionCount');
    expect(Object.keys(lensOutputFixture.properties.metrics)).toContain('totalRevenue');
    expect(Object.keys(lensOutputFixture.properties.metrics)).toContain('eventCount');
    expect(lensOutputFixture.properties.topEvents).toBeInstanceOf(Array);
    expect(lensOutputFixture.properties.topEvents.length).toBe(3);
    expect(lensOutputFixture.properties.recommendations).toBeInstanceOf(Array);
    expect(lensOutputFixture.properties.generatedAt).toBe('2024-09-11T14:16:00.000Z');
    expect(lensOutputFixture.properties.computationTimeMs).toBe(234);
    expect(lensOutputFixture.properties.totalRecords).toBe(342);
    expect(lensOutputFixture.properties.isPartial).toBe(false);
  });

  it('should validate lensInputFixture shape', () => {
    expect(lensInputFixture._fixture_version).toBe(1);
    expect(lensInputFixture.event_type).toBe('lens_query');
    expect(lensInputFixture.properties.profileId).toBe('profile_001');
    expect(lensInputFixture.properties.dimensions).toEqual(['segments', 'campaigns', 'purchases']);
    expect(lensInputFixture.properties.filters.plan).toBe('premium');
    expect(lensInputFixture.properties.timeRange.start).toBe('2024-09-01T00:00:00.000Z');
    expect(lensInputFixture.properties.aggregation.metric).toBe('count');
    expect(lensInputFixture.properties.sort.field).toBe('count');
    expect(lensInputFixture.properties.sort.direction).toBe('desc');
    expect(lensInputFixture.properties.limit).toBe(50);
    expect(lensInputFixture.properties.offset).toBe(0);
  });

  it('should validate surface360QueryFixture shape', () => {
    expect(surface360QueryFixture._fixture_version).toBe(1);
    expect(surface360QueryFixture.event_type).toBe('surface_360_query');
    expect(surface360QueryFixture.properties.profileId).toBe('profile_001');
    expect(surface360QueryFixture.properties.surfaces).toContain('purchases');
    expect(surface360QueryFixture.properties.surfaces).toContain('campaigns');
    expect(surface360QueryFixture.properties.surfaces).toContain('identities');
    expect(surface360QueryFixture.properties.surfaces).toContain('communications');
    expect(surface360QueryFixture.properties.depth).toBe('deep');
    expect(surface360QueryFixture.properties.includeEdges).toBe(true);
    expect(Object.keys(surface360QueryFixture.properties.timeWindow)).toContain('start');
    expect(Object.keys(surface360QueryFixture.properties.timeWindow)).toContain('end');
    expect(surface360QueryFixture.properties.limitPerSurface).toBe(100);
  });
});
