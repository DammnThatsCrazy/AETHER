---
title: Identity Resolution
slug: source-of-truth/identity-resolution
section: source-of-truth
visibility: internal
audience: [architect, dev-senior, ai]
status: stable
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/identity/models.py
  - Backend Architecture/aether-backend/services/identity/routes.py
  - Backend Architecture/aether-backend/services/identity/resolver.py
  - Backend Architecture/aether-backend/services/identity/repository.py
canonical_owner: identity@aether
last_synced_commit: 0adc1534d28d00a7aa98aaffb61c50698e8d33cb
---
# Identity Resolution

Canonical definition of the Aether identity resolution subsystem. This file is
the single source of truth for `canonical_entity_id` assignment, resolution
decision semantics, confidence tiers, reason codes, cross-tenant scoping, and
operator workflows.

---

## What is `canonical_entity_id`?

Every entity that Aether observes is assigned a stable UUID called
`canonical_entity_id`. It is:

- **Backend-owned** — the SDK never assigns or emits it; it is stamped by
  `services/identity/resolver.py` after Bronze ingestion.
- **Tenant-scoped** — two tenants observing the same user have independent,
  non-overlapping `canonical_entity_id` namespaces.
- **Stable under merge** — when two identities are merged, the surviving
  `canonical_entity_id` is preserved and the absorbed one is tombstoned
  (`status: merged`).
- **Recoverable via split** — operator-initiated splits create a new
  `canonical_entity_id` for the separated fragment and record the lineage in
  the audit log.

---

## Resolution decision model

Each resolution cycle produces a `MergeDecision`:

| Decision | Meaning |
|----------|---------|
| `create` | No existing entity found; create a new `canonical_entity_id`. |
| `link` | Confident enough to associate alias with an existing entity without full merge. |
| `merge` | Strong or deterministic evidence; merge two previously separate entities. |
| `candidate` | Evidence exists but below merge threshold; enqueued as a conflict for operator review. |
| `reject` | Evidence is contradictory or invalid; signals discarded. |
| `noop` | Signals already accounted for; no graph change needed. |
| `blocked` | Resolution explicitly halted: cross-tenant attempt, fingerprint-only, consent revoked, or suppressed entity. |

---

## Confidence tiers

Resolution evidence is scored and bucketed into confidence tiers:

| Tier | Approximate Score | Meaning |
|------|-------------------|---------|
| `deterministic` | 1.0 | Hard evidence: authenticated `user_id`, `external_id`, **verified email ownership** (`email_ownership_verified`), verified wallet signature proof. |
| `strong` | ~0.85–0.99 | Strong but not proven: an **observed** `email_hash`/`phone_hash`, same anonymous install ID, session continuity across platforms. An observed email address is strong evidence of the same identity — it is **not** proof the subject controls the mailbox. |
| `probable` | ~0.60–0.84 | Medium evidence: same campaign path, journey path, `org_id` co-occurrence. |
| `weak` | ~0.01–0.59 | Soft signals: device fingerprint, IP proximity, timing correlation. |
| `blocked` | N/A | Signal disqualified; see reason codes below. |

Fingerprint alone is never sufficient to promote a link to `probable` or
above. Cross-device linking requires at least one strong or deterministic
signal.

---

## Signal types

| Signal | Enum value | Typical tier |
|--------|-----------|--------------|
| Authenticated user ID | `user_id` | deterministic |
| Verified email ownership | `email_ownership_verified` | deterministic |
| Observed email hash | `email_hash` | strong |
| Observed phone hash | `phone_hash` | strong |
| Verified wallet signature | `wallet_signature_verified` | deterministic |
| Anonymous install ID | `anonymous_id` | strong |
| Mobile install ID | `mobile_install_id` | strong |
| Browser persistent ID | `browser_id` | strong |
| Session ID | `session_id` | probable |
| Installation ID | `installation_id` | probable |
| Campaign ID | `campaign_id` | probable |
| Journey ID | `journey_id` | probable |
| Commerce customer ID | `commerce_customer_id` | strong |
| Payment customer ID | `payment_customer_id` | strong |
| Account ID | `account_id` | strong |
| Agent ID | `agent_id` | strong |
| Org ID | `org_id` | probable |
| Device fingerprint | `device_fingerprint` | weak |
| External ID | `external_id` | strong |

---

## Reason codes

Every resolution decision is annotated with a reason code for auditability:

