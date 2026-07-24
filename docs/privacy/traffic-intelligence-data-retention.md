---
title: Traffic Intelligence Data Retention
slug: privacy/traffic-intelligence-data-retention
section: compliance
visibility: I
audience: [compliance, ops, security]
status: stable
canonical_owner: privacy@aether
---
# Traffic Intelligence Data Retention

Retention for each traffic-intelligence table is governed by the enforced
storage-policy registry, `config/storage_policies.yaml`. This page documents the
policy entries exactly as declared; it is not itself the source of truth. The
registry is coverage-gated by `scripts/release/check_storage_policies.py`, and
`StorageManager` (`shared/storage/manager.py`) fails closed for any persistent
resource type lacking a policy.

## How retention classes resolve to durations

The storage-plane lifecycle (`shared/storage/lifecycle.py`) interprets
`retention_class`:

- **`standard`** — rows and any externalized objects age out after
  `STORAGE_RETENTION_STANDARD_DAYS` (default **365 days**, see
  `config/settings.py`). Sweeping runs only when
  `STORAGE_LIFECYCLE_RETENTION_ENABLED` is set (default off).
- **`legal`** — never swept; compliance-owned (`_retention_days` returns `None`
  and the sweep is skipped with `retention_class=legal is compliance-owned`).

A `legal_hold_supported: true` policy allows an active legal hold to block
deletion regardless of class.

## Policy entries (verbatim from the registry)

All five traffic-intelligence tables share `retention_class: standard`,
`delete_behavior: hard_delete`, and `legal_hold_supported: true`. They differ
only in consent-invalidation, reflecting whether the rows are subject-linked.

| Resource type | retention_class | delete_behavior | requires_consent_invalidation | legal_hold_supported |
|---|---|---|---|---|
| `verified_referral_links` | standard | hard_delete | true | true |
| `verified_referral_link_uses` | standard | hard_delete | true | true |
| `source_link_handoffs` | standard | hard_delete | true | true |
| `deferred_attribution_handoffs` | standard | hard_delete | true | true |
| `apple_attribution_postbacks` | standard | hard_delete | **false** | true |

### verified_referral_links

Controlled verified-link definitions (destination + hashed token). Standard
retention, hard delete on expiry/sweep. Consent invalidation applies. No
plaintext token is retained (`_token_hash`).

### verified_referral_link_uses

Per-use redirect records (UA class, `is_machine`, verification result,
environment, hashed handoff linkage). Standard retention, hard delete. Consent
invalidation applies because a use is session-level evidence.

### source_link_handoffs

One-time redirect handoff tokens minted by `GET /v1/r/{token}`, stored hashed at
rest with a short operational TTL (`_HANDOFF_TTL = 15 minutes`) and consumed
once. The registry comment records them as "user acquisition evidence."

> Note the two independent clocks: the **15-minute operational TTL** governs
> when a handoff can still be consumed (`_redirect_eligible` / expiry check in
> `consume_handoff_hash`), while the **standard retention class** governs when
> the durable row is swept. The TTL expiring makes a handoff unusable; it does
> not by itself delete the row.

### deferred_attribution_handoffs

Deterministic pre-install handoff records reconciled on first launch; the
identifier is stored only as a SHA-256 hash and the record is consumed once
(migration `20260803_deferred_attribution`). Standard retention, hard delete,
consent invalidation applies.

### apple_attribution_postbacks

Campaign-level AdAttributionKit / SKAdNetwork postbacks (proof_level
`platform_verified`), stored idempotently on `(tenant_id, idempotency_key)`.
Standard retention, hard delete, `legal_hold_supported: true`. This is the one
entry with `requires_consent_invalidation: false`: the rows carry **no
per-subject identity** (aggregate, campaign-level platform evidence with no user
linkage), so there is no subject whose consent revocation would apply. The
registry comment states this explicitly, and it is intentional rather than a
gap.

## Cross-references

- Subject-linkage and capture minimization:
  `docs/privacy/traffic-intelligence-privacy-review.md`.
- Token/replay/oracle controls:
  `docs/security/traffic-intelligence-threat-model.md`.
