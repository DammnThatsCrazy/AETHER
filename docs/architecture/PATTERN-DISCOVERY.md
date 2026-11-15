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
  "services/api/intelligence/pattern_discovery/": "sha256:c1bcdbf62474f76e1e0195b26fcdcf71114a7b8b6c66afdfcce63c8c0769695f"
---

# Pattern Discovery and Unstructured Evidence Intelligence

Aether's normalizers, identity resolution, graph projection and risk detectors
interpret evidence they were built to understand. Pattern Discovery handles
everything else. It reads raw and semi-structured evidence, interprets it
schema-on-read, finds patterns nobody defined in advance, and surfaces each
one to the people using Aether automatically: in a tenant feed, on the graph,
in the 360 views and in a "new since you last looked" digest. No human step
is needed to *see* a pattern. Every pattern stays reviewable afterwards:
anyone can hide, pin or rename it, or give it a verdict. Only a deliberate
promotion turns a pattern into durable risk and graph intelligence.

It is a governed plane *beside* the canonical graph, not inside it. Discovery
output is always `claim_state: inferred`. Discovery never merges identities,
marks an agent malicious, denies a transaction or writes a graph fact.
Surfacing is presentation, not a decision. Only a promotion writes anything
durable outside the plane, and what it writes is `attributed`, never
`verified`.

Code: `services/api/intelligence/pattern_discovery/`. Master flag:
`AETHER_PATTERN_DISCOVERY_ENABLED` (default off).

## Pipeline

```
raw evidence (events + arbitrary properties, free text, canonical graph edges)
  -> extraction.py     schema-on-read: typed attributes, segments, tools, principals, templates
  -> engine.py         discovery frame, field profiles
  -> baselines.py      tenant / segment / hour-of-week baselines (decayed)
  -> detectors/        13 unknown-pattern detectors (+ ML window scores)
  -> cross_domain.py   independent detectors agreeing, within and across runs
  -> scoring.py        capped confidence, novelty, severity, analyst calibration + tuning
  -> registry.py       versioned records, lifecycle, CAS writes, duplicate merging
  -> service.py        review -> promote -> Risk360 signals + RiskCluster graph edges
  -> sections.py       Profile 360 / Agent 360 / Risk 360 sections
  -> jobs.py           scheduled per-tenant discovery
```

`engine.run_discovery` is pure: evidence, baseline, feedback, ML scores and
prior patterns go in, and records plus a baseline delta come out, so every run
can be reproduced from its inputs. `service.PatternDiscoveryService` does all
the I/O.

## Schema-on-read extraction

`extraction.extract_events` accepts any event rows (`event_type`,
`occurred_at`, identity fields, arbitrary nested `properties`, optional raw
`text`) and produces:

- **The actor and principal.** When a row carries an agent id, the agent is the
  actor and the person (`user_id`, `principal_id`, `on_behalf_of`, ...) becomes
  its principal through a `DELEGATED_BY` link. Otherwise the actor is the
  canonical entity, user, anonymous id or session, in that order.
- **A behavioural token.** This is the event type plus its outcome
  (`add_card!fail`), `tool:<name>` for tool calls, or the event type plus a
  message template for free-text log and error events.
- **Typed attributes.** The value's shape is checked first (email, EVM/BTC
  wallet, Luhn-valid card, IP, URL host, phone, user agent, timestamp, hash),
  and key hints are used second, at lower confidence.
- **Learned identifiers.** A field nobody modelled is promoted to
  `field:<path>` when its values behave like identifiers: no whitespace,
  neither constant nor unique, not dominated by one value, not a category name,
  and at least one value shared by several entities.
- **Free text.** Error messages, notes, transcripts and logs are collapsed to
  Drain-style templates, and any identifiers embedded in them are extracted.
- **Cohort dimensions.** Each event is tagged with `entity_kind`, `application`,
  `geography` and, for agents, `agent_type`. Dimensions are taken only from
  the evidence, never guessed.
- **Window metrics.** The extraction records bot user agents (by pattern),
  latency and session ids for ML window features.
- **Candidate observations.** Each attribute assertion carries its extractor
  and confidence, and is always `inferred`.

Privacy: emails, phones, payment instruments, IPs, user agents, learned fields
and anything found in free text are replaced by a tenant-salted digest before
they leave extraction. Wallet addresses and hosts are kept as public
identifiers. Rows of another tenant are counted and ignored.