| Reason code | Meaning |
|-------------|---------|
| `same_user_id` | Matching authenticated user ID across signals. |
| `same_external_id` | Matching external system identifier. |
| `same_verified_wallet` | Matching wallet address with verified signature proof. |
| `same_verified_email` | Matching email with **verified ownership** proof (deterministic). |
| `verified_email_evidence` | Verified-email ownership authorised a deterministic merge of compatible fragments. |
| `conflicting_verified_identifier` | Verified ownership spans candidates carrying contradictory deterministic identifiers; routed to review. |
| `resolution_replay` | Decision produced by an asynchronous resolution replay (new evidence reconciling history). |
| `same_email_hash` | Matching hashed email across signals (observed only, not proof of control). |
| `same_phone_hash` | Matching hashed phone across signals. |
| `same_anonymous_id` | Matching anonymous install/browser ID. |
| `same_session_id` | Same session ID observed across events. |
| `same_device_install` | Same device installation fingerprint. |
| `same_campaign_path` | Entity arrived via the same campaign attribution path. |
| `same_journey_path` | Entity participated in the same journey segment. |
| `same_agent_delegation` | Agent delegation chain links two subjects. |
| `same_org_account` | Org/account membership co-occurrence. |
| `consent_allows_link` | Explicit consent present and permits this link type. |
| `consent_blocks_link` | Consent absent or revoked for this link type. |
| `cross_tenant_blocked` | Attempted cross-tenant resolution; hard block. |
| `fingerprint_only_blocked` | Only fingerprint signals present; insufficient for link. |
| `insufficient_evidence` | Combined signal weight below minimum threshold. |
| `conflicting_alias` | Alias maps to two different entities; enqueued as conflict. |
| `revoked_alias` | Alias was previously revoked; suppressed. |
| `manual_operator_merge` | Operator-initiated merge via `/v1/identity/merge`. |
| `manual_operator_split` | Operator-initiated split via `/v1/identity/split`. |
| `new_entity` | No prior entity found; fresh `canonical_entity_id` created. |

---

## Identity assurance: verification evidence

The resolver distinguishes an **observed** identifier from a **verified** one.
Observation ("this event carried `user@example.com`") is strong evidence but is
not proof the subject controls the mailbox; a client-supplied `email_verified`
flag is **never** trusted as proof and is discarded during signal extraction.
Ownership/control is established only by backend-owned verification and recorded
as durable evidence.

- **Challenges** (`identity_verification_challenges`) — short-lived OTP or
  scanner-safe magic-link proofs. High-entropy secrets are stored only as an
  HMAC digest under a key domain separate from identifier hashing; challenges
  are single-use (`issued → validated → consumed`), expiry- and attempt-bounded,
  and tenant-scoped. A magic-link `GET` only *validates* (never creates
  evidence); a subsequent explicit `POST /consume` performs the one-time
  consumption, so enterprise mail scanners cannot forge ownership.
- **Evidence** (`identity_verification_evidence`) — the durable fact produced
  when a proof succeeds (or a trusted OIDC/SSO `email_verified` claim is
  validated server-side). Evidence carries the identifier hash, method, issuer,
  assurance level, challenge/event provenance, policy version, and status
  (`active`/`revoked`/`expired`). It records *why* two identities may resolve
  together; it is revocable and never silently deleted.

Verified email ownership emits the `email_ownership_verified` signal, scored
**deterministic**. It still requires identity-linking consent, and a suppressed
email hash blocks resolution regardless of assurance level. When verified
ownership spans multiple candidate entities, the resolver merges them only if
they carry no contradictory deterministic identifier (e.g. two different
`user_id`s) — otherwise it opens a conflict for review. The surviving
`canonical_entity_id` is the **oldest** active subject (by first-seen), never the
largest or most recent.

## Resolution replay and revision

New evidence can arrive after the fact. `services/identity/resolution_replay.py`
re-runs the **existing** resolver for the affected identifier component — it is
not a second matcher and adds no scoring of its own. Replay is asynchronous,
tenant- and component-scoped, and idempotent on
`{tenant_id}:{trigger_id}:{policy_version}`, so a duplicate verification
callback can never double-merge.

Each identity topology change increments a monotonic `resolution_revision` on the
surviving subject and is carried on the `IDENTITY_MERGED` event, giving
downstream derived surfaces (Profile360, analytics, journeys, attribution,
caches) a clean signal for detecting and restating stale identity state.

---

## Entity types

