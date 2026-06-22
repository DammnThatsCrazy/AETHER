# Consent Model

Eight canonical purposes. Source of truth: `packages/shared/contracts/consent-registry.json`.
Generated artifacts: `packages/shared/consent.ts` (TypeScript) and
`Backend Architecture/aether-backend/services/ingestion/generated_registry.py` (Python).
Regenerate with: `python scripts/generate_contracts.py`.

| Purpose | Default | Explicit Opt-in Required | Retention | Gates |
|---|---|---|---|---|
| `analytics` | ✓ enabled | no | 90d | track, page, screen, heartbeat, error, performance, identify, journey_* |
| `marketing` | disabled | no | 180d | experiment, conversion, ad_exposed, email_*, unsubscribe_observed |
| `personalization` | disabled | no | 180d | content_impression, recommendation_exposed, recommendation_accepted/rejected (personalization fields) |
| `web3` | disabled | no | 365d | wallet, transaction, contract_action, transaction_*_observed, token_approval_observed, bridge_transfer_observed |
| `agent` | disabled | no | 90d | agent_*, agentic_* |
| `commerce` | disabled | no | 7y | payment_*, approval_*, entitlement_*, access_*, x402_*, order_*, subscription_*, invoice_*, ecommerce family |
| `credit` | disabled | **yes** | 730d | credit_signal_observed, credit_account_observed, credit_decision_observed |
| `location` | disabled | **yes** | 30d | location_observed, geofence_transition_observed |

## Rules

1. `ConsentState` has exactly these eight boolean fields plus `updatedAt` and `policyVersion`.
2. The SDK stamps `ConsentState` onto every event's `context.consent`.
3. Before transport, the SDK **drops** any event whose required purpose is `false`
   (exception: `consent` events are always allowed — `requiredPurposes: []`).
4. The backend ingestion validator re-checks via per-event `context.consent` snapshot
   (authoritative) and falls back to `BatchRequest.consents` (optional hint).
5. Changing `ConsentState` emits a `consent` event for a continuous audit trail.

## Explicit opt-in purposes

`credit` and `location` always require explicit opt-in. They are **never** granted by
an accept-all operation. The consent UI must present them separately. The
`EXPLICIT_OPT_IN_PURPOSES` constant in `consent.ts` enumerates them.

## Fingerprint gating

`personalization` purpose controls access to device fingerprinting.
On revocation: cached fingerprint must be deleted and a `consent` event emitted.
`fingerprintGated: true` is set on the `personalization` purpose in the registry.

## Defaults

All purposes default to `false` in `DEFAULT_CONSENT_STATE` (no consent at init).
The consent UI pre-checks purposes based on `defaultEnabled` in the registry
(only `analytics` is `defaultEnabled: true`).

## Native platforms

iOS, Android, and React Native accept `List<String>` / `[String]` of purpose keys.
Only the canonical eight strings are recognized; others are silently ignored.
