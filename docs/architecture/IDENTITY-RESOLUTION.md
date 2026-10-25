---
title: Identity Resolution
slug: concepts/identity-resolution
section: concepts
visibility: P
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
source_files:
  - services/api/identity/identity/
  - services/api/ingestion/ingestion/batch.py
  - services/api/workers/runtime/consumer_specs.py
  - services/api/repositories/repos.py
  - services/api/intelligence/analytics/routes.py
  - services/api/identity/profile/composer.py
  - services/api/identity/profile/aggregator.py
  - services/api/actions/agent/deployment_routes.py
  - services/api/actions/agent_marketplace/identity_binding.py
  - services/api/actions/agent_marketplace/authority.py
  - services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py
  - packages/shared/identity.ts
canonical_owner: identity@aether
estimated_read_minutes: 12
toc_depth: 3
reviewed_source_commits:
  - commit: "fcfe08b7b"
    reason: "Reviewed the SDK batch envelope refactor and V2 parity. The helper preserves the existing authenticated identity namespace stamp and only adds the optional flag-gated observation envelope; identity resolution behavior is unchanged."
  - commit: "5da9690b0"
    reason: "Reviewed request-to-usage correlation in the batch handler. The request ID becomes metering correlation metadata and actual usage references are returned; source namespace, canonical identity, and resolution decisions are unchanged."
  - commit: "40af67902"
    reason: "Reviewed the accepted-observation consent receipt correlation addition. The batch response and audit metadata now retain real receipt IDs; source namespace, canonical identity, and resolution decisions are unchanged."
source_hashes:
  "packages/shared/identity.ts": "sha256:574974d03d8c4f8b99ad414c7b738b675cc293723f764e2ca3b76dc2ca40d8a2"
  "services/api/actions/agent/deployment_routes.py": "sha256:46ace5ea27e1c0a95bb62b7d63cd9c53f383f0ae759e30c795914f41e5e2a8b4"
  "services/api/actions/agent_marketplace/authority.py": "sha256:b136984919ab302e7140815f5984f4cfad11494c3a591853af33d4c741a88b29"
  "services/api/actions/agent_marketplace/identity_binding.py": "sha256:0508f1094a8d369cd6c02004a18456c4b21b3b15f7160742d0ba6c9155aae352"
  "services/api/alembic/versions/20261011_agent_deployment_identity_bindings.py": "sha256:ab8553556c2c9d6e0e46fe55899132946dcfef9c432b8aed72d394da8e5a3269"
  "services/api/identity/identity/": "sha256:02607b0fff37bba1e4fca57ca429312ec26631451fd125c2b9bfeef93e027425"
  "services/api/identity/profile/aggregator.py": "sha256:228b48e5b06d6f4355c1d5fda2363ef5e3265570e750863bd7fd98941a41109f"
  "services/api/identity/profile/composer.py": "sha256:aae09f67a164f0e2b940676e52841ff325f36650ac4b1c022cc2a60a31505c20"
  "services/api/ingestion/ingestion/batch.py": "sha256:c1fddf5e0e2d31384b586ef0f4e73429f397c9351d35e8d6a12fdedd94896955"
  "services/api/intelligence/analytics/routes.py": "sha256:b51cb890d703eb9c495b723fd79b6e03bf292300db82441024b5b645e6b341b7"
  "services/api/repositories/repos.py": "sha256:97da54692debeff715bd1129e264e4fc0b8801abeda5c52b288c96094e04a605"
  "services/api/workers/runtime/consumer_specs.py": "sha256:c78159537971b6e5eeb0ef86cd982118f47f34f82349e86f5f4536872137c5d5"
---
# Aether Identity Resolution v0.1.0-alpha.0 — Technical Guide

## Overview

Aether's Identity Resolution system unifies user profiles across devices, browsers, wallets, and sessions into a single **Identity Cluster**. It uses a hybrid approach: **deterministic signals** (exact identifier matches) can auto-merge when rollout policy allows, while **probabilistic signals** (fingerprint similarity, IP clustering, behavioral patterns) flag candidate merges for review. Resolution is disabled by default (`IDENTITY_RESOLUTION_ENABLED=false`); auto-merge and manual review are separately gated and also default off. Identity-link consent is required before identifiers are resolved.

> **Staging/production default:** strong (probabilistic) auto-linking is **off by default** in `staging`/`production` — only deterministic signals auto-merge; strong matches go to candidate/conflict review. Set `AETHER_IDENTITY_STRONG_AUTOLINK=1` to re-enable strong auto-link under explicit tenant policy. Fingerprint-only and cross-tenant matches never auto-link in any environment.

## Architecture

The production implementation lives in `services/api/identity/identity/` — `resolver.py` orchestrates a 15-step pipeline via `IdentityResolutionService`, backed by 9 specialized repository classes (`repository.py`), HMAC-SHA256 PII hashing (`hashing.py`), merge/split policy engines (`merge_policy.py`, `split_policy.py`), a conflict manager (`conflicts.py`), an audit writer (`audit.py`), and a graph writer (`graph_writer.py`). Confidence scoring uses a 5-tier model (BLOCKED → NONE → LOW → MEDIUM → HIGH → DETERMINISTIC) in `confidence.py`.