| Enum value | Meaning |
|------------|---------|
| `human` | Authenticated end user. |
| `anonymous_visitor` | Pre-authentication visitor tracked by `anonymous_id`. |
| `device` | Physical or logical device fingerprint. |
| `session` | One continuous interaction window. |
| `wallet` | On-chain address (any VM/chain). |
| `agent` | Autonomous worker acting on behalf of a human or org. |
| `organization` | Business account inside a tenant. |
| `account` | General account entity (B2B seat, sub-account, etc.). |
| `campaign` | Attribution campaign entity. |
| `journey` | Multi-step user journey record. |
| `commerce_customer` | Commerce-plane customer identity. |
| `payment_customer` | Payment-rail customer identity. |

---

## Identity graph edge types

| Edge type | Semantic meaning |
|-----------|-----------------|
| `same_as` | Two entities resolved as the same physical identity (merge result). |
| `observed_as` | Entity observed under an alias (link without full merge). |
| `logged_in_as` | Human–authenticated-session binding. |
| `uses_device` | Human–device relationship. |
| `owns_wallet` | Verified wallet ownership (proof of key control). |
| `controls_wallet` | Operational wallet control without cryptographic proof. |
| `delegates_to_agent` | Human or org delegates authority to an agent. |
| `agent_acts_for` | Agent acting on behalf of a human or org. |
| `belongs_to_org` | Entity membership in an organization. |
| `came_from_campaign` | Attribution edge: entity originated from campaign. |
| `participated_in_journey` | Entity journey participation record. |
| `converted_after_touch` | Conversion attribution edge after touchpoint. |

---

## Entity lifecycle

```
                 ┌─────────────────┐
  ingestion ───► │ CREATE (active) │
                 └────────┬────────┘
                          │ strong/deterministic evidence
                          ▼
                 ┌─────────────────┐
                 │  MERGE (merged) │ ◄── absorbed entity; canonical_entity_id
                 └────────┬────────┘     redirects to surviving entity
                          │ operator split
                          ▼
                 ┌─────────────────┐
                 │  SPLIT (split)  │ ◄── new canonical_entity_id for fragment;
                 └─────────────────┘     lineage recorded in audit log
```

`SubjectStatus` values: `active`, `merged`, `split`.

Merged entities are not deleted — they are tombstoned and retain full audit
history. The `canonical_entity_id` of a merged entity resolves to the
surviving entity in all query paths.

---

## Cross-tenant scoping guarantee

Identity resolution is hard-scoped to `tenant_id`. The resolver:

1. Filters all candidate lookups by `tenant_id` before scoring.
2. Returns `blocked` with reason `cross_tenant_blocked` on any cross-tenant
   signal attempt.
3. Never emits a `canonical_entity_id` that spans two tenants.

No configuration can disable this guarantee. It is enforced at the repository
layer, not just the route layer.

---

## Consent gates

| Signal / link type | Consent required |
|-------------------|-----------------|
| Authenticated `user_id`, `email_hash`, `phone_hash` | Analytics consent |
| `wallet_signature_verified` | Web3 / analytics consent |
| Device fingerprint | Functional or analytics consent |
| Cross-device link (any) | Analytics consent (explicit) |
| Sensitive merge (PII-bearing alias) | Analytics + PII consent |
| Agent delegation link | Analytics consent |

`consent_allows_link` / `consent_blocks_link` reason codes are stamped on
every decision that involves a consent-gated signal type.

---

## API endpoints

All routes are under prefix `/v1/identity`.

### Resolution and reads

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/v1/identity/resolve` | write | Resolve identity from event signals. Accepts a list of `IdentitySignal` objects plus optional `entity_id`. Returns a `MergeDecision` and the resulting `canonical_entity_id`. |
| `GET` | `/v1/identity/entities/{entity_id}` | read | Fetch canonical entity record by `canonical_entity_id`. |
| `GET` | `/v1/identity/entities/{entity_id}/aliases` | read | List aliases attached to entity (values are redacted to hashes). |
| `GET` | `/v1/identity/entities/{entity_id}/graph` | read | Neighborhood subgraph: entity + adjacent nodes within N hops. |
| `GET` | `/v1/identity/entities/{entity_id}/audit` | read | Full merge/link/split audit log for an entity. |
| `GET` | `/v1/identity/conflicts` | read | Paginated conflict/candidate queue for operator review. |
| `GET` | `/v1/identity/health` | read | Resolver health metrics (queue depth, error rate, DB latency). |

### Operator writes

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/v1/identity/merge` | write | Operator-initiated merge of two `canonical_entity_id` values. Annotated with `manual_operator_merge` reason code. |
| `POST` | `/v1/identity/split` | write | Operator-initiated split/rollback. Creates a new `canonical_entity_id` for the separated fragment. |
| `POST` | `/v1/identity/recompute` | write | Recompute resolution for an entity by replaying its ingestion events. |
| `POST` | `/v1/identity/suppress` | write | Create a suppression rule to permanently block an identifier hash from being used in identity linking. |
| `DELETE` | `/v1/identity/suppress/{suppression_id}` | write | Revoke an active suppression rule. |
| `GET` | `/v1/identity/suppressions` | read | List active suppression rules for this tenant. |

