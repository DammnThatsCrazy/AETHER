# Consent Model

Consent is **registry-derived**. The source of truth is
`packages/shared/contracts/consent-registry.json`; the authoritative, always-current
enumeration of purposes is the generated table
[`docs/_generated/consent-registry-table.md`](../_generated/consent-registry-table.md).
Do not hardcode a purpose count in docs or validators — every layer must agree
with the registry.

Generated artifacts: `packages/shared/consent.ts` (TypeScript) and
`Backend Architecture/aether-backend/services/ingestion/generated_registry.py` (Python).
Regenerate with: `python scripts/generate_contracts.py`.

## Purpose categories

The registry groups purposes by whether they require explicit opt-in:

**Base purposes** (`explicitOptInRequired: false`) — may be granted by an accept-all
operation:

| Purpose | Default | Retention | Notes |
|---|---|---|---|
| `analytics` | ✓ enabled | 90d | Core product usage / operational analytics |
| `marketing` | disabled | 180d | Attribution, experiments, conversion, advertising |
| `personalization` | disabled | 180d | Fingerprinting + recommendations; `fingerprintGated`, `blockLocalCollection` |
| `web3` | disabled | 365d | Wallet connections, on-chain observations |
| `agent` | disabled | 90d | Agentic workflow / AI task lifecycle |
| `commerce` | disabled | 2555d | Payments, subscriptions, orders, entitlements (may be legal-held) |

**Explicit opt-in purposes** (`explicitOptInRequired: true`) — **never** granted by
accept-all; the consent UI must present each separately:

| Purpose | Retention | Notes |
|---|---|---|
| `financial_activity` | 2555d | Read-only derivatives trading analytics; suppress-on-revocation |
| `credit` | 730d | Credit signals / decisions; no backend enrichment, no graph, no training |
| `location` | 30d | Precise/coarse location + geofence; `blockLocalCollection`, delete-on-revoke |
| `economic_observability` | 2555d | Read-only stablecoin economic intelligence; suppress-on-revocation |
| `cross_chain_observability` | 2555d | Read-only interoperability intelligence; suppress-on-revocation |

The exact fields, data categories, DSR delete scope, and revocation behavior for
each purpose live in the registry and the generated table — this doc summarizes;
the registry governs.

## Rules

1. `ConsentState` has exactly one boolean field per registry purpose (keyed by the
   canonical purpose key) plus `updatedAt` and `policyVersion`.
2. The SDK stamps `ConsentState` onto every event's `context.consent`.
3. Before transport, the SDK **drops** any event whose required purpose is `false`
   (exception: `consent` events are always allowed — `requiredPurposes: []`).
4. The backend ingestion validator re-checks via per-event `context.consent` snapshot
   (authoritative) and falls back to `BatchRequest.consents` (optional hint).
5. Changing `ConsentState` emits a `consent` event for a continuous audit trail.

## Explicit opt-in purposes

Explicit opt-in purposes are enumerated by `explicitOptInRequired: true` in the
registry and by the `EXPLICIT_OPT_IN_PURPOSES` constant in `consent.ts`. They are
**never** granted by an accept-all / grant-all operation and must be presented
separately in the consent UI. Several (`financial_activity`,
`economic_observability`, `cross_chain_observability`) carry additional governance
permissions (`identityLinkingPermission`, `graphProjectionPermission`,
`modelTrainingPermission`) and a `stop_new_collection_and_suppress_projections`
revocation behavior.

## Fingerprint gating

`personalization` purpose controls access to device fingerprinting
(`fingerprintGated: true` in the registry). Fingerprint generation must not run
before `personalization` is granted. On revocation: the cached fingerprint must be
deleted, the in-memory collector reset, and a `consent` event emitted.

## Defaults

All purposes default to `false` in `DEFAULT_CONSENT_STATE` (no consent at init).
The consent UI pre-checks purposes based on `defaultEnabled` in the registry
(only `analytics` is `defaultEnabled: true`).

## Native platforms

iOS, Android, and React Native accept `List<String>` / `[String]` of purpose keys.
Only the canonical purpose keys from the registry are recognized; others are
silently ignored.
