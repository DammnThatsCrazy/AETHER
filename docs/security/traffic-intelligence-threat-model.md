---
title: Traffic Intelligence Threat Model
slug: security/traffic-intelligence-threat-model
section: security
visibility: I
audience: [security, architect, dev-senior]
status: stable
canonical_owner: security@aether
---
# Traffic Intelligence Threat Model

Scope: the acquisition-source / traffic-intelligence surfaces — the verified
source-link redirect (`GET /v1/r/{token}`), the source classifier, deferred and
platform (Apple) attribution ingestion, and the historical reclassification
repair job. Each threat below names the concrete control that mitigates it and
the code path that enforces it. Controls are described as they are implemented;
where a guarantee is partial it is called out explicitly.

## Trust model

- The redirect endpoint is **public and unauthenticated**. It must never leak
  token state, never accept a caller-supplied destination, and never mint
  user-correlatable evidence for non-human traffic.
- The classifier is a **pure, server-side function**
  (`services/traffic/classifier.py`, `SourceClassifier.classify`). SDKs submit
  raw evidence; they do not decide source, medium, channel, or proof level.
- Apple postbacks are **campaign-level platform evidence only**. They never
  create a touchpoint or resolve a user/install to a campaign.

---

## T1 — Open redirect

**Risk:** an attacker crafts a redirect that forwards victims to an
attacker-controlled destination, abusing Aether's domain reputation.

**Control:** the visitor is only ever redirected to the link's *stored*
`destination_url`; a request-supplied destination is structurally impossible.
`redirect_verified_source_link` (`services/traffic/routes.py`) reads
`result["destination_url"]` from the resolved record and passes nothing from the
request into the target. Destinations are sanitized when the link is created
(`_clean_destination_url` in `services/traffic/referral_links.py`). The only
request-derived value appended is the one-time `aether_ref` handoff token
(`_append_handoff_param`), which is opaque and Aether-minted.

## T2 — Cross-tenant token acceptance

**Risk:** a token issued for tenant A is accepted while acting as tenant B,
crossing a tenant boundary.

**Control:** verified links are stored per tenant and resolved by
`token_hash`; the resolved record carries its own `tenant_id`, which is the
only tenant used for the recorded use and any minted handoff
(`resolve_redirect`). Handoff consumption is explicitly tenant-scoped —
`consume_handoff_hash` filters `WHERE tenant_id = $1 AND handoff_hash = $2`, so
a handoff minted for one tenant cannot be consumed under another. Apple postback
idempotency and storage are keyed on `(tenant_id, idempotency_key)`
(`ApplePostbackRepository.store`, migration `20260803_deferred_attribution`).

## T3 — Replay

**Risk:** a captured redirect or handoff token is replayed to fabricate
repeated or duplicate acquisition evidence.

**Controls:**
- Redirect eligibility enforces expiry, valid-from, environment match, active
  status, and `max_uses` (`_redirect_eligible`); an exhausted link stops
  minting handoffs.
- The handoff token is **one-time**: `consume_handoff_hash` sets `consumed_at`
  atomically (`FOR UPDATE`), and a second consumption returns `replayed` while
  incrementing `replay_count`. Re-consumption by the *same* `source_event_id`
  is treated idempotently (`consumed`), not as new evidence.
- Handoffs are short-lived (`_HANDOFF_TTL = 15 minutes`).
- Apple postback redelivery is de-duplicated by the idempotency key
  (`ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`), so Apple's retry
  storms never double-store.

## T4 — Token at rest

**Risk:** disclosure of stored tokens allows forging redirects or handoffs.

**Control:** tokens are never stored in cleartext. Both the referral token and
the handoff token are persisted only as SHA-256 digests (`_token_hash`); the
plaintext `referral_token` is disclosed exactly once, in the create response,
and never returned by any list/read path (`public_referral_link` omits it).
Lookups compare digests (`secrets.compare_digest` on the local path; indexed
`token_hash` equality on SQL).

## T5 — Sensitive-query / raw-URL logging

**Risk:** referrer URLs and landing pages carry PII or sensitive query strings
(search terms, tokens) that must not be persisted or logged.

