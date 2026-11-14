---
title: Pattern Discovery and Unstructured Evidence Intelligence
slug: pattern-discovery
section: concepts
visibility: I
audience: [security, architect, dev-senior, ops]
status: experimental
since_version: "0.1.0"
source_files:
  - services/api/intelligence/pattern_discovery/
source_hashes:
  "services/api/intelligence/pattern_discovery/": "sha256:de0f543bd9604aa851e35c7d986167d499afc5a97e97f4cdfdc90d91865d5a66"
---

# Pattern Discovery and Unstructured Evidence Intelligence

Aether's normalizers, identity resolution, graph projection and risk detectors
interpret evidence they were built to understand. Pattern Discovery is the
layer for everything else. It reads raw and semi-structured evidence,
interprets it schema-on-read, finds patterns that were never defined in
advance, and puts each one in front of a reviewer as an evidence-backed
candidate. Promotion into durable risk intelligence happens only after
review.

It is a governed plane *beside* the canonical graph, not inside it.
Discovery output is always `claim_state: inferred`. Discovery never merges
identities, marks an agent malicious, denies a transaction or writes a graph
fact.

Code: `services/api/intelligence/pattern_discovery/`. Flag:
`AETHER_PATTERN_DISCOVERY_ENABLED` (default off).

## Pipeline

```
raw evidence (events + arbitrary properties, free text, optional graph edges)
  -> extraction.py      schema-on-read: typed attributes, counterparties, message templates
  -> engine.py          discovery frame, field profiles
  -> baselines.py       decayed tenant baseline: what is normal here
  -> detectors/         unknown-pattern detectors
  -> cross_domain.py    independent detectors agreeing on the same entities
  -> scoring.py         confidence (capped), novelty, severity, analyst calibration
  -> registry.py        versioned pattern records, lifecycle, compare-and-set writes
  -> service.py         review -> promote -> attributed Risk360 signals
```

`engine.run_discovery` is pure (evidence, baseline and feedback in; records
and baseline delta out), so every run can be reproduced from its inputs.
`service.PatternDiscoveryService` does all I/O.

## Schema-on-read extraction

`extraction.extract_events` accepts any event rows (`event_type`,
`occurred_at`, identity fields, arbitrary nested `properties`) and returns:

- **Extracted events.** For each row: the acting entity (`user:`, `agent:`,
  `anon:`, `session:` or `entity:`), a behavioural *token* (event type plus
  outcome, such as `add_card!fail`, or event type plus a message template for
  free text), typed attributes and counterparty links (`TRANSACTS_WITH`,
  `DELEGATED_BY`, `SPAWNED_BY`, `INVITED_BY`, `TARGETS`).
- **Attribute typing.** The value's own shape is checked first (email, EVM/BTC
  wallet, Luhn-valid card number, IPv4/IPv6, URL host, phone, user agent,
  timestamp, hash). Key-name hints (`device_id`, `card_fingerprint`, ...) are
  used only after that, at lower confidence.
- **Learned identifiers.** Per `(source, event_type)` field profiles record
  path, type mix, cardinality and presence. A field nobody modelled is
  promoted to a linkage attribute `field:<path>` when its values behave like
  identifiers: strings with no whitespace, neither constant nor unique, not
  dominated by one value, not a known category name, and at least one value
  shared by several entities.
- **Free text.** Error messages, notes, transcripts and logs are collapsed to
  Drain-style templates (`card <*> declined for order <*> at <*>`), and any
  identifiers embedded in the text are extracted.
- **Candidate observations.** Each attribute assertion carries its extractor
  and confidence and is always `inferred`.

Privacy: emails, phones, payment instruments, IPs, user agents, learned
fields and anything found in free text are replaced by a tenant-salted
digest before they leave extraction. Wallet addresses and hosts are kept
because they are public identifiers that investigations need. Rows of
another tenant are counted and ignored.

## Detectors

All detectors are deterministic, bounded and dependency-free. None of them
reports a pattern that most of the population shares: that is the product's
normal flow.

| Kind | What it finds | Statistic |
|---|---|---|
| `sequence` | Recurring token chains (n = 3..5, runs collapsed to `token+`) | Lift over an order-1 Markov model of the same window; novelty against baseline n-gram rates |
| `shared_attribute_cluster` | Entities converging on devices, IPs, wallets, cards, emails or learned fields | Hub values (robust z on degree per attribute type) plus components linked by hubs or by two or more shared values; ubiquitous values excluded |
| `behavioral_cohort` | Near-identical behaviour across many entities | TF-IDF + time-of-day cosine; threshold learned from the population's p99 random-pair similarity; normal-flow cohorts dropped |
| `temporal_burst` | Token rates far above normal | Poisson tail against the baseline rate (or the same window without its peak) |
| `lockstep` | Many entities doing the same thing in the same minute, repeatedly | Membership Jaccard across windows |
| `behavioral_outlier` | Entities extreme on the same set of features (rate, diversity, failure ratio, device/IP/wallet/card/email churn, fan-out, amount) | Upward robust z, grouped by feature signature |
| `novel_motif` | Typed triangles and directed 3–4 cycles not in `relationship-motif-registry.json` | Closure rate relative to the graph average |
| `schema_drift` | New event groups, new / dropped / retyped fields, new identifier fields | Field presence against the baseline profile |
| `cross_domain` | Patterns of different kinds implicating the same entities | Entity-set Jaccard ≥ 0.4 across kinds |

A detector that raises an exception is recorded in the run stats and skipped.
The other detectors still run.

## Scoring

