---
title: Demo Data
slug: operations/demo-data
section: operations
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Demo Data

All Demo App data is **synthetic** and self-contained in
`frontend/demo/src/data/fixtures.ts`. No real customer data is used and no
backend is required in `local-mocked` mode.

## Synthetic dataset

- **Tenant**: `Orbit Commerce (Demo)` on plan P3.
- **Ingestion paths**: Web/iOS/Android SDK + Shopify connector + Stripe signed
  webhook + HubSpot connector.
- **Profile360**: a synthetic entity with resolved identities (email, web
  session, wallet, Shopify customer, HubSpot contact) and relationships.
- **Intelligence**: recommendation families, OODA steps, decisions, dispatches,
  outcomes, playbook ROI, value-created totals, data-quality scores, and the
  Kyber operator rollup.

## Seed / reset

The app renders directly from fixtures, so:
- `npm run demo:seed --workspace=@aether/demo` and `demo:reset` are **no-ops
  locally** (reload the app to restore fixtures).
- For a backend-backed demo (future activation), an `AETHER_DEMO_SEED_ENABLED`
  flag would gate a `services/demo` seed/reset endpoint that writes deterministic
  synthetic records into the in-memory stores. Off by default; not required.

See [Demo App](DEMO-APP.md).