**Persistence.** Alembic migrations create the identity tables with named
columns, not the generic `data` JSONB column. The migrations are
`20260612_identity_resolution_tables`, `20260619_identity_suppression` and
`20260715_identity_merge_correctness`. The stores in `repository.py` therefore
run `BaseRepository` in explicit-column mode (`_jsonb_mode = False`):

- Record keys bind to their migrated columns.
- Keys with no column are kept in the table's `payload` JSONB, or in `data` for
  `identity_suppression_rules`. Examples are `source_platform`, `context`,
  `cluster_version` and a split's `fragment`.
- A few historical record keys map to differently named columns: `alias_value_hash` →
  `alias_hash`, `signal_value_hash` → `signal_hash`, a cluster's `status` →
  `cluster_status`, and an edge's `source_entity_id`/`target_entity_id` →
  `from_entity_id`/`to_entity_id`.

Reads return the same flat record shape. Signal observations are written before the event resolves to an entity, so
`identity_signal_observations.canonical_entity_id` is nullable
(`20260924_identity_observation_entity_nullable`) until the resolver links it.
`source_identities` and `identity_claims` have no migration and stay on the
runtime-created JSONB store.

The graph writer's graph mirror routes through the canonical **Graph Mutation Gateway** (`shared/graph/mutation_gateway.py`): merge edges are expressed as `identity_merged` mutations (other identity edges as `edge_created`, split revokes as `identity_split`), each carrying the decision's reason codes, source-event evidence, and confidence as ledger metadata. At `AETHER_MUTATION_GATEWAY_MODE=off` the gateway delegates straight to the GraphClient (pre-gateway behavior); in `shadow`/`enforce` modes every mirror write is also recorded in the append-only `graph_mutation_ledger`. Repo-backed identity edges remain the source of truth — mirror failures stay non-fatal.

SDK identity resolution is owned by the `identity-worker` consumer on
`SDK_EVENTS_VALIDATED`. The V1 batch path writes Bronze and publishes the
validated event; V2 writes Bronze plus its outbox row transactionally and the
relay publishes it. The worker registers a source identity before invoking the
resolver, and retries use stable tenant/event/policy identities. It publishes
`IDENTITY_RESOLVED` only after an accepted canonical decision.

### Identity360 read boundary

The product-facing Identity360 provider
(`services/api/identity/identity/identity360_provider.py`) is a bounded,
read-only view over the entity registry and canonical identity repositories.
It accepts exact tenant-owned entity, agent, or source-identity IDs; it does
not resolve arbitrary identifiers, expose raw identifier values or hashes,
evaluate identity, or write graph state. Repository results are rechecked
against tenant and requested-subject scope. Missing or incomplete joins remain
unknown, degraded, or truncated, so Identity360 does not replace the resolver
or turn an absent read into a negative identity decision.

When the `wallets` slot is requested, Identity360 reads bounded, exact
tenant/entity links from the canonical `entity_wallets` registry and separately
joins `wallet_ownership_verified` evidence for that same entity. A recorded
link establishes an association, while verification proves control only at its
recorded time; neither establishes current control or complete wallet
ownership. The response distinguishes linked wallets from historical proofs,
reports read coverage and truncation, and exposes opaque evidence references
without wallet addresses, wallet identifiers, or identifier hashes. No rows in
these authorities leaves wallet presence unknown rather than empty.

The `devices_sessions` slot exposes identifier-type metadata only
(`device_id`, `installation_id`, or `session_id`) from exact tenant-scoped
source-identity records, with an evidence reference for each observation.
Raw identifier values and hashes are omitted. This is not a device or session
inventory: inventory completeness and freshness remain unknown until dedicated
device/session authorities are joined.

The current `identifier_inventory`, `namespace_map`, and `aliases` paths also
require record-level evidence before returning a row. For `namespace_map`, the
provider takes the exact `source_system_id` already stored on a tenant- and
evidence-validated source identity and looks up that exact key in the loaded
provider runtime registry. It does not infer a provider from a namespace
prefix or connection. Returned provider metadata is allowlisted; missing keys
remain unknown, and the slot stays partial because the provider registry has
no freshness watermark. Missing or conflicting identity rows remain unknown
or degraded, not evidence that an identifier or alias does not exist.

The batch backend stamps `context.identity_namespace` from the authenticated
site binding. The SDK cannot select its own namespace. This lets profile and
analytics reads ask for a canonical entity and resolve its event IDs through
signal observations and merge lineage, so anonymous activity remains visible
after a later identity bind.

### Source identities and late binding

`SourceIdentityRegistry` records external identifiers before they are resolved
to canonical entities. Registration is tenant- and `source_namespace`-scoped:
repeated IDs within one namespace are idempotent, while equal raw IDs from a
CSV upload, connector, or SDK in different namespaces remain distinct source
identities. Candidate comparison is also tenant-scoped and follows the
eligibility, freshness, and consent checks for its source; a shared claim alone
does not authorize a link or merge. This lets historical imports precede SDK
installation without making a CSV row ID or provider ID canonical identity.
SDK `identify` observations add evidence and are resolved by the backend; SDKs
do not assign canonical entities.