- **Confidence** is a noisy-OR of evidence strengths, multiplied by the kind's
  calibration factor and clipped at the kind's cap (`CONFIDENCE_CAPS`: 0.65 to
  0.75 for statistical kinds, 0.85 for cross-domain, 0.9 for schema drift).
- **Calibration.** Each reviewer verdict is appended to `pattern_feedback`.
  Per kind, `factor = 0.5 + (useful + 1) / (useful + noise + 2)`, where
  `valid`/`malicious` count as useful and `benign`/`duplicate` as noise. A
  *family* (kind plus the coarse shape of its signature) dismissed three times
  and never confirmed stays in `candidate` at low priority.
- **Novelty** is the lower of the detector's novelty and the signature's
  novelty against the baseline. On a tenant's first run it is capped at 0.5.
- **Status.** `needs_review` when confidence ≥ 0.4, novelty ≥ 0.3 and the
  family is not suppressed. Otherwise `candidate`.
- **Severity** orders the queue. It is never used for enforcement.

## Registry and lifecycle

A pattern's identity is `(tenant, kind, signature)`, and its id is derived
from that. When a later run re-detects the same signature, the same record is
updated (`times_observed`, support, evidence). `version` is bumped when the
evidence fingerprint changes. The fingerprint covers the signature, the
evidence types, the order of magnitude of the affected population, and the
risk categories.

```
candidate <-> needs_review --verdict--> confirmed_valid / confirmed_malicious --promote--> promoted
                                      \-> benign / duplicate / unresolved
any open or reviewed state --> deprecated --(re-detected)--> funnel
```

- Only a reviewer verdict, with a reason of at least 10 characters, leaves the
  funnel. A `duplicate` verdict must name another pattern in the same tenant.
- A verdict holds only for the evidence fingerprint it was made on. A
  re-detection with a different fingerprint supersedes the verdict (the
  verdict stays in `review_history`) and the pattern re-enters the funnel.
- Promotion is allowed only from a confirmed status whose evidence has not
  changed since review. A promoted pattern is sticky: re-detection refreshes
  its support but never re-queues it.
- Open patterns not re-observed for `STALE_AFTER_RUNS` (6) runs of their
  detector are deprecated automatically. Reviewed patterns are never
  deprecated automatically.
- Every write after the first is a compare-and-set on `revision`, so
  concurrent reviews are all kept, in commit order.

Stores (JSONB, tenant-scoped): `discovered_patterns`, `pattern_feedback`,
`pattern_discovery_baselines` (one row per tenant), `pattern_discovery_runs`.

## Promotion into Risk360

`POST .../promote` writes one canonical `RiskSignal` per resolvable affected
subject and per registered risk dimension of the pattern
(`projections.promote_to_risk`):

- `claim_state: attributed`. A human attributed the pattern. It is never
  `verified` or `observed`.
- Subjects must be canonical. `entity:` and `user:` refs go through the
  identity authority (following merge tombstones) and must resolve to an
  existing subject. `agent:` refs must resolve to one canonical Agent.
  `wallet:` refs are subjects as they are. Anything unresolved gets no signal
  and is recorded as `unresolved_subject` in `promotion.risk_signals`.
- Signal ids are derived from content, so promoting again converges.
- `AETHER_PATTERN_RISK_PROMOTION_ENABLED` (default on) can turn the write off
  while keeping the promotion itself.

The same conversion is registered as the `pattern_discovery` producer in
`intelligence.risk360.signals` (`adapt_producer_signal`). Unreviewed
candidates produce no signals. Agent 360 and Profile 360 already read
canonical Risk360 signals for resolved subjects, so promoted patterns reach
those views through their existing authorities.

## Entity context

`GET /v1/intelligence/patterns/entities/{kind:id}` returns the emerging
patterns, reviewed patterns, unresolved identity overlaps and
most-co-implicated entities for one entity. It is advisory context for
Profile 360, Agent 360 and Risk 360 panels and is labelled `inferred` /
`advisory`.

## API

Tenant routes act on the authenticated tenant only (no header fallback):
reads need `read`, runs, reviews and deprecations need `write`, and promotion
needs `admin`. Kyber routes (`/v1/kyber/patterns/*`) need a Kyber operator,
name the tenant through `tenant_id`, and are declared in
`config/route_registry.yaml`. See `docs/reference/BACKEND-API.md` for the
endpoint list.

The Kyber web discovery queue is at `/intelligence/patterns`. The nav entry is
gated on the `pattern_discovery_enabled` capability flag.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `AETHER_PATTERN_DISCOVERY_ENABLED` | `false` | Mounts tenant and Kyber routes; exposes the capability flag |
| `PATTERN_DISCOVERY_WINDOW_HOURS` | `72` | Evidence window read from the event store per run |
| `PATTERN_DISCOVERY_MAX_EVENTS` | `50000` | Event cap per run; a truncated read is reported in `coverage.truncated` |
| `AETHER_PATTERN_RISK_PROMOTION_ENABLED` | `true` | Whether promotion writes Risk360 signals |

## Limits and honest gaps

- Runs are on-demand (tenant or Kyber `POST .../runs`). There is no scheduled
  worker yet.
- Pattern listing scans up to 5,000 records per tenant in the service layer.
  Very large registries need indexed queries.
- Detectors work within one evidence window plus the decayed baseline. Patterns
  spread more thinly than the window are seen only through baseline drift.
- The IsolationForest + autoencoder model in `services/ml` is not called. The
  outlier detector is its explainable, dependency-free counterpart.
- Nothing here has been validated against labelled production data. It is
  experimental, and `scripts/production_status.py` makes no readiness claim
  for it.
