---
title: API Anti-Distillation Controls
slug: security/api-anti-distillation
section: security
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: security@aether
source_files:
  - Backend Architecture/aether-backend/services/security/anti_distillation.py
last_synced_commit: "pending"
estimated_read_minutes: 6
---

# API Anti-Distillation Controls

> Aether's intelligence APIs expose scored signals that represent significant
> investment in data acquisition, model training, and enrichment pipelines.
> Anti-distillation controls prevent adversaries from systematically querying
> the API to reconstruct a competing intelligence dataset at Aether's expense.

## The distillation threat

Model distillation via API is a known attack: an adversary makes a large number
of diverse, representative queries to an intelligence API, accumulates the
scored responses, and trains a model on those responses that approximates the
source model's behavior. The adversary gets model-quality intelligence for the
cost of API credits.

In Aether's context, the attack surface is broader than model copying. An
adversary can:

- Query thousands of wallet addresses to build a labeled dataset of risk scores.
- Systematically extract protocol health scores across all major protocols.
- Combine wallet scores with on-chain data to back-engineer scoring features.

The controls below make this prohibitively expensive while preserving legitimate
high-volume use.

---

## Control 1: Rate limiting

Standard rate limits are enforced per API key and per tenant. Rate limit
thresholds vary by plan tier.

| Plan tier | Wallet score requests/minute | Protocol requests/minute |
|---|---|---|
| P1 (Free) | 10 | 5 |
| P2 (Startup) | 100 | 50 |
| P3 (Growth) | 500 | 200 |
| P4 (Enterprise) | Custom SLA | Custom SLA |

Rate limit headers (`X-RateLimit-Remaining`, `X-RateLimit-Reset`) are returned
on every response. Requests that exceed the limit receive `429 Too Many Requests`.

Rate limits are enforced at the Redis layer and are window-resetting (sliding
window, not fixed bucket).

---

## Control 2: Rapid diverse query detection

Rate limits alone do not stop a patient adversary who queries slowly over time.
The rapid diverse query detector specifically looks for the distillation pattern:
many different wallet addresses queried in a short window.

**Threshold:** Any API key that queries more than 100 distinct wallet addresses
within a 60-second window triggers an automated review hold.

**Detection logic:**

1. The middleware tracks a rolling 60-second window of unique wallet addresses
   per API key using a Redis HyperLogLog counter.
2. When the unique-address count exceeds 100 in the window, a
   `security.rapid_diverse_query` audit event is emitted.
3. The key is placed in a `REVIEW_HOLD` state for 10 minutes.
4. During `REVIEW_HOLD`, the API key continues to function but all responses
   are served from a degraded tier (see score binning below).
5. If the pattern repeats within 24 hours, the hold escalates to a
   `MANUAL_REVIEW` flag and the security team is notified.

The 100-wallet threshold is intentionally permissive enough to allow legitimate
batch enrichment pipelines but tight enough to flag systematic extraction.
Customers with legitimate high-volume needs should contact support to configure
a monitored allowlist.

---

## Control 3: Score binning by plan tier

Raw model scores are continuous values (e.g., `0.832`). Returning high-precision
scores on every request allows an adversary to reconstruct fine-grained score
distributions with relatively few queries.

Score binning rounds returned scores to a resolution that matches the plan tier:

| Plan tier | Score resolution | Example |
|---|---|---|
| P1 (Free) | 0.1 | 0.8 |
| P2 (Startup) | 0.05 | 0.80 |
| P3 (Growth) | 0.01 | 0.83 |
| P4 (Enterprise) | 0.001 | 0.832 |

Binning is applied at the API response serialization layer, not at the model
layer. The model always produces full-precision scores internally. This means
that if a customer upgrades their plan tier, historical scores are not
retroactively re-exposed; only new API calls benefit from higher precision.

**During REVIEW_HOLD:** Score resolution is automatically reduced by one tier
(e.g., a P3 key in REVIEW_HOLD receives P2-level binning) until the hold clears.

---

## Control 4: Honeypot wallets

A set of synthetic wallet addresses is maintained as a honeypot. These addresses
do not correspond to real wallets but return plausible-looking scores from a
separate model that generates consistent fictional responses.

**Purpose:** If an adversary queries a honeypot wallet, it signals that they
are using address-enumeration strategies rather than querying known-interesting
wallets. Honeypot queries trigger immediate escalation to `MANUAL_REVIEW`.

**Operational rules:**

- The honeypot address list is maintained by the security team only.
- Honeypot addresses must never be added to any public list or documentation.
- The response served for honeypot addresses is indistinguishable from a
  real scored response (same latency profile, same schema).
- All honeypot query audit events are flagged `HIGH_CONFIDENCE_DISTILLATION`.

---

## Control 5: Audit events

All anti-distillation controls emit structured audit events to the immutable
audit log.

| Event | Trigger | Severity |
|---|---|---|
| `security.rate_limit_exceeded` | Rate limit hit | INFO |
| `security.rapid_diverse_query` | 100+ unique wallets/60s | MEDIUM |
| `security.review_hold_activated` | Key placed in REVIEW_HOLD | HIGH |
| `security.honeypot_query` | Query against honeypot address | CRITICAL |
| `security.manual_review_flagged` | Repeated pattern within 24h | HIGH |
| `security.distillation_confirmed` | Human review confirms threat | CRITICAL |

---

## Legitimate high-volume use cases

These controls are not intended to block legitimate use cases. Tenants with
genuine batch enrichment needs should:

1. Request a monitored allowlist through the enterprise support channel.
2. Provide a use-case description (e.g., "nightly enrichment of 50k wallet
   portfolio").
3. The platform issues a configurable batch-mode rate limit with extended windows.

Batch-mode keys are monitored more closely than standard keys to ensure the
declared use case matches actual query patterns.

---

## Related docs

- `BYOK_PROVIDER_GATEWAY.md` — Credential controls that complement API security.
- `DATA_RIGHTS_LEDGER.md` — Rights framework that governs what the API serves.
- `SOURCE_TO_MODEL_MATRIX.md` — Model outputs the API exposes.