Provider sync and webhook ingestion can add customer evidence after a raw
provider record has been durably accepted. Provider-specific extractors select
customer fields; order, receipt, seller, and store identifiers are not treated
as person identifiers. Connector identities use a tenant-scoped namespace
containing the provider, account, and connection, so the same provider ID from
different accounts or connections remains distinct. Email and phone claims are
normalized and persisted as tenant-scoped HMAC hashes; provider customer IDs
remain source-scoped identifiers and are not canonical entity IDs.

Each connector claim is tied to the accepted raw record's checksum and schema
version and to its owning sync-run or verified-webhook lifecycle. The evidence
stays pending until that durable lifecycle completes, and candidate lookup
rechecks the current lifecycle anchor and raw fingerprint. SDK late-binding
and connector evidence are both disabled by default
(`SDK_LATE_BINDING_ENABLED=false` and
`CONNECTOR_BACKFILL_IDENTITY_RESOLUTION_ENABLED=false`). When both are enabled,
connector evidence may be considered through the tenant-scoped late-binding
flow; a claim match does not merge profiles by itself, and approval revalidates
the evidence and requires server-verified identity-link consent.

`merge_policy.py` additionally enforces a **non-merge-eligible signal denylist** (`NON_MERGE_ELIGIBLE_SIGNAL_NAMES`): `deployment_id`, `agent_id`, `external_platform`, `external_channel_id`, and `external_workspace_id` are filtered out before merge scoring, so external agent deployment/platform telemetry can never contribute to an identity merge on its own. Exclusions are recorded with reason code `non_merge_eligible_signal_excluded`.

External agent deployment identity uses a separate explicit binding authority.
A tenant administrator may bind `(tenant_id, source_namespace, source_agent_ref)`
to an existing canonical Agent in that same tenant. The binding is durable and records the acting tenant administrator and
binding time; resolution checks that the binding still matches the deployment's
namespace/reference and canonical entity. Missing, ambiguous, stale, or
cross-tenant bindings remain unresolved. This does not alter the identity
resolver's automatic merge policy: `agent_id` and deployment/platform signals
remain excluded from merge scoring, and a binding is not merge evidence.

```
SDK event
    |
    v
POST /v1/batch
    |-- validate, consent and privacy gates
    |-- V1: persist Bronze, then publish SDK_EVENTS_VALIDATED
    |-- V2: commit Bronze + event_outbox together; relay publishes later
    |
    v
identity-worker consumes SDK_EVENTS_VALIDATED
    |-- stamp/consume the server-authenticated app namespace
    |-- register source identity and observed claims
    |-- run IdentityResolutionService
    |-- record canonical ownership on the source identity
    |-- publish IDENTITY_RESOLVED only after an actual decision
    |
    +-- CREATE / LINK / MERGE → canonical entity and graph policy
    +-- ambiguous evidence → candidate/conflict review
    +-- insufficient evidence → source-scoped provisional identity
```

V1 and V2 now share the same asynchronous consumer. V1 no longer starts a
process-local resolver task from the request handler. At-least-once delivery
uses the source event ID for idempotent source registration, signal observations,
and provisional entity IDs. The raw Bronze event remains unchanged. An
identity-bearing anonymous page or heartbeat can create a provisional entity;
conversion is not required. Later evidence can resolve that same source history
to a known canonical entity.

The SDK batch path stamps `context.identity_namespace` from the authenticated
`X-Aether-Site` binding. Caller-provided identity namespace values are ignored.
Tenant-wide secret credentials use a tenant-local namespace. This keeps equal
SDK user IDs from separately bound sites from being treated as the same app
identity by default.

## Identity Graph Schema

### Vertex Types

| Vertex | Description | Key Properties |
|---|---|---|
| `User` | A user profile (anonymous or identified) | `anonymous_id`, `user_id`, `traits`, `tenant_id` |
| `DeviceFingerprint` | Unique browser/device identifier | `fingerprint_id` (SHA-256), `canvas_hash`, `webgl_renderer`, `audio_hash`, `screen_resolution`, `timezone`, `language`, `platform` |
| `IPAddress` | Network endpoint | `ip_hash` (SHA-256), `ip_range`, `asn`, `isp`, `is_vpn`, `is_proxy`, `is_tor` |
| `Location` | Geographic position | `country_code`, `region`, `city`, `latitude`, `longitude`, `timezone` |
| `Email` | Email address (hashed) | `email_hash` (SHA-256), `domain`, `is_disposable` |
| `Phone` | Phone number (hashed) | `phone_hash` (SHA-256 of E.164), `country_code` |
| `Wallet` | Blockchain wallet | `address`, `vm`, `chain_ids[]`, `ens`, `classification` |
| `IdentityCluster` | Merged identity group | `cluster_id`, `canonical_user_id`, `confidence`, `member_count`, `resolution_status` |

