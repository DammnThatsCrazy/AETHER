// =============================================================================
// Example: Campaign spend → revenue linkage via outcome edges.
//
// Demonstrates:
//   • ResourceNode of type "campaign"
//   • Two Actions with economic blocks (spend + revenue)
//   • Relationship.outcome carrying causal revenue attribution
//   • Derived EconomicState aggregation (lazy, never persisted)
// =============================================================================

import {
  aggregateEconomicState,
  createResourceNode,
  validateEconomicPayload,
  validateRelationshipExtensions,
  type EconomicActionLike,
} from '@aether/shared';

const campaign = createResourceNode({
  id: 'res_campaign_acme_2026Q1',
  type: 'campaign',
  platform: 'meta',
  metadata: { objective: 'conversions', budgetUSD: 500 },
});

const spend: EconomicActionLike = {
  id: 'act_spend_1',
  economic: validateEconomicPayload({
    amount: 100,
    currency: 'USD',
    direction: 'pay',
    counterparty_type: 'platform',
    counterparty_id: campaign.id,
    rail: 'stripe',
  }),
};

const revenue: EconomicActionLike = {
  id: 'act_rev_1',
  economic: validateEconomicPayload({
    amount: 350,
    currency: 'USD',
    direction: 'receive',
    counterparty_type: 'platform',
    counterparty_id: 'shopify',
    rail: 'stripe',
  }),
};

const causal = validateRelationshipExtensions({
  flow_ref: { flow_id: 'campaign_acme_2026Q1', sequence: 1 },
  interaction_mode: 'A2A',
  outcome: { metric: 'revenue', value: 350 },
});

const state = aggregateEconomicState([spend, revenue], { units: 7 });
// → { total_spend: 100, total_revenue: 350, unit_cost: 14.285714... }

// eslint-disable-next-line no-console
console.log({ campaign, spend, revenue, causal, state });
