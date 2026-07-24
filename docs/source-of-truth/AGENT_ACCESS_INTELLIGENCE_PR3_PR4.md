# Agent Access Intelligence — PR 3 & PR 4: Providers, Reconciliation, Graph, Surfaces

**Release train:** `AGENT_ACCESS_INTELLIGENCE`
**Scope:** PR 3 (`AAI-3-*` — provider framework, provider evidence, reconciliation, reference
packs) and PR 4 (`AAI-4-*` — access graph, profiles/journeys, Noesis alerts & exports, Kyber
operator surface, Aether tenant UI, GA hardening).
**Status:** implemented. Every `AAI-3-*` and `AAI-4-*` ledger item is
`implementation_in_progress` with an explicit exception rather than a terminal status —
the work is built and tested, but `make ci-check` green is not production evidence, and
`scripts/production_status.py` remains the only thing that may say otherwise.

Builds on PR 1 (canonical ingestion spine) and PR 2 (capability catalog, authority, policy,
identity, drift, blast radius).

---

## 1. The finding that shaped both PRs

Three substantial modules in this subsystem were already written, already tested, and
**imported only by their own tests** — dead in production:

| Module | Size | Only importer before this work |
|---|---|---|
| `services/agentic_observability/provider_framework.py` | 386 lines | `tests/unit/test_agentic_provider_framework.py` |
| `services/agentic_observability/governance.py` | — | nothing |
| `services/noesis/adapters/agentic_intelligence_adapter.py` | — | `tests/unit/test_agentic_noesis_adapter.py` |

This is PR 1's original sin — a fully-built pipeline whose entry point is never called —
repeated three more times. The bulk of PR 3 and PR 4 is therefore **wiring, not writing**:
each lane was judged on whether its subsystem is reachable from a mounted route at the end,
proven by a test that goes through the real call path.

A module that is tested but unreachable passes CI forever while delivering nothing. Tests
are not evidence of reachability; a route is.

---

## 2. Surfaces added

All tenant routes read `request.state.tenant`, gate on `require_permission("read"|"write")`,
and fail closed on cross-tenant access. All are registered in `config/route_registry.yaml`.

| Route | Item |
|---|---|
| `GET /v1/capability-providers/adapters` | AAI-3-PROVIDER-FRAMEWORK |
| `POST,GET /v1/capability-providers/evidence` (+ `/{id}`) | AAI-3-PROVIDER-EVIDENCE |
| `GET /v1/capability-providers/permission-findings` | AAI-3-PROVIDER-FRAMEWORK |
| `GET /v1/capability-reconciliation` (+ `/pipeline-health`, `/lineage/{id}`) | AAI-3-RECONCILIATION |
| `GET /v1/capability-graph/{neighborhood,summary}` | AAI-4-GRAPH |
| `GET /v1/capability-profiles` (+ `/{agent_id}`, `/{agent_id}/journey`) | AAI-4-PROFILES-JOURNEYS |
| `GET /v1/capability-alerts/{evaluate,export}` | AAI-4-NOESIS-ALERTS-EXPORTS |
| `GET /v1/kyber/capability-ops/{authority,drift,blast-radius}` | AAI-4-KYBER-OPS |

`/v1/kyber/capability-ops` needs **no** registry entry: any path containing `/kyber`
auto-classifies as operator + audit + high risk. A test asserts that classification rather
than assuming it, so a change to the rule fails loudly instead of shipping an unclassified
operator route.

Frontends: `/agent-access` in both Aether (tenant) and Kyber (operator). Both are routable
but **not yet linked in nav** — nav files are shared surfaces and were left to their owners.

---

## 3. Decisions that were refused

Recording these because each is a thing the monoprompt could be read as asking for, and
each would have produced something that looks like a feature and behaves like a lie.

- **No net-new provider-neutral event types.** PR 1 deferred
  `capability_discovered` / `capability_invocation_observed` / `provider_action_confirmed`.
  They stay deferred: nothing emits them, and registering contract surface that no producer
  writes is the same dead-code failure this PR spent its budget removing. The full
  contract-generation cost buys an empty registry entry.
- **No third-party vendor reference packs.** Nothing in this repo establishes the scope
  vocabularies, endpoints, or tool names of Stripe, Slack, GitHub, or anyone else. An
  invented baseline is precisely the input that silences a real `unexpected_new_scope`
  finding — a fabricated pack is worse than no pack. Two grounded packs ship
  (`x_reference` from the in-repo adapter, `mcp_generic` from this repo's own MCP
  vocabulary) plus one clearly-labelled `example` template. Both grounded packs assert
  **no** baselines (`baseline_status: none_asserted`), which is fail-loud: every observed
  scope is reported for review rather than silently approved.
- **No `verified` state anywhere.** Provider evidence is *provider-attested*. This backend
  still cannot authenticate a third-party publisher, and the word would be read by an
  operator as "someone checked".
- **No blocking risk threshold in alert rules.** `policy_engine.py` deliberately defines
  none, with the reasoning recorded in-code. Alert rules are declarative and the rule, its
  threshold, and the observed value all appear in the response — a hidden constant would
  read as platform policy.
- **No notification delivery wired to the default rules.** Paging an operator off a default
  threshold nobody authored is the fabricated-control failure again. Delivery belongs behind
  a tenant-authored rule set.