### Email verification and evidence

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/v1/identity/verification/email/challenges` | write | Issue an email verification challenge (`otp` or `magic_link`). The raw secret is delivered out-of-band. |
| `POST` | `/v1/identity/verification/email/challenges/{challenge_id}/verify` | write | Verify an OTP code; on success produces `email_ownership_verified` evidence. |
| `GET` | `/v1/identity/verification/email/callback` | write | Scanner-safe magic-link landing — validates the token only; never consumes or creates evidence. |
| `POST` | `/v1/identity/verification/email/challenges/{challenge_id}/consume` | write | One-time consumption of a validated magic link; produces evidence. |
| `POST` | `/v1/identity/verification/oidc` | write | Validate a trusted OIDC/SSO `email_verified` claim (issuer allowlist + audience) into evidence. |
| `GET` | `/v1/identity/entities/{canonical_entity_id}/evidence` | read | List verification evidence for an entity (operator-facing, redacted). |
| `POST` | `/v1/identity/evidence/{evidence_id}/revoke` | write | Revoke verification evidence; triggers resolution replay. |

### SIWX session binding

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/identity/siwx/bind` | Bind a SIWX (Sign-In With X) session to an identity. |
| `GET` | `/v1/identity/siwx/status/{session_id}` | Query SIWX binding status. |
| `DELETE` | `/v1/identity/siwx/{session_id}` | Revoke a SIWX session binding. |

### Legacy (backwards-compatible, do not use in new integrations)

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/v1/identity/profiles/{user_id}` | Legacy profile read. Use `/entities/{entity_id}` instead. |
| `PUT` | `/v1/identity/profiles/{user_id}` | Legacy profile write. |
| `GET` | `/v1/identity/profiles/{user_id}/graph` | Legacy graph read. |

---

## Identifier suppression

Suppression rules allow operators to permanently block an identifier hash from
being used in identity linking. Once suppressed:

1. The hashed identifier is checked before any alias lookup or edge write.
2. All existing aliases linked via that hash are revoked.
3. Future resolution events carrying that hash produce a `blocked` decision.
4. The suppression rule is **append-only** — rules are revoked, never deleted,
   so the audit trail is preserved.

Suppression is tenant-scoped. A suppression rule in tenant A has no effect on
tenant B.

Suppression rules are stored in `identity_suppression_rules` with:
- `identifier_type` — the signal category (e.g. `email_hash`, `phone_hash`)
- `identifier_hash` — HMAC-SHA256 of the normalized raw value (never stored)
- `reason` — human-readable rationale (e.g. "user_request", "legal_hold")
- `expires_at` — optional expiry; NULL means permanent
- `revoked_at` — set when the rule is revoked (never deleted)

A unique partial index on `(tenant_id, identifier_type, identifier_hash) WHERE revoked_at IS NULL`
enforces one active rule per identifier per tenant. Creating a duplicate returns
the existing active rule (idempotent).

---

## Operator merge/split/recompute workflow

1. **Conflict surfaces** — the resolver emits `candidate` for ambiguous
   signals. These appear in `GET /v1/identity/conflicts`.
2. **Operator reviews** — conflicts show the two candidate `canonical_entity_id`
   values, the supporting signals, and their confidence scores.
3. **Operator merges or dismisses** — `POST /v1/identity/merge` writes the
   decision with reason `manual_operator_merge` and updates both entities.
4. **Split if needed** — `POST /v1/identity/split` reverses an incorrect
   merge; audit lineage is preserved.
5. **Recompute** — `POST /v1/identity/recompute` replays ingestion events
   to refresh resolution after schema or policy changes.

---

## SDK boundary

The Aether SDK is signals-only. It:

- Emits raw identity signals (`userId`, `anonymousId`, `walletAddress`, etc.)
  as fields on canonical events.
- Never receives or emits `canonical_entity_id`.
- Never makes resolution decisions.
- Never links cross-device profiles.

`canonical_entity_id` is assigned exclusively by
`services/identity/resolver.py` after Bronze ingestion. Operators and backend
services may read it via the `/v1/identity/entities` API. The SDK has no
access to this field.
