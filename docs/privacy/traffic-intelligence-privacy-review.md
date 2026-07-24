---
title: Traffic Intelligence Privacy Review
slug: privacy/traffic-intelligence-privacy-review
section: compliance
visibility: I
audience: [compliance, security, architect]
status: stable
canonical_owner: privacy@aether
---
# Traffic Intelligence Privacy Review

This review documents the privacy posture of the traffic-intelligence surfaces:
the source classifier, the verified source-link redirect, the source/handoff
records, and Apple platform-attribution ingestion. Each principle names the
control that enforces it in code, or states plainly where a claim is an
architectural boundary rather than a code-enforced guarantee.

## Data-minimization principles

### P1 — No raw form values captured

Classification inputs are limited to acquisition evidence: referrer, referrer
domain, UTM parameters, click identifiers, landing page, and user agent
(`SourceClassifier.classify` signature in `services/traffic/classifier.py`).
There is no form-field, input-value, or DOM-content parameter anywhere in the
classifier contract. Form values are neither an input nor an output of traffic
intelligence.

### P2 — No raw referrer URLs or sensitive query strings at rest

The classifier never returns a raw referrer URL. It emits only a normalized
hostname, an origin-only URL (scheme + host, no path or query), and a one-way
`referrer_path_hash` (`SourceClassifier.normalize_referrer`). Because the path
is stored only as a non-reversible hash, sensitive query strings and full paths
cannot be reconstructed downstream — the reclassification repair explicitly
preserves the existing hash instead of recomputing a path
(`services/traffic/repair.py`).

### P3 — Token and path hashing

Redirect and handoff tokens are persisted only as SHA-256 digests
(`_token_hash` in `services/traffic/referral_links.py`); plaintext tokens are
disclosed once at creation and never returned by read/list paths
(`public_referral_link`). Referrer paths are stored only as one-way hashes
(P2). No reversible token or path material is retained.

### P4 — No keyboard interception

Traffic intelligence has no keystroke input. The classifier and redirect
consume only navigation-level evidence (P1). This is a design boundary: there
is no keyboard/keylogging code path in these surfaces, and none is required for
source classification.

### P5 — No third-party app surveillance

Source determination relies on web navigation evidence and platform postbacks,
not on observing other installed applications. Apple platform evidence is
consumed only through Apple's own AdAttributionKit / SKAdNetwork postbacks
(`services/attribution/apple_postbacks.py`), which are aggregate and
campaign-level — the design does not inspect a device's other apps, and no such
signal is an input to classification.

### P6 — No accessibility-service dependence

Classification requires no OS accessibility service. All inputs are ordinary
web request/navigation attributes (P1); the traffic-intelligence design places
no dependence on accessibility APIs to obtain evidence.

> Scope note for P4–P6: these are statements about the traffic-intelligence
> backend surfaces reviewed here. They describe capabilities the design does
> **not** require or use. Native-SDK capture behavior is owned and audited
> separately; this review does not assert guarantees about code outside these
> surfaces.

### P7 — Consent-governed capture

The persistent traffic-intelligence resources are governed by the storage
policy registry with consent invalidation enabled. In
`config/storage_policies.yaml`, `verified_referral_links`,
`verified_referral_link_uses`, `source_link_handoffs`, and
`deferred_attribution_handoffs` all declare `requires_consent_invalidation:
true`, so consent revocation invalidates derived materializations. The registry
is enforced (`enforcement_status: enforced`, coverage-gated by
`scripts/release/check_storage_policies.py`), and `StorageManager`
(`shared/storage/manager.py`) fails closed for any resource type without a
policy.

Apple postbacks are the deliberate exception: `apple_attribution_postbacks`
declares `requires_consent_invalidation: false` because the rows carry no
per-subject identity (campaign-level aggregate evidence with no user linkage),
so there is no subject whose consent revocation would apply. This is documented
in the policy comment and is intentional, not an omission.

### P8 — Bot traffic is not treated as a person

Machine/scanner/link-preview requests are detected before any human-evidence
branch (`_classify_user_agent`, `_classify_redirect_user_agent`) and never mint
a user-correlatable handoff token (`handoff_minted = not is_machine`). Bot
traffic therefore does not create person-level records.

## Subject-linkage summary

| Surface | Subject-linked? | Retained identifiers |
|---|---|---|
| Verified referral link | No (tenant config) | destination, hashed token |
| Referral link use | Session-level | hashed handoff, UA class, `is_machine` |
| Source-link handoff | Short-lived (15 min) | SHA-256 handoff hash only |
| Deferred attribution handoff | Deterministic, hashed | SHA-256 identifier hash only |
| Apple postback | No (campaign aggregate) | reduced campaign fields, no user id |

See `docs/privacy/traffic-intelligence-data-retention.md` for the retention
class and delete behavior of each surface.