Wallet identity signals retain their VM family and, when supplied, concrete
chain reference from `vm` and `chainId` (for example, `eip155:1` or
`solana:mainnet`). The resolver includes both in the hash scope, normalizes
known address formats, and preserves case-sensitive encodings such as Solana,
Bitcoin Base58, and Substrate SS58. When only the VM is known, hashes are scoped
to that family; when neither field is present, the legacy EVM namespace is
used. Accepted wallet addresses remain observations unless a server-owned
verification flow supplies stronger evidence. A wallet connection is an observation
and does not prove ownership, custody, or key control. Historical wallet hashes
are not rewritten by this change; reconcile retained source events before
linking legacy non-EVM aliases.

The compatibility request field `wallet_signature_verified` is deprecated and
ignored, as are per-wallet client `verified` and `signature_verified` flags.
The compatibility identity route can emit only an observed wallet-address
signal from those claims; a client cannot promote it to cryptographic proof or
change its trust class. Wallet control is established through the server-issued
`POST /v1/identity/verification/wallet/challenges` and
`POST /v1/identity/verification/wallet/challenges/{challenge_id}/verify`
flow. Both calls require current server-evaluated identity-link consent for the
same anonymous subject. The five-minute message binds tenant, subject, wallet,
chain namespace, nonce and expiry. EVM `eip155:*` signatures use EIP-191
`personal_sign`; Solana signatures verify Ed25519 over the exact UTF-8 message.
Verified evidence replays through the existing resolver with the exact
consented anonymous subject and chain-scoped wallet hash, while honoring wallet
suppression and contradictory deterministic identifiers. A signature proves
key control for this challenge; it does not prove exclusive ownership, custody,
or payment authorization. Sui transaction execution evidence remains separate,
and Sui wallet-signature formats are not accepted by this flow.

The optional `tenant_app_key` request field selects a registered SDK site for a
tenant-wide secret credential; the site must belong to the tenant and be
active. Site-bound credentials may select only an already-bound site. Wallet
proofs use the same `site:<site_id>` identity namespace as SDK batch ingestion,
or `tenant:<tenant_id>` when a tenant-wide credential supplies no site. Durable
evidence encrypts the replay subject with versioned key IDs and supports an
active/previous key overlap. `POST /v1/identity/evidence/{evidence_id}/replay`
returns a cached completed result for legacy evidence without a subject only
when the summary has no `internal_error` reason; otherwise it requires a fresh
proof rather than inferring identity. Resolver `internal_error` outcomes leave
replay jobs failed and retryable when replay inputs can be recovered. Legacy
completed jobs recording `internal_error` are not considered successful cache
entries.
Replay claims use a renewable lease and fencing token: a crashed or cancelled
worker's stale claim can be reclaimed, while the prior owner cannot overwrite
the successor's result. Issuance, retry, revocation, and proof-derived alias
cleanup are serialized per tenant and identifier. Revoking or expiring evidence
removes its verified alias only after no unexpired active proof remains for
that identifier. Revoked evidence is never replayed as affirmative
verification. A subsequent fresh proof may establish a new verified alias,
while a revoked observed alias or suppression still vetoes linking. Reversing
an earlier entity merge requires the explicit identity split workflow. If
alias cleanup fails, the revoke or expiry path reports failure and can be
retried; it does not report cleanup complete while the alias remains active.

### Edge Types

| Edge | Direction | Purpose |
|---|---|---|
| `HAS_FINGERPRINT` | User -> DeviceFingerprint | Device ownership |
| `SEEN_FROM_IP` | User -> IPAddress | Network observation |
| `LOCATED_IN` | User -> Location | Geographic association |
| `HAS_EMAIL` | User -> Email | Email ownership (deterministic) |
| `HAS_PHONE` | User -> Phone | Phone ownership (deterministic) |
| `OWNS_WALLET` | User -> Wallet | Verified wallet key control (deterministic; a connection is only an observation) |
| `MEMBER_OF_CLUSTER` | User -> IdentityCluster | Cluster membership |
| `SIMILAR_TO` | User -> User | Probabilistic similarity link |
| `IP_MAPS_TO` | IPAddress -> Location | Geolocation mapping |
| `RESOLVED_AS` | User -> User | Identity merge (audit trail) |

## Resolution Signals

### Deterministic Signals (Auto-Merge)

These produce `confidence = 1.0` and trigger immediate merging:

| Signal | Match Logic | Example |
|---|---|---|
| **UserIdSignal** | Same `userId` across profiles | User logs in on phone and laptop |
| **VerifiedEmailSignal** | Same email with **verified ownership** (`email_ownership_verified`) | Mailbox control proven via OTP / magic link / trusted OIDC |
| **PhoneSignal** | Same E.164 phone hash | Same phone number registered from web and app |
| **WalletSignatureSignal** | Same wallet address with verified signature | Cryptographic key-control proof |
| **OAuthSignal** | Same OAuth provider + subject | Google login on desktop and mobile |

**Email normalization**: lowercase, trim whitespace, remove dots from Gmail local part (j.doe@gmail.com = jdoe@gmail.com), remove plus aliases (user+tag@domain.com = user@domain.com).