- **No composite risk or trust score.** Observed risk levels roll up as counts by level. A
  number an operator cannot trace is worse than the raw counts.
- **The access graph is not a Silver projector.** It is a table→table derivation, and
  forcing a dispatcher projector in would touch four CI-guarded ownership artifacts for no
  benefit — the same reasoning that kept the Phase A catalog out of that path.

---

## 4. Defects found and fixed in the code that became reachable

Making dead code live turns its latent bugs into real ones. Everything below was found by
review once the module had a caller.

**`provider_framework.compute_permission_findings`**
1. Compared ISO instants **lexicographically** against `utc_now().isoformat()`. A stored
   `…Z` value sorts after the identical moment written `…+00:00`, so an already-expired
   grant never reported `expired_grant` and a post-revocation action never reported
   `revoked_grant_used` — the two highest-severity findings the function exists to produce,
   silently absent. (Same bug class as the `ends_at` defect fixed in `authority.py`.)
2. Matched agentless records against each other via `None == None`, fabricating
   `revoked_grant_used` findings between unrelated rows. Attribution now requires an
   identified agent on both sides, and excluded records are counted in the response.
3. Action window is bounded and the **effective** cap disclosed. The cap was previously
   checked only between installations, so a single installation could overshoot it entirely
   and — when the tenant had just one — never disclose the truncation at all.

**`agentic_observability/reconciliation.py`**
4. `pipeline_health` returned `health: "healthy"` for **every tenant, always**. Every
   medallion table it counts lost its writer when PR 1 delegated agentic observation to the
   canonical spine, so all counts are 0 and the old expression read 0-failures as healthy.
   Zero observed rows is now `unknown` with a stated basis. *An empty pipeline reported as a
   healthy one is the most misleading output an operations surface can produce: it is
   indistinguishable from a working one.*
5. `reconcile()` appended a phantom gap with an empty id for any row lacking an
   `observation_id`, and reported a windowed pass as a complete one.

Known and **not** fixed here, recorded so they are not rediscovered as new: the adapter's
own answers carry no truncation disclosure and state bounded counts as complete facts;
`XReferenceAdapter.consume_webhook` skips HMAC verification when the secret or signature
header is absent (fail-open, currently unreachable — no webhook route exists);
`build_provider_graph_projection` and `PROVIDER_TRUTH_PRECEDENCE` remain dead.

---

## 5. GA hardening (`AAI-4-GA-HARDENING`)

**Performance is bounded reads, not a quota system.** Every AAI surface reads through an
explicit window and *discloses when that window was hit*; no new quota mechanism was
invented, because an undisclosed bound is the actual failure mode and a quota would not fix
it. Two performance defects were removed rather than tuned: the authorization split in
`risk_service` was issuing ~400 sequential uncached round-trips on one read-gated GET (now
one bounded query matched in memory), and `compute_permission_findings` is O(grants × actions)
with an unbounded action list (now capped and disclosed).

**Evidence.** `scripts/release/collect_evidence.py` now includes
`agent_access_reference_packs`. A malformed or missing pack silently removes a provider's
approved-scope baseline, after which the permission surface reports no scope violations for
that provider — a false all-clear, which is exactly what an evidence bundle exists to rule
out. `make validate-reference-packs` is wired into `repo_doctor`, so it runs in `ci-check`.

**The invariant every surface in this subsystem holds, and what it cost to hold it:**

> Unknown is never reported as zero. A count that could not be computed is `null` with an
> explicit `missing_inputs` reason; a bounded read that was hit says so; `authorized` is
> tri-state and never defaults to `false`.

This has now been violated and repaired **five separate times** across PR 2, PR 3 and PR 4 —
in the authorization split, in `digest_map`, in `counts.scope`, in `pipeline_health`, and in
the two UI lanes that had to refuse to render `null` as `0`. It is the single most
load-bearing and most consistently re-broken rule in this package, which is why it is stated
here rather than left implicit.

---

## 6. Known gaps

- `/v1/capability-catalog` and `/v1/capability-installations` return `count` as the **page
  length** with no `truncated` / `counts.scope`, unlike every sibling surface. A tenant with
  4,000 capabilities and a default `limit` sees `count: 100`, which reads as an inventory
  total. Both UI lanes had to work around it. This should be brought in line with
  `list_profiles`; it is a PR 2 surface and was left un-widened here deliberately.
- `count_by_state` returns real counts *alongside* `truncated: true`; a caller rendering
  `counts` directly prints a confident partial number. The Kyber aggregator nulls them, but
  the shape invites the bug.
- `catalog_health()`'s tenant list is `Counter.most_common(20)` with no `tenants_truncated`
  flag — cross-tenant tenant discovery is silently ranked-window-only.
- `_upsert_installation` drops the agent↔server binding when either side is absent, with no
  counter and no log, so an agent emitting only serverless `provider_action` facts is
  invisible to every installation-based surface.
- `_server_key` now exists in three places that must agree; one of them will drift.
- `scripts/docs_drift.py` treats an unresolvable `last_synced_commit` as clean, disarming
  staleness detection for 105 of 199 source-linked docs (pre-existing; see PR 2 §6c).
