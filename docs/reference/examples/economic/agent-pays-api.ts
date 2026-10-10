// =============================================================================
// Example: Agent paying a paid API via an x402-style handshake.
//
// Demonstrates:
//   • Action with an embedded economic block
//   • Handshake lifecycle (pending → paid)
//   • Action → Handshake → Action edges (initiates / resolves_to)
// =============================================================================

import {
  createHandshake,
  transitionHandshake,
  validateEconomicPayload,
  validateRelationshipExtensions,
  type EconomicActionLike,
  type Handshake,
} from '@aether/shared';

// 1. Buyer agent sees a 402 response and records the handshake locally.
let hs: Handshake = createHandshake({
  id: 'hs_x402_summarize_1',
  request_id: 'req_summarize_1',
  required_amount: 0.05,
  timestamp: Date.now(),
});

// 2. Buyer agent emits the payment Action; it points at the handshake via an
//    `initiates` relationship in the graph.
const payment: EconomicActionLike = {
  id: 'act_pay_1',
  economic: validateEconomicPayload({
    amount: 0.05,
    currency: 'USD',
    direction: 'pay',
    counterparty_type: 'service',
    counterparty_id: 'svc_summarize_api',
    rail: 'internal',
  }),
};

const initiates = validateRelationshipExtensions({
  flow_ref: { flow_id: 'flow_summarize_1', sequence: 0 },
  interaction_mode: 'A2A',
  economic_involved: true,
});

// 3. Service confirms receipt; the handshake transitions to `paid`. A
//    `resolves_to` edge from Handshake → Action records the link.
hs = transitionHandshake(hs, 'paid');

const resolvesTo = validateRelationshipExtensions({
  flow_ref: { flow_id: 'flow_summarize_1', sequence: 1 },
  interaction_mode: 'A2A',
  economic_involved: true,
});

// eslint-disable-next-line no-console
console.log({ hs, payment, initiates, resolvesTo });