> **Observed vs. verified email.** A merely *observed* `email_hash` (asserted in event traits) is **strong** evidence, not deterministic — it does not prove the subject controls the mailbox, and does not auto-merge in staging/production. Only **verified email ownership** (`email_ownership_verified`, established by the backend verification layer — OTP, scanner-safe magic link, or a server-validated OIDC `email_verified` claim) is deterministic. Verified email still requires identity-linking consent, respects identifier suppression, and opens a conflict rather than merging when candidates carry contradictory deterministic identifiers. A client-supplied `email_verified` flag is never trusted.

**Phone normalization**: E.164 format (+1234567890), strip spaces/dashes/parens.

### Anonymous → known binding (identify)

An event that carries a `userId` **together with** its `anonymousId` (the SDK
`identify` call, and every event the SDK sends after it) is the SDK asserting
that this anonymous visitor *is* that user. The resolver treats that
co-occurrence as **deterministic** evidence (`authenticated_user_binding`
reason code). When the relevant resolution and auto-merge rollout flags and
server-authoritative consent permit it, the anonymous profile and user's
profile can merge at the `DETERMINISTIC` tier, collapsing every compatible
candidate into the oldest surviving entity. With auto-merge off, the result is
a review candidate when manual review is enabled, or blocked. The binding
applies only when:

- the event carries exactly one `userId` and its `anonymousId` matched an
  existing profile;
- every candidate profile was reached through that `userId` or `anonymousId`
  (not through a session, email, or device match); and
- no candidate — including fragments already merged into it — holds a
  **different** `userId`, `external_id`, or verified wallet.

When a different tenant/app-scoped `userId` is presented with only a shared
device, browser, installation, session, or anonymous signal, the resolver
creates a separate profile and does not attach the shared signal as an alias.
This prevents a fingerprint or shared device from joining the people. If the
event binds an `anonymousId` already associated with a different `userId`, it
never merges: it resolves to its own profile and opens a
`conflicting_user_binding` conflict for review. A plain returning
anonymous visitor (same `anonymousId`, no `userId`) stays `PROBABLE` →
`CANDIDATE`, and a session-only match stays `WEAK` → `REJECT`
(`insufficient_evidence`): probabilistic evidence still needs corroboration.
Matches follow merge tombstones, so an alias left on a merged fragment resolves
to the surviving profile.

**First sighting.** A consented, tenant/app-scoped `userId` can anchor a new
profile when there are no existing candidates. That narrow fallback links
deterministic user, external, and anonymous identifiers; it does not turn a
device fingerprint, observed email/phone, or wallet into a profile alias just
because the profile was created. Other first sightings follow the regular
policy and consent checks.

**Consent.** Identity-stitching consent (`analytics`, `identity`, or
`marketing`) is read from both snapshot shapes: the nested
`{"purposes": {...}}` form and the flat SDK `ConsentState` every event carries
in `context.consent` (`{"analytics": true, ...}`). Consent-gated identifiers
(email/phone hash, installation/browser id, fingerprint) are neither scored nor
stored as aliases without it.
The direct `POST /v1/identity/resolve` route requires a server-side identity-link
consent receipt for the authenticated tenant and request `anonymous_id`; a
caller-supplied `consent_snapshot` is not authorization. Missing receipts or
consent lookup failures return a blocked decision.

**Where identifiers are read from.** `userId`, `anonymousId`, `sessionId` from
the event; email/phone from `properties`, `properties.traits` (the web SDK
identify), or `context.traits`; installation id from `properties`,
`context.installationId`, or `context.device.id` / `context.device.installationId`.

### Probabilistic Signals (Scored)

These produce variable confidence (0.0-1.0) and are combined using weighted composite scoring:

| Signal | Weight | Scoring |
|---|---|---|
| **FingerprintSimilarity** | 0.35 | Canvas hash (30%), WebGL (25%), audio (15%), screen (5%), timezone+lang (10%), platform (5%), hardware (5%), fonts (5%) |
| **NetworkGraphProximity** | 0.20 | Jaccard similarity on shared graph neighbors |
| **IPCluster** | 0.15 | Same IP = 0.8, same /24 = 0.4, same ASN = 0.15, VPN discount |
| **BehavioralSimilarity** | 0.15 | Cosine similarity on feature vectors (session timing, page frequency, event mix) |
| **LocationProximity** | 0.15 | Same city = 0.6, same region = 0.3, same country = 0.1 |

**Composite score** = `sum(signal_confidence * weight) / sum(weights)`

## Device Fingerprinting

### Web SDK

The `DeviceFingerprintCollector` in `packages/sdk/web/src/core/fingerprint.ts` generates a SHA-256 hash from 17 browser signals:

