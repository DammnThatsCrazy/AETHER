// =============================================================================
// Example: H2A authorization → A2A transfer.
//
// Demonstrates:
//   • Authorization embedded on a parent Action
//   • Two related Actions sharing a flow_ref (sequence 0 → 1)
//   • Different interaction_mode per edge (H2A then A2A)
//   • Spend amount enforced against authorization.limit by the caller
// =============================================================================

import {
  validateAuthorization,
  validateEconomicPayload,
  validateRelationshipExtensions,
  type EconomicActionLike,
} from '@aether/shared';

const auth = validateAuthorization({
  source: 'human',
  scope: 'spend:campaign=acme',
  limit: 200,
});

// Human approves an agent-initiated workflow. No economic block on this
// Action — the authorization itself is the relevant signal.
const approval: EconomicActionLike = {
  id: 'act_h2a_1',
  authorization: auth,
};

// Agent A transfers value to Agent B as part of executing that approval.
const transfer: EconomicActionLike = {
  id: 'act_a2a_1',
  authorization: auth,
  economic: validateEconomicPayload({
    amount: 50,
    currency: 'USD',
    direction: 'pay',
    counterparty_type: 'agent',
    counterparty_id: 'agent_buyer',
    rail: 'internal',
  }),
};

const h2aEdge = validateRelationshipExtensions({
  flow_ref: { flow_id: 'flow_acme_purchase_42', sequence: 0 },
  interaction_mode: 'H2A',
  economic_involved: false,
});

const a2aEdge = validateRelationshipExtensions({
  flow_ref: { flow_id: 'flow_acme_purchase_42', sequence: 1 },
  interaction_mode: 'A2A',
  economic_involved: true,
});

// Caller-side guard against over-spend.
if ((transfer.economic?.amount ?? 0) > (auth.limit ?? Infinity)) {
  throw new Error('spend exceeds authorization limit');
}

// eslint-disable-next-line no-console
console.log({ approval, transfer, h2aEdge, a2aEdge });