## Baselines

`baselines.py` keeps one decayed (EWMA) baseline row per tenant:

| Key | What it holds | Used by |
|---|---|---|
| `token_rate` | events/hour per token | bursts, segment shifts |
| `segment_rate` | events/hour per `dimension=value\|token` | segment shifts |
| `hour_of_week` | mean events/hour for each of the 168 weekly hours, with counts | seasonal bursts |
| `ngram_rate` | per-1k-session token n-gram rates | sequence novelty |
| `signatures` | runs seen and decayed support per pattern signature | novelty for every kind |
| `field_profiles` | field presence and dominant type per event group | schema drift |
| `motif_rate` | decayed counts of typed motifs | motif novelty |
| `attribute_degree` | robust degree statistics per attribute type | hub detection |

A run is folded into the baseline only once its evidence window ends at least
half a window after the last fold. Overlapping scheduled runs over mostly the
same events therefore never count one stretch of activity many times.

A run filtered to some kinds leaves the baseline sections of detectors it did
not run untouched: `ngram_rate` is updated only when the sequence detector
ran, and `motif_rate` only when motif detection ran. A detector that ran and
measured nothing still decays its section.

## Detectors

All detectors are deterministic, bounded and dependency-free. None of them
reports a pattern that most of the population shares: that is the product's
normal flow.

| Kind | What it finds | Statistic |
|---|---|---|
| `sequence` | Recurring token chains (n = 3..5, runs collapsed to `token+`) | Lift over an order-1 Markov model; baseline n-gram novelty |
| `shared_attribute_cluster` | Entities converging on devices, IPs, wallets, cards, emails or learned fields | Hub values (robust z per attribute type) plus components linked by hubs or by two or more shared values |
| `behavioral_cohort` | Near-identical behaviour across many entities | TF-IDF + time-of-day cosine with a population-learned threshold; normal-flow cohorts dropped |
| `temporal_burst` | Token rates far above normal *for that hour of the week* | Poisson tail against the seasonal rate, otherwise the flat baseline or the same window without its peak |
| `lockstep` | Many entities doing the same thing in the same minute, repeatedly | Membership Jaccard across windows; the signature's `anchor` (the group's smallest member) keeps disjoint groups distinct |
| `behavioral_outlier` | Entities extreme on the same set of features, compared only within their cohort (humans, agents, anonymous) | Upward robust z per cohort |
| `segment_shift` | A token surging inside one country, app, cohort or agent type while the rest of the tenant does not | Segment Poisson tail; localization against the rest of the tenant; single-valued dimensions excluded |
| `agent_spawn_anomaly` | Sub-agent fan-out extreme against the agent population, or spawn bursts | Robust z on child counts; children per 2-minute window |
| `agent_tool_signature` | One tool-call sequence run by agents of different principals | Identical per-session tool sets across ≥2 principals |
| `agent_interaction_cluster` | Agents transacting with, targeting or messaging each other across principals | Connected components of agent-to-agent links |
| `novel_motif` | Typed triangles and directed 3–4 cycles not in `relationship-motif-registry.json`, over extraction edges **and the tenant's canonical graph** | Closure rate relative to the graph average |
| `schema_drift` | New event groups, new, dropped or retyped fields, new identifier fields | Field presence against the baseline profile |
| `traffic_anomaly` | Hourly windows the ML `anomaly_detection` model flags | Model score > 0.5 on contract-shaped window features; requests carry `X-Service-Token` from `ML_SERVICE_TOKEN` for standalone serving |
| `cross_domain` | Patterns of different kinds implicating the same entities, including still-active patterns from earlier runs | Entity-set Jaccard ≥ 0.4 across kinds; at least one current-run member |

A detector that raises an exception is recorded in the run stats and skipped;
the others still run.

**ML.** The IsolationForest + autoencoder model in `services/ml` is trained on
window-level traffic metrics, so it scores hourly windows, not entities
(`detectors/ml_windows.py`, `ml.py`). The features are traffic volume,
conversion, mean session duration, bounce, error rate, p99 latency, bot share,
unique visitors and revenue. Inputs the evidence cannot supply are sent as zero
and listed in `unobserved_features` on the pattern. Scoring goes through the
existing ML serving client (`/v1/predict/batch`) with a 10-second timeout and
never fails a run. Flag: `PATTERN_DISCOVERY_ML_ENABLED`.