| Signal | Uniqueness | Collection Method |
|---|---|---|
| Canvas rendering | High | Draw test pattern, hash `toDataURL()` |
| WebGL renderer | High | `WEBGL_debug_renderer_info` extension |
| WebGL vendor | Medium | Same extension |
| Audio context | High | `OfflineAudioContext` oscillator hash |
| Font detection | Medium-High | Canvas width measurement for 24 fonts |
| Screen resolution | Low | `screen.width x screen.height` |
| Color depth | Low | `screen.colorDepth` |
| Timezone | Low | `Intl.DateTimeFormat` |
| Language | Low | `navigator.language` |
| Platform | Low | `navigator.platform` |
| Hardware concurrency | Low-Medium | `navigator.hardwareConcurrency` |
| Device memory | Low-Medium | `navigator.deviceMemory` |
| Touch support | Low | `navigator.maxTouchPoints` |

**Privacy**: Only the composite SHA-256 hash leaves the browser. Raw signals are never transmitted. On the backend, PII fields (email, phone, IP) are stored as HMAC-SHA256 hashes (`services/api/identity/identity/hashing.py`) — raw values are never persisted in the graph or audit trail. Fingerprinting is skipped when GDPR mode is active and analytics consent is not granted. Cached in localStorage for 7 days.

### iOS SDK

Fingerprint from: `identifierForVendor`, device model, system version, screen dimensions, scale, locale, timezone, processor count, physical memory. SHA-256 via CryptoKit.

### Android SDK

Fingerprint from: `ANDROID_ID`, `Build.MODEL`, `Build.MANUFACTURER`, OS version, display metrics, locale, timezone, available processors. SHA-256 via `MessageDigest`.

### React Native

Delegates to native module: `NativeModules.AetherNative.getFingerprint()`.

## Decision Thresholds

| Threshold | Default | Action |
|---|---|---|
| Auto-merge | 0.95 | Merge profiles immediately (requires deterministic by default) |
| Review | 0.70 | Flag for admin review |
| Reject | < 0.70 | No merge, record as evaluated |

### Configuration

```json
{
  "auto_merge_threshold": 0.95,
  "review_threshold": 0.70,
  "max_cluster_size": 50,
  "cooldown_hours": 24,
  "require_deterministic_for_auto": true,
  "allow_probabilistic_auto_merge": false
}
```

The legacy `PUT /v1/resolution/config` route was removed with the unregistered resolution engine; these thresholds are not tenant-configurable through the API.

## API Endpoints

Production routes are served under `/v1/identity/` by `services/api/identity/identity/routes.py`. Legacy profile routes are backwards-compatible.

| Endpoint | Method | Description |
|---|---|---|
| `/v1/identity/resolve` | POST | Resolve identity from event payload + signals (15-step pipeline via `IdentityResolutionService`) |
| `/v1/identity/entities/{entity_id}` | GET | Get canonical entity (`read`) |
| `/v1/identity/entities/{entity_id}/aliases` | GET | Entity aliases (redacted PII) (`read`) |
| `/v1/identity/entities/{entity_id}/graph` | GET | Identity graph neighborhood (`read`) |
| `/v1/identity/entities/{entity_id}/audit` | GET | Audit / history for entity (`read`) |
| `/v1/identity/conflicts` | GET | Conflict / candidate queue (`read`) |
| `/v1/identity/merge` | POST | Operator merge (requires operator scope) |
| `/v1/identity/split` | POST | Operator split / rollback |
| `/v1/identity/split/preview` | POST | Non-mutating fragment-split impact analysis: aliases to reassign, observations to relink, edges to revoke, risk notes; blocked splits return `allowed:false` + a typed `rejection_reason` (`read`) |
| `/v1/identity/split/execute` | POST | Execute a fragment split — `create_new_entity` / `restore_pre_merge_entity` / `move_to_existing_entity` — lineage-preserving alias reassignment + observation relink + SAME_AS edge revoke, audited via the append-only split event; publishes `IDENTITY_SPLIT` so measurement re-derives journeys/attribution for both entities (`write`) |
| `/v1/identity/reconciliation` | GET | Repository↔graph identity-edge drift for the tenant (`missing_in_graph` / `missing_in_repo`); `?refresh=true` forces a fresh check, else returns the latest persisted run (`read`) |
| `/v1/admin/kyber/identity/reconciliation` | POST | Kyber-operator trigger to run edge reconciliation for a given `tenant_id` (`require_kyber_operator`) |
| `/v1/identity/recompute` | POST | Recompute identity from stored signals |
| `/v1/identity/health` | GET | Resolver health in the standard envelope (`IdentityHealthEnvelope`). `data.status` is `healthy` when the repository answers and the tenant counts read back, otherwise `degraded`. The counts are total entities/aliases/clusters, open conflicts and recent merges/splits. |
| `/v1/identity/suppress` | POST | Suppress an identifier hash — revokes matching aliases + blocks future resolution (`write` permission) |
| `/v1/identity/suppress/{suppression_id}` | DELETE | Revoke a suppression rule (`write` permission) |
| `/v1/identity/suppressions` | GET | List active suppression rules for tenant |
| `/v1/identity/profiles/{user_id}` | GET/PUT | Legacy profile read/write (backwards-compatible; `read` / `write` permission). Profiles are stored per tenant (row id `{tenant}:{user_id}`, user vertex `{tenant}:user:{user_id}`), so two tenants can each keep a profile for the same SDK user id; a read answers 404 when the caller's tenant has none |
| `/v1/identity/profiles/{user_id}/graph` | GET | Legacy profile graph (backwards-compatible): 404 for another tenant's profile, and only neighbours tagged with the caller's tenant |
| `/v1/identity/siwx/bind` | POST | SIWX session binding |
| `/v1/identity/siwx/status/{session_id}` | GET | SIWX session status |
| `/v1/identity/siwx/{session_id}` | DELETE | Revoke SIWX session |

