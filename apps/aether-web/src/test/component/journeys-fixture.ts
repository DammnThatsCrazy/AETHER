/**
 * Shared compiled-journey fixture for the Journeys and Episodes page tests.
 * Shaped like GET /v1/profile/{id}/unified-journey. Times are anchored to
 * FIXTURE_NOW (tests fake only `Date`).
 */
export const FIXTURE_NOW = new Date(2026, 9, 16, 15, 0, 0).getTime();

const at = (minsAgo: number) => new Date(FIXTURE_NOW - minsAgo * 60_000).toISOString();

function step(id: string, pos: number, minsAgo: number, extra: Record<string, unknown>) {
  return {
    step_id: id,
    step_position: pos,
    activity_family: 'web2',
    activity_type: 'page_view',
    activity_status: 'observed',
    actor_type: 'human',
    source_class: null,
    ai_provider: null,
    ai_product: null,
    referral_mediation_type: null,
    journey_role: null,
    verification_level: null,
    evidence_confidence: null,
    attributed_net_revenue: null,
    transition_type: null,
    channel: null,
    source: null,
    domain: null,
    dapp_id: null,
    chain_id: null,
    wallet_id: null,
    agent_id: null,
    campaign_id: null,
    session_id: null,
    identity_confidence: null,
    identity_method: null,
    occurred_at: at(minsAgo),
    displayLabel: id,
    risk_score: null,
    risk_tier: null,
    fraud_status: null,
    fraud_disposition: null,
    ...extra,
  };
}

/** Two episodes: s1–s3 (~5 hours ago) and s4–s5 (last 10 minutes). */
export function journeyPayload(overrides: Record<string, unknown> = {}) {
  return {
    entity_id: 'u-1',
    steps: [
      // Returned out of order on purpose: the model sorts by time.
      step('s2', 2, 295, { displayLabel: 'Campaign click', activity_family: 'campaign', campaign_id: 'c-spring', session_id: 'sess-a', channel: 'email' }),
      step('s1', 1, 300, { displayLabel: 'Landing visit', source: 'google', domain: 'shop.example', session_id: 'sess-a', verification_level: 'verified', evidence_confidence: 0.9 }),
      step('s3', 3, 290, { displayLabel: 'Agent compare', activity_family: 'agent', actor_type: 'agent', agent_id: 'agent-atlas', ai_provider: 'openai', session_id: 'sess-a' }),
      step('s4', 4, 10, { displayLabel: 'Order placed', activity_family: 'outcome', actor_type: null, session_id: 'sess-b', attributed_net_revenue: 120, wallet_id: 'w-1' }),
      step('s5', 5, 5, { displayLabel: 'Webhook sync', actor_type: 'system', session_id: 'sess-b', source: 'shopify' }),
    ],
    meta: { journey_id: 'j-1', journey_version_id: 'jv-1', step_count: 5, compiler_version: '2.0', quality_status: 'complete' },
    summary: { journey_id: 'j-1', journey_state: 'converted', step_count: 5, started_at: at(300), ended_at: at(5), converted_at: at(10) },
    pagination: { has_more: false },
    degraded_dimensions: [],
    ...overrides,
  };
}