## Scoring and analyst feedback

- **Confidence** is a noisy-OR of evidence strengths, multiplied by the kind's
  calibration factor and clipped at the kind's cap (`CONFIDENCE_CAPS`: 0.6 to
  0.75 for statistical kinds, 0.85 for cross-domain, 0.9 for schema drift).
- **Calibration.** Every reviewer verdict is appended to `pattern_feedback`.
  For each kind, `factor = 0.5 + (useful + 1) / (useful + noise + 2)`, where
  valid and malicious verdicts count as useful and benign and duplicate as
  noise.
- **Threshold tuning.** With at least five verdicts on a kind, the detector
  threshold that governs it moves with `0.5 - precision`: up to 50% stricter
  for noisy kinds and up to 25% more sensitive for trusted ones. The tunable
  thresholds are sequence lift, cohort similarity, outlier z, burst tail
  probability, motif lift and lockstep size. The per-kind surfacing
  confidence bar (base `SURFACE_CONFIDENCE`, 0.4) moves the same way. Every adjustment is recorded in the run
  stats (`threshold_tuning`).
- **Suppression.** A *family* (kind plus the coarse shape of its signature)
  dismissed three times and never confirmed stays in `candidate` at low
  priority.
- **Novelty** is the lower of the detector's novelty and the signature's
  novelty against the baseline. On a tenant's first run it is capped at 0.5.
- **Status.** A pattern is `surfaced` (shown to users, with no human step)
  when confidence clears the per-kind bar, novelty is at least
  `SURFACE_NOVELTY` (0.3) and its family is not suppressed. Otherwise it stays
  `candidate`, which the UIs call "watching": kept and re-scored every run,
  but not shown by default.

## Registry and lifecycle

A pattern's identity is `(tenant, kind, signature)`. When a later run
re-detects the same signature, the same record is updated and its `version`
is bumped if the evidence fingerprint changed. The fingerprint covers the
signature, the evidence types, the order of magnitude of the affected
population and the risk categories.

```
candidate <-> surfaced            (automatic; surfaced is what users see)
surfaced / candidate --(optional verdict)--> confirmed_valid / confirmed_malicious --promote--> promoted
                                          \-> benign / duplicate / unresolved
any visible state --hide--> hidden --unhide--> the status it was hidden from
any open or reviewed state --> deprecated --(re-detected)--> funnel
```

- **Visible statuses** (`VISIBLE_STATUSES`) are `surfaced`, `unresolved`,
  `confirmed_valid`, `confirmed_malicious` and `promoted`. The tenant feed,
  the 360 sections, the lenses and the graph overlay show only these, pinned
  patterns first.
- **Surfacing is sticky.** Once surfaced, a pattern keeps `surfaced_at` and
  stays visible while it recurs. Recurrence lowers novelty, and that never
  pulls a surfaced pattern back to `candidate`.
- **Curation** (`apply_curation`, `POST .../curate`) is how people change a
  pattern without judging it: `hide` / `unhide` (unhide restores the stored
  pre-hide status), `pin` / `unpin`, and `rename` (sets `display_title`; the
  detector title stays in `detector_title`). Every action is recorded in
  `review_history`, and a hide is also recorded as noise feedback for
  calibration. Curation keys survive re-detection.
- **Verdicts are optional.** A verdict needs a reason of at least 10
  characters, and it is what calibration learns from.
- **Hidden and reviewed patterns stay put** while their evidence fingerprint is
  unchanged. A materially changed fingerprint resurfaces a hidden pattern
  (`resurfaced_after_material_change` in its history).
- A verdict holds only for the evidence fingerprint it was made on; a changed
  fingerprint supersedes it, and the superseded verdict stays in
  `review_history`.
- **Duplicates.** A `duplicate` verdict names the canonical pattern. The
  duplicate is merged into it: entities and support are added, and the
  duplicate's id is recorded in `duplicates`. Later re-detections of the
  duplicate signature strengthen the canonical pattern instead of
  re-entering the queue. Re-merging the same duplicate refreshes its
  contribution whenever its members or support changed, even under an
  unchanged fingerprint (which ignores individual members and counts), and is
  a no-op otherwise. Reversing or retargeting a `duplicate` verdict withdraws
  the contribution from the old canonical pattern (`duplicate_withdrawn` in
  its history), restoring its own membership and support.