### Example: Resolve Identity

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  -X POST https://api.aether.io/v1/identity/resolve \
  -d '{"entity_id": "user-123", "signals": {...}}'
```

**Response:**
```json
{
  "cluster_id": "clust-abc",
  "canonical_user_id": "user-123",
  "confidence": 1.0,
  "member_count": 3,
  "resolution_status": "auto_merged",
  "members": [
    { "user_id": "user-123", "role": "primary", "joined_at": "2026-01-15T..." },
    { "user_id": "anon-456", "role": "merged", "joined_at": "2026-02-01T..." },
    { "user_id": "anon-789", "role": "merged", "joined_at": "2026-03-01T..." }
  ],
  "linked_devices": [
    { "fingerprint_id": "a1b2c3...", "first_seen": "2026-01-15T...", "observations": 47 },
    { "fingerprint_id": "d4e5f6...", "first_seen": "2026-02-01T...", "observations": 23 }
  ],
  "linked_ips": [
    { "ip_hash": "abc123...", "ip_range": "192.168.1.0/24", "observations": 120 }
  ],
  "linked_wallets": [
    { "address": "0x1234...abcd", "vm": "evm", "ens": "user.eth" },
    { "address": "7nY4...Kx3p", "vm": "svm" }
  ],
  "linked_emails": [
    { "email_hash": "def456...", "domain": "gmail.com" }
  ]
}
```

## Safety Mechanisms

| Mechanism | Description |
|---|---|
| **Max cluster size** | Refuse merge if resulting cluster exceeds 50 profiles (configurable). Prevents cascading merges in NAT/VPN scenarios. |
| **Cooldown** | Don't re-evaluate rejected pairs for 24 hours. |
| **Fraud gate** | If either profile has fraud score > 40, route to manual review regardless of identity confidence. |
| **Undo capability** | `RESOLVED_AS` edges store full signal snapshots. Merges can be reversed by restoring the secondary profile and reassigning graph edges. |
| **Privacy** | All PII (email, phone, IP) stored as HMAC-SHA256 hashes only (`services/api/identity/identity/hashing.py`). Raw values never persisted in graph or audit trail. |

## Audit Trail

Every resolution decision is recorded in TimescaleDB with:
- Decision ID, profile pair, action taken
- Composite confidence score
- Whether deterministic match was found
- Full signal snapshot (all signal results at decision time)
- Timestamp and who decided (system or admin)

Query via: `GET /v1/identity/entities/{entity_id}/audit` (the legacy `GET /v1/resolution/audit/{decision_id}` route was removed).

## Event Topics

| Topic | When Emitted |
|---|---|
| `aether.resolution.evaluated` | Every time a candidate pair is evaluated |
| `aether.resolution.auto_merged` | When an auto-merge is executed |
| `aether.resolution.flagged` | When a pair is flagged for review |
| `aether.resolution.approved` | When an admin approves a merge |
| `aether.resolution.rejected` | When an admin rejects a merge |
| `aether.identity.fingerprint.observed` | When a fingerprint vertex is created/updated |
| `aether.identity.ip.observed` | When an IP vertex is created/updated |

## SDK Integration

### Sending Identity Signals

```typescript
// Web SDK — all signals are captured automatically
aether.init({ apiKey: 'your-key' });

// Fingerprint: auto-generated and included in every event context
// IP: captured server-side from request headers
// Location: derived from IP via MaxMind GeoLite2

// To enable cross-device resolution, provide explicit identifiers:
aether.identify('user-123', {
  email: 'user@example.com',     // Deterministic cross-device link
  phone: '+14155551234',          // Deterministic cross-device link
  oauthProvider: 'google',        // OAuth-based linking
  oauthSubject: 'google-uid-xyz', // OAuth subject ID
});