**Control:** the classifier never returns a raw referrer URL. It emits only a
normalized hostname, an origin-only URL, and a one-way `referrer_path_hash`
(`SourceClassifier.normalize_referrer`; see the module docstring: "Raw referrer
URLs are never returned"). The path hash is non-reversible, so downstream
storage and the reclassification repair cannot reconstruct the original path
(`services/traffic/repair.py` preserves the existing hash rather than
recomputing from the sanitized origin).

## T6 — Scanner / bot classified as human

**Risk:** link-preview crawlers, security scanners, and bots inflate human
acquisition counts or receive user-correlatable handoffs.

**Control:** machine user agents are detected first, ahead of every other
signal. In the classifier, `_classify_user_agent` runs before referral, click,
UTM, and referrer branches and yields a non-attribution-eligible result. At the
redirect, `_classify_redirect_user_agent` flags `is_machine`; machine requests
are recorded with `is_machine = true` and **no handoff token is minted**
(`handoff_minted = not is_machine`), so bots never generate user handoffs.

## T7 — Campaign / source conflation

**Risk:** conflating "where traffic came from" with "which campaign gets
credit" corrupts both attribution and measurement.

**Control:** the classifier is deliberately campaign-agnostic — it "remains the
sole owner of neither campaign identity nor conversion credit" (module
docstring); the campaign resolver and attribution engine are separate owners.
Apple postbacks reinforce this boundary: they are stored as campaign-level
`platform_verified` measurement input and "never resolve a user or install to a
campaign" (`services/attribution/apple_postbacks.py` module docstring).

## T8 — SDK-side classification

**Risk:** a compromised or spoofed SDK asserts its own source/medium/proof,
bypassing server judgement.

**Control:** classification is server-authoritative. `report_traffic_source`
(`services/traffic/routes.py`) calls the server classifier and then **overwrites**
the client-provided `source`, `medium`, `traffic_type`, and `confidence` with
the classifier's output. The SDK's role is limited to submitting raw evidence;
it cannot set a proof level.

## T9 — Verified → inferred silent downgrade

**Risk:** evidence that was cryptographically or server-verified is silently
degraded to inferred, or a weak claim is silently promoted to verified.

**Controls:**
- Proof levels are ranked (`_PROOF_RANK`) and claim-provided proof is capped by
  what the evidence supports (`ENTRY_METHOD_PROOF_CEILINGS`); a claim cannot
  raise its own proof above its entry method's ceiling.
- Suppressed-but-conflicting signals are not discarded — they are preserved in
  `evidence_conflicts` on every `ClassifiedSource`, so a downgrade is auditable
  rather than silent.
- The reclassification repair "never overwrites classification history"
  (`services/traffic/repair.py` module docstring); it records new revisions with
  a reason string and input hash rather than mutating prior evidence.
- Apple signature status is explicit and non-silent: a verified signature is
  recorded `verified`; a known-version signature that fails verification is
  **rejected** (HTTP 422) and never stored; an unknown version is stored
  `unverified` (low-trust), never upgraded to `verified`.

## T10 — Fingerprint treated as proof

**Risk:** device/browser fingerprinting is used as attribution proof, which is
both privacy-hostile and unreliable.

**Control:** the classifier derives proof only from declared/observed evidence
— verified referral link, paid click identifiers, UTM parameters, or a
normalized referrer domain. With no such evidence the result is
`direct_unknown` with `proof_level = "none"` (the no-evidence fallback in
`classify`), never a fingerprint-derived claim. There is no device-fingerprint
input to `SourceClassifier.classify`.

## T11 — Forged Apple attribution postback

**Risk:** a forged AdAttributionKit / SKAdNetwork postback fabricates
platform-verified campaign evidence.

**Control:** postback signatures are cryptographically verified. The signed
parameter string is reconstructed per postback version (SKAdNetwork
2.1/2.2/3.0 and 4.0 / AdAttributionKit), joined by the U+2063 separator, and the
`attribution-signature` is checked with ECDSA(SECP256R1, SHA-256) against
Apple's published key using `cryptography`
(`services/attribution/apple_postbacks.py`, `_build_signed_message` /
`_evaluate_signature`). A known-version signature that fails verification is
rejected and stored nowhere; only a genuinely verified signature is recorded
`verified`.

**Honest limitation:** the Apple verification key is embedded as
`APPLE_SKADNETWORK_PUBLIC_KEY_B64` (Apple's widely-published SKAdNetwork P-256
key) and is operator-overridable via `AETHER_APPLE_SKADNETWORK_PUBLIC_KEY_B64`.
Operators must confirm the key against Apple's current "Verifying an
install-validation postback" documentation for their integration. If the
configured key is absent or unloadable, signatures are recorded honestly as
`unverified` (low-trust) rather than falsely `verified`; the verification code
path itself is fully implemented and does not depend on key provenance.

---

## Non-oracle guarantee

Every failed redirect condition — unknown, expired, revoked, wrong-environment,
not-yet-valid, exhausted, missing destination — collapses to an identical HTTP
404 (`resolve_redirect` returns `None`; the route raises a uniform 404). The
endpoint therefore does not function as a token-state oracle.
