---
title: Demo Walkthrough
slug: tutorials/demo-walkthrough
section: tutorials
visibility: I
audience: [exec, buyer, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Demo Walkthrough

A guided path through the Demo App ([Demo App](DEMO-APP.md)). Start with
an explicitly backend-seeded demo tenant, then run
`npm run dev --workspace=@aether/demo` → http://localhost:5177.

1. **Ingestion (SDK or no SDK).** Show both paths side by side: SDK (Web/iOS/
   Android) and no-SDK (Shopify connector, Stripe signed webhook, HubSpot). Click
   **Send SDK event** / **Send webhook event** to show real backend ingestion.
   *Message: "You don't need to wait for an SDK rollout — connect existing tools."*
2. **Graph & Profile360.** One person resolved across email, web, wallet,
   Shopify, and HubSpot. *Message: "Aether unifies identities into one graph."*
3. **Recommendations.** Recommendation families propose governed plays with
   confidence. *Message: "The graph produces decisions, not just dashboards."*
4. **OODA loop.** Observe → Orient → Decide → Act → Learn.
5. **Decisions, actions & dispatch.** Approved decisions dispatch to Slack /
   webhook / CRM with delivery receipts.
6. **Outcomes & ledger.** Observed outcomes with value and confidence deltas.
7. **Playbooks & ROI.** Repeatable plays with measured value.
8. **Value review & data quality.** Total value created + intelligence-quality
   score.
9. **Operator (Kyber) view.** Toggle to the operator rollup of the same tenant —
   health, expansion, renewal risk, value, intelligence quality (aggregate-only).

See [Demo Sales Script](DEMO-SALES-SCRIPT.md) for the narrative version.