- Promotion is allowed only from a confirmed status whose evidence has not
  changed since review, and it is sticky. Seeing a pattern is automatic;
  letting it write risk signals and graph edges stays a human act.
- **Timestamps.** `surfaced_at` (first visible), `changed_at` (last evidence
  fingerprint change, i.e. a new `version`) and `deprecated_at` drive "what's
  new".
- Open patterns not re-observed for `STALE_AFTER_RUNS` (6) runs of their
  detector are deprecated automatically. Reviewed patterns never are. A run
  whose evidence-store read failed ages nothing (`coverage.aging.status:
  skipped_store_unavailable`): absence from an unread store is not evidence.
  The same holds per detector: `traffic_anomaly` patterns are not aged unless
  ML scoring ran (`scored` or `no_windows`), and `novel_motif` patterns are
  not aged when the graph read was unavailable (`coverage.aging.skipped_kinds`).
  A selected `cross_domain` pass with too few input patterns counts as run
  with no match (`skipped: insufficient_inputs`), so composites age once their
  constituent patterns disappear.
  The scheduled job reports such a run as failed so the jobs worker retries it.
- Every write after the first is a compare-and-set on `revision`.

### Stores

There are five tenant-scoped JSONB tables, created by migration
`20261114_pattern_discovery_stores`. Each has CHECK constraints binding the row
tenant to the data tenant.

| Table | Contents | Indexes |
|---|---|---|
| `discovered_patterns` | pattern records | `(tenant, status, priority)`, `(tenant, kind)`, GIN on `affected_entity_keys` and on `segment_keys` |
| `pattern_feedback` | analyst verdicts | `(tenant, kind)` |
| `pattern_discovery_baselines` | one row per tenant | `(tenant, created_at)` |
| `pattern_discovery_runs` | run records | `(tenant, created_at)` |
| `pattern_viewer_state` | per-viewer, per-scope `last_seen_at` | `(tenant, viewer)` |

The feed reads by indexed status. Entity lookups and the graph overlay use the
GIN index (`data->'affected_entity_keys' ?| keys`), and lenses use the
`segment_keys` GIN index. The integration test
`tests/pattern_discovery/test_postgres.py` runs the migration's own SQL against
PostgreSQL when `PATTERN_DISCOVERY_TEST_DSN` is set. Storage policies are in
`config/storage_policies.yaml`.

## Privacy and governance

- **DSR erasure.** The `pattern_discovery` component is registered with the
  durable erasure job (`governance/consent/erasure_planes.py`). For a subject
  it redacts every exact subject ref (`user:`, `anon:`, `entity:`, `agent:`,
  `session:` keys or the bare id) from affected entities, evidence, signature
  content, title, summary, review history and promotion outcomes, and from
  merged-duplicate state (`base_entity_keys`, `duplicates[*].entity_keys`) so
  re-detection cannot fold the subject back in. User-authored text is scrubbed
  too: a renamed `display_title` and refs embedded inside review-history text
  (a rename to "Investigate user:alice" becomes "Investigate [erased]"), and a
  subject named only there is still found. The pattern
  id and signature hash are kept. Patterns left with fewer than two entities
  are deleted, because one remaining entity would re-identify the erased one
  by difference. Run records listing a redacted pattern are deleted too, as
  are the subject's own `pattern_viewer_state` rows. A legal hold on
  `discovered_patterns` skips the plane. Baselines and feedback carry no
  subject keys.
- **Consent.** Per-entity reads (entity context, the three 360 sections, the
  Journey 360 lens and "what's new" for an entity scope) and promotion require an affirmative `analytics` consent receipt from the
  authoritative server store, the same rule Agent 360 applies before reading
  Risk360. The check fails closed: a store error is a denial. The tenant
  review queue lists patterns built from evidence that already passed
  ingestion consent. The tenant feed, segment lenses and graph overlay list
  patterns built from evidence that already passed ingestion consent; they
  are tenant analytics surfaces, not per-subject disclosures.

## Promotion

`POST .../promote` requires `admin` or a Kyber operator. It:

1. writes one canonical Risk360 `RiskSignal` per affected subject and per
   registered risk dimension, with `claim_state: attributed` and
   content-derived ids. Subjects must resolve to a canonical entity (merge
   tombstones followed), a canonical Agent or a wallet, *and* hold consent.
   Anything else is recorded as `unresolved_subject` or `consent_withheld`
   and gets no signal (flag `AETHER_PATTERN_RISK_PROMOTION_ENABLED`);
