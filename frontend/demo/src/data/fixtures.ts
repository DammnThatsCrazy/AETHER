// Synthetic, closed demo data for a single demo tenant. No real data; no backend.
export const DEMO_TENANT = {
  tenant_id: 'tenant_demo_orbit',
  name: 'Orbit Commerce (Demo)',
  plan: 'P3 — Growth Intelligence',
};

export const INGESTION_PATHS = [
  { id: 'sdk_web', kind: 'SDK', label: 'Web SDK', detail: '@aether/web installed — page, identify, commerce events', status: 'live' },
  { id: 'sdk_ios', kind: 'SDK', label: 'iOS SDK', detail: 'AetherSDK (CocoaPods) — represented', status: 'live' },
  { id: 'sdk_android', kind: 'SDK', label: 'Android SDK', detail: 'com.aether:sdk-android — represented', status: 'live' },
  { id: 'conn_shopify', kind: 'No-SDK', label: 'Shopify connector', detail: 'orders + customers synced (no app code)', status: 'live' },
  { id: 'webhook_stripe', kind: 'No-SDK', label: 'Signed webhook (Stripe)', detail: 'invoice.paid → graph signal', status: 'live' },
  { id: 'conn_hubspot', kind: 'No-SDK', label: 'HubSpot connector', detail: 'contacts + deals enrich the graph', status: 'live' },
];

export const PROFILE360 = {
  entity: 'Maya Chen',
  signals: 42,
  identities: ['email', 'web session', 'wallet 0x7a…e1', 'Shopify customer', 'HubSpot contact'],
  relationships: 11,
  confidence: 0.91,
};

export const RECOMMENDATIONS = [
  { id: 'rec_1', family: 'retention_play', title: 'Re-engage high-LTV cart abandoner', confidence: 0.86, status: 'recommended' },
  { id: 'rec_2', family: 'expansion', title: 'Offer Pro upgrade to power user cohort', confidence: 0.78, status: 'recommended' },
  { id: 'rec_3', family: 'risk', title: 'Flag refund-abuse pattern on account', confidence: 0.81, status: 'recommended' },
];

export const OODA = [
  { step: 'Observe', detail: 'Ingest SDK + connector events into the event store.' },
  { step: 'Orient', detail: 'Resolve identities, build the graph + Profile360.' },
  { step: 'Decide', detail: 'Recommendation families propose governed actions.' },
  { step: 'Act', detail: 'Approved decision dispatches to Slack / webhook / CRM.' },
  { step: 'Learn', detail: 'Outcomes feed the ledger and update confidence.' },
];

export const DECISIONS = [
  { id: 'dec_1', recommendation: 'rec_1', action: 'Send win-back offer via Klaviyo', status: 'approved' },
  { id: 'dec_2', recommendation: 'rec_2', action: 'Queue upgrade nudge in-app', status: 'approved' },
];

export const DISPATCHES = [
  { id: 'disp_1', decision: 'dec_1', target: 'webhook', status: 'delivered', receipt: 'sim-webhook-9f2a' },
  { id: 'disp_2', decision: 'dec_2', target: 'slack', status: 'delivered', receipt: 'sim-slack-1b77' },
];

export const OUTCOMES = [
  { id: 'out_1', decision: 'dec_1', label: 'success', value: 1280, currency: 'USD', confidence_delta: 0.04 },
  { id: 'out_2', decision: 'dec_2', label: 'success', value: 540, currency: 'USD', confidence_delta: 0.03 },
];

export const PLAYBOOKS = [
  { id: 'pb_1', name: 'Cart Abandonment Recovery', runs: 128, success_rate: 0.74, observed_value: 41200 },
  { id: 'pb_2', name: 'Expansion Nudge', runs: 64, success_rate: 0.69, observed_value: 18800 },
];

export const VALUE_REVIEW = {
  retained_revenue: 41200,
  expansion_revenue: 18800,
  avoided_loss: 9600,
  total: 69600,
};

export const DATA_QUALITY = {
  overall: 0.93,
  status: 'healthy',
  dimensions: { event: 0.96, identity: 0.93, graph: 0.94, recommendation: 0.9, outcome: 0.91 },
};

export const KYBER_VIEW = {
  tenant: DEMO_TENANT.name,
  health_score: 0.88,
  expansion_score: 0.72,
  renewal_risk: 'low',
  recommendations_acted: 2,
  value_created_total: VALUE_REVIEW.total,
  intelligence_quality: DATA_QUALITY.overall,
};
