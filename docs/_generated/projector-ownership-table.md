<!-- DO NOT EDIT — generated from packages/shared/contracts/projector-ownership-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Silver Projector Ownership Registry

Contract version: `1.0.0`

Projectors in EXACT dispatcher order (ADR-C3). Activity ownership is ADR-C4: one real-world event, one canonical activity owner.

| # | Projector | Table | Activity role | Families | Types | Owned activity types |
|---|---|---|---|---|---|---|
| 1 | `CommsProjector` | `silver_comms_facts` | comms_owner | `comms` | 19 | 19 |
| 2 | `IdentityEvidenceProjector` | `silver_identity_evidence_facts` | fact_emitter | `identity_lc` | 15 | 15 |
| 3 | `TouchpointProjector` | `silver_campaign_touchpoint_facts` | touchpoint_owner | `comms`, `core`, `ecommerce`, `exposure`, `journey`, `outcome` | 27 | 21 |
| 4 | `ExposureProjector` | `silver_exposure_facts` | fact_emitter | `exposure` | 8 | 4 |
| 5 | `OutcomeProjector` | `silver_outcome_facts` | fact_emitter | `outcome` | 9 | 8 |
| 6 | `RevenueProjector` | `silver_revenue_facts` | fact_emitter | `commerce`, `ecommerce` | 17 | 17 |
| 7 | `FrictionProjector` | `silver_friction_facts` | no_activity | `friction` | 12 | 0 |
| 8 | `AccountActivityProjector` | `silver_account_activity_facts` | fact_emitter | `b2b` | 20 | 20 |
| 9 | `ServerOperationProjector` | `silver_server_operation_facts` | no_activity | `server` | 11 | 0 |
| 10 | `AgentExecutionProjector` | `silver_agent_execution_facts` | fact_emitter | `agent` | 60 | 60 |
| 11 | `AIInvocationProjector` | `ai_execution_facts` | no_activity | `agent` | 1 | 0 |
| 12 | `Web3TransactionProjector` | `silver_web3_transaction_facts` | fact_emitter | `wallet`, `web3_lc` | 15 | 15 |
| 13 | `X402FlowProjector` | `silver_x402_flow_facts` | fact_emitter | — | 6 | 6 |
| 14 | `StablecoinProjector` | `silver_stablecoin_facts` | no_activity | `stablecoin` | 26 | 0 |
| 15 | `DerivativesProjector` | `silver_derivatives_facts` | no_activity | `derivatives` | 33 | 0 |
| 16 | `InteropProjector` | `silver_interop_facts` | no_activity | `interop` | 31 | 0 |
| 17 | `ConversionProjector` | `canonical_conversions` | fact_emitter | `ecommerce`, `identity_lc` | 10 | 6 |
| 18 | `CardLinkedProjector` | `card_linked_flow_facts` | no_activity | `commerce`, `reward`, `wallet` | 6 | 0 |

## Convergent activity emitters

These projectors also emit canonical activity for the listed event types but converge on the owner's row via the idempotent upsert.

| Projector | Event types |
|---|---|
| `ConversionProjector` | `order_completed`, `signup_completed`, `subscription_started`, `trial_started` |

## Handled types absent from the event registry

| Projector | Event types |
|---|---|
| `TouchpointProjector` | `ad_click`, `click`, `impression`, `landing`, `page_view`, `pageview`, `search_performed`, `session_start`, `session_started` |
| `RevenueProjector` | `payment_intent_created`, `payment_succeeded` |
| `AgentExecutionProjector` | `agent_handoff_observed`, `agent_step_observed`, `agent_tool_call_observed`, `agentic_session_abandoned`, `agentic_session_completed`, `agentic_session_started` |
| `Web3TransactionProjector` | `transaction_confirmed`, `transaction_failed`, `transaction_initiated`, `transaction_submitted`, `wallet_connected`, `wallet_disconnected` |
| `X402FlowProjector` | `x402_payment_failed_observed`, `x402_payment_initiated_observed`, `x402_payment_required_observed`, `x402_payment_verified_observed`, `x402_resource_unlocked_observed`, `x402_settlement_confirmed_observed` |
| `ConversionProjector` | `checkout_completed`, `lead_created`, `opportunity_closed_won`, `payment_confirmed`, `reward_redeemed`, `x402_settled` |

## Families with no projector

| Family | Status | Target tables | Reason |
|---|---|---|---|
| `consent` | no_projection | — | Consent is control-plane state owned by the consent authority, not a Silver analytics fact. |
| `credit` | pending | `credit_signal_facts` | Registry declares silverProjection=credit_signal_facts; no dispatcher projector exists yet. |
| `identity` | pending | `identity_evidence_facts` | The bare identify call is not routed; identity evidence is currently projected from identity_lc lifecycle events only. |
| `interaction` | pending_pr2 | `feature_transition_facts`, `product_interaction_facts`, `surface_interval_facts` | The interaction family currently has NO projector; its silverProjection targets land with the PR 2 interaction plane. |
| `location` | pending | `location_observation_facts` | Registry declares silverProjection=location_observation_facts; no dispatcher projector exists yet. |
| `x402` | pending | `x402_flow_facts` | X402FlowProjector handles legacy *_observed event types that are not in the event registry; the registry's x402 family types are not yet routed by the dispatcher. |

## Out-of-band stages

- `SilverGraphProjector` (graph_emission): Fire-and-forget Silver->graph mutation emission invoked by the dispatcher after each successful fact projection; evidence-backed (provenance_class=silver, source_event_id required) and never a canonical-activity owner.