2. writes governed graph intelligence through `GraphMutationGateway`: one
   `RiskCluster` vertex per pattern and one `MEMBER_OF_CLUSTER` edge from each
   subject that received a signal, built with the canonical
   `build_edge_properties` (so it passes `GraphWriteValidator` in production)
   and `causality_class: inferred_influence` (flag
   `AETHER_PATTERN_GRAPH_PROMOTION_ENABLED`).

Calling promote again on an already-promoted pattern performs no second
lifecycle transition. It re-runs only the projections a transient outage left
incomplete (outcomes never recorded, a failed risk write, or a failed graph
projection) and counts the retry in `promotion.projection_retries`; with
nothing incomplete it returns the pattern unchanged. Both projections are
idempotent.

Deprecating a promoted pattern soft-revokes its membership edges, including
after a `failed` graph projection that may have written some memberships
before stopping: every subject that received a signal is revoked, one failure
does not stop the rest, and the report says `revoked`, `partial` or `failed`
with counts. Its Risk360
signals remain as attributed history owned by the risk plane. The conversion
is also registered as the `pattern_discovery` producer in
`intelligence.risk360.signals`. Risk360 and the Agent 360 canonical risk read
consume those signals through their existing authorities.

## Surfaces

**360 sections** (`sections.py`). Each section is consent-gated and advisory:

| Endpoint | Section contents |
|---|---|
| `GET /v1/profile/{id}/patterns` | emerging patterns, similar profiles, behavioural cohorts, unresolved identity overlaps, contradictory evidence, changes from the profile's baseline (reads both `user:` and `entity:` keys) |
| `GET /v1/agent/{id}/patterns` | novel delegation motifs, tool-call signatures, spawning anomalies, shared infrastructure, behaviour repeated across principals, agent-to-agent interaction, principals |
| `GET /v1/risk360/{kind}/{id}/patterns` | pattern findings with evidence coverage and review status, campaigns, emerging clusters, graph motifs, temporal anomalies, written risk signals |

**What's new since I last looked** (`feed.py`). Each viewer has a
`last_seen_at` per scope: `feed` (the whole tenant), `<surface>:<entity key>`
for a 360 section, or `lens:<lens>:<subject>`. `GET .../whats-new?scope=`
returns patterns that are **new** (surfaced after last seen), **changed**
(already surfaced, but with a new evidence version since) and **retired**
(deprecated since), each with a digest by kind, severity, segment and risk
category. With no last-seen time it looks back 7 days. Viewing never marks
anything seen. `POST .../whats-new/seen` does, when the user clicks "Mark
seen". 360 sections and lenses carry `last_seen_at`, `new_count` and per-row
`is_new` / `is_changed`. After each run that surfaces high or critical
patterns, the service raises one in-app notification per tenant per day
(category `pattern_discovery`, link `/patterns?view=new`; flag
`AETHER_PATTERN_NOTIFICATIONS_ENABLED`).

**Patterns on the graph** (`graphview.py`). `GET .../{id}/graph` returns the
pattern as a renderable subgraph: the pattern node, member entities, the
shared attribute values and counterparties its evidence names (hashed values
stay hashed), principals and member patterns, and the links between them (at
most 300 nodes; `truncated` says so). `POST .../graph-overlay` takes the node
ids in a graph view (bare ids or `kind:id` keys, at most 500) and returns, per
node, the visible patterns it belongs to. A member is linked to a shared
attribute value only when the detector observed it with that value
(`owners` in the shared-attribute evidence, at most 50 per value); records
without owner sets draw no member-to-attribute edges. Likewise, `ACTS_FOR`
edges are drawn only for the agent/principal pairs the agent detectors
observed (`agent_principals`), and agent-to-agent edges only for observed
`(source, relation, target)` links (`links`), labelled with the relation.
Records without those draw principals attached to the pattern node
(`INVOLVES_PRINCIPAL`) and no agent-to-agent edges, rather than inventing
relationships.