// Wallet connections are automatically tracked:
// When a user connects MetaMask on desktop AND Phantom on mobile,
// the backend resolves both to the same identity cluster.
```

## Cross-device journey handoff (mobile to web)

The legacy stitcher infers a handoff from consecutive events that change
session or device type; that is an inference and stays labelled as one. A
server-owned path is available behind `JOURNEY_HANDOFF_ENABLED` (default off):

1. The source device calls `POST /sdk/journey-handoff` with its journey, session
   and anonymous ID. The server returns a single-use token (30-900 s TTL, default
   600 s). Only its SHA-256 is stored (`journey_handoffs`).
2. The destination calls `POST /sdk/journey-handoff/redeem`. Redemption is one
   atomic conditional update bound to tenant and app namespace; expired,
   already-used, wrong-scope and unknown tokens all return the same 404.
3. A redemption yields a link with `link_basis: "explicit_handoff"` and
   `identity_merge: "not_performed"`. It proves one party held both sessions at
   that moment. It does not merge identities, assert a user ID, or select a
   profile; resolution still decides that from its own evidence.

Identity-link consent is required at both ends (fail closed). The source
subject's consent is re-evaluated at redemption, because redeeming creates an
explicit link carrying its identifiers; if it has lapsed the response is the
same 404 as an unknown token and the token is left unspent (it expires on its
own). The routes are classified in `config/route_registry.yaml`, and a
site-bound publishable key may call exactly the issue and redeem POSTs (the
tenant read is not reachable with one). `GET /sdk/journey-handoff/journeys/{journey_id}`
(`read`) lists the handoffs for a journey; a token past `expires_at` that was
never redeemed is reported as `expired`. Rows hold both anonymous IDs, so they are
retained 90 days (`journey_handoff_sweep`, maintenance role, runs even when the flag is
off) and erased by anonymous ID through the `journey_handoffs` DSR component. SDK client
methods exist on web, React Native, iOS and Android (`createJourneyHandoff` /
`redeemJourneyHandoff`).

**Journey projection.** When the measurement compiler builds a journey it looks up
redeemed handoffs for the sessions involved. A step whose previous and current
session are exactly a redeemed (source, destination) pair gets
`transition_evidence.link_basis = "explicit_handoff"` (with the `handoff_id` and
`identity_merge: "not_performed"`); every other cross-device or platform-change hop
is labelled `"inferred"`. `GET /v1/journeys/{id}/transitions` returns the counts as
`link_basis`. The label appears the next time the journey is compiled; redeeming a
handoff does not itself trigger a rebuild. A failed lookup leaves hops inferred.

## Agent Identity Resolution

v8.0 extends the identity graph to autonomous AI agents and smart contracts.

**AGENT vertex** — Every registered agent receives its own `AGENT` vertex in the identity graph, connected to its owner via a `LAUNCHED_BY` edge pointing to the owner's `User` vertex. Agent identity links include:
- `owner_user_id` — the human user who deployed or owns the agent
- `model_name` — the underlying model (e.g. `gpt-4o`, `claude-opus-4-20250514`)
- `capabilities[]` — declared capability set (e.g. `['trade', 'analyze', 'deploy']`)
- `wallet` — the agent's on-chain wallet address (if applicable)

**Cross-layer resolution (H2A edges)** — Human-to-Agent (`H2A`) edges trace attribution from agent actions back to the human users who launched them. When an agent performs an on-chain action or records a decision, the resolution consumer follows the `LAUNCHED_BY` edge to attribute the activity to the owning `IdentityCluster`. This enables end-to-end auditability across the human-agent boundary.

**CONTRACT vertex** — Smart contracts deployed by agents receive a `CONTRACT` vertex linked to the deploying agent via a `DEPLOYED` edge (`AGENT → CONTRACT`). Contract vertices store `address`, `chain_id`, `bytecode_hash`, and `deployer_agent_id`, enabling full provenance from contract back to human owner through the agent layer.

**Experience 360 identity reads.** The mounted 360 frame runtime calls the
read-only `Identity360Provider` for `entity`, `agent`, and `source` subjects.
It returns resolved subject identity, source-identifier lineage, relationship
identity context, and identity evidence from tenant-scoped identity authorities.
Source identifiers remain source references until a canonical tenant binding
resolves them. Actor attribution and delegation slots are separate: an owner
field or source-reported actor ID alone does not establish who performed an
action or whether it was authorized.

## Decision evidence & source precedence

Identity resolution now emits **additive, fail-closed decision evidence** without
changing any resolution outcome:

- **IdentityDecision evidence** (`services/api/identity/identity/decision_evidence.py`) — the
  resolver records an `IdentityDecisionEvidence` row (decision type — `auto_link`,
  `candidate_link`, `merge`, `split`, `suppress`, `reject`, `conflict`, …, the
  matched signals, confidence, and a hashed consent snapshot) for each resolution.
  Recording is wrapped so a failure can never break resolution; evidence is
  tenant-scoped.
- **Source Precedence Engine** (`services/api/identity/identity/source_precedence.py`) — a
  machine-readable precedence matrix ranks conflicting sources per field
  (identity, revenue, wallet/account/payment linkage, financial value, reward
  status, attribution basis, …). When candidate sources disagree and none clears
  the field's manual-review threshold, the engine returns a **conflict record**
  (`requires_manual_review=True`) rather than silently choosing between two
  authoritative-level sources.
## Kyber reconciliation repair

Kyber operators can repair repository/graph divergence through the tenant-scoped
reconciliation repair endpoint. Requests default to `dry_run=true`, require an
operator actor and reason, and accept a caller request id for idempotency. Before
mutation, the service durably records a repair intent. Repository identity edges
are authoritative: missing graph mirrors are recreated, while graph-only edges
are revoked. Every edge returns an explicit outcome; partial failures remain
visible and retryable. The service rejects any repair input that crosses tenant
ownership boundaries.