**Segment lenses** (`lenses.py`). The engine stores a `segment_profile` on
each pattern: the share of its entities' events in each campaign, channel,
geography, application, entity kind and agent type. It also indexes
`segment_keys` (values with at least a 20% share).
`GET .../lenses/{lens}/{subject}` groups the visible patterns that
concentrate in a subject by kind: `campaign360/<campaign id>`,
`geographic360/<country code>`, `communication360/<channel | all>`, and
`journey360/<profile id>`. The journey lens shows the journey-shaped subset
of the profile's patterns and is consent-gated.

**Aether web.** `/patterns` is the tenant page. It has two views: "New since
you last looked" (`?view=new`, with mark-all-seen) and "All surfaced", with
filters for watching, hidden, reviewed and retired patterns. The detail panel
draws the pattern graph and offers pin / hide / rename, an optional verdict
and "Show on graph", which opens `/explore?pattern=<id>`. There, members in
view are outlined and the panel draws the subgraph. Without a pattern
selected, Explore offers "patterns touching these objects" through the
overlay. The Profile 360 overview and the Agent 360 page render the sections
with new / changed badges. The Risk overview shows the surfaced feed and a
link to what's new. Campaign 360 (overview), Journey detail (overview), Geo
(country level) and Communications render the lenses. All of these are gated
on the `pattern_discovery_enabled` capability.

**Kyber web.** `/intelligence/patterns` is the operator view of a tenant's
surfaced feed. It shows what is new since the operator last looked (with mark
seen), evidence, competing explanations, the pattern graph, related and member
patterns and review history. Operators can curate (pin, hide, rename), run
discovery, record an optional verdict, promote and deprecate.

**Contracts.** `packages/shared/pattern-discovery.ts` is the frontend twin of
the vocabularies. `tests/unit/test_pattern_discovery_contract_parity.py`
asserts parity with the backend.

## Scheduling

The `pattern_discovery_sweep` worker (materializer role) enqueues one durable
`pattern_discovery.run` job per tenant with analytics events every
`PATTERN_DISCOVERY_INTERVAL_MINUTES`. The idempotency key is the interval
bucket, so a restarted worker never doubles a pass. It is inert unless both
`AETHER_PATTERN_DISCOVERY_ENABLED` and `PATTERN_DISCOVERY_SCHEDULER_ENABLED` are
on, and it re-reads them every pass. The scheduler defaults to on, so a tenant
with discovery enabled gets patterns surfaced with no manual run. On-demand runs remain available through
`POST /v1/intelligence/patterns/runs` and the Kyber equivalent.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `AETHER_PATTERN_DISCOVERY_ENABLED` | `false` | Mounts the tenant, Kyber and 360 section routes; exposes the capability |
| `PATTERN_DISCOVERY_WINDOW_HOURS` | `72` | Evidence window per run |
| `PATTERN_DISCOVERY_MAX_EVENTS` | `50000` | Event cap per run; truncation is reported in `coverage.truncated` |
| `AETHER_PATTERN_RISK_PROMOTION_ENABLED` | `true` | Promotion writes Risk360 signals |
| `AETHER_PATTERN_GRAPH_PROMOTION_ENABLED` | `true` | Promotion writes RiskCluster membership edges |
| `PATTERN_DISCOVERY_GRAPH_MOTIFS_ENABLED` | `true` | Motif discovery reads the tenant's canonical graph |
| `PATTERN_DISCOVERY_ML_ENABLED` | `false` | Score hourly windows with the ML anomaly model |
| `PATTERN_DISCOVERY_SCHEDULER_ENABLED` | `true` | Run discovery for every active tenant on a schedule |
| `AETHER_PATTERN_NOTIFICATIONS_ENABLED` | `true` | In-app notification when a run surfaces high or critical patterns |
| `PATTERN_DISCOVERY_INTERVAL_MINUTES` | `360` | Scheduler interval |

## Known limits

- **Unvalidated precision.** No detector has measured precision or recall on
  labelled production data. The area is 2/5 in `scripts/production_status.py`,
  with a pre-production blocker until a shadow pilot produces calibration
  evidence per kind.
- **Unobserved ML inputs.** p99 latency, sessions and outcomes are only as good
  as the evidence: missing inputs reach the ML model as zeros, and each
  pattern lists them.
- **Bounded reads.** A run reads at most `PATTERN_DISCOVERY_MAX_EVENTS` events
  and 20,000 graph edges. The stats listing and the cross-run context scan up
  to 5,000 and 2,000 patterns per tenant respectively.
