# M11 — Migration, Replay, Backfill, Decommission (Close-Out)

Program: SOCIAL360_RELATIONSHIP_FIDELITY (S360RF)
Milestone: M11 — blueprint §150 (migration/replay/backfill/decommission) + §116-§120 (legacy migration stages)
Status: **implemented — with recorded residuals** (all residual seams are flag-gated OFF and documented below; nothing is claimed that is not in-repo and validated).
Date: 2026-09-04
Canonical gate at close: `make ci-check` (env-stripped) — see M12 report for evidence.

## 1. What M11 closes

M11 is the migration/decommission half of the legacy-social honesty work. The
*eliminate fabricated defaults* stage (G061 / §118) was executed inside M4
(legacy social honesty) and M10 (kyber influence fix); M11 records the
classification outcome, the decommission ledger, the replay/backfill posture,
and the acceptance evidence for §150. Where M11's blueprint scope names work
that would change **active customer paths while the social360 surface is
flag-gated OFF**, that work is recorded as deferred-to-activation with the
precise seam (D-04, D-05) rather than executed speculatively.

## 2. Decommission ledger

| Artifact | Disposition | Milestone | Evidence |
|---|---|---|---|
| `services/social/social_aggregator.py` | **Deleted** (legacy fixed-overlap + fabricated-default source) | M4 | file absent; M4 tests 14/0; legacy-scan validator (M12) finds no idioms |
| `gold_social_intelligence` DDL | **Deleted** (dead/redundant social-gold DDL) | M4 | file absent |
| Fixed cross-platform audience overlap `0.20 / 0.15 / 0.25` in the authority path | **Removed** | M4 | routes.py re-written as legacy wrapper over canonical aggregator; `audience_summary` no longer synthesized from fixed constants |
| `/v1/profile/{id}/social-intelligence` empty stub shadowing real handler | **Resolved** — reclassified as a legacy wrapper delegating to `IntelligenceAggregator.social_intelligence` | M4 | routes.py; defect `social_stub_shadows_real_handler` closed |
| kyber `influence = "low"` + `verified: False` fabrication on unknown data | **Fixed** — unknown remains unknown | M4/M10 | kyber social-intelligence-panel honesty fix; M10 tests 35/0 |
| `services/social/` legacy surface | **Retained as compatibility wrapper** (decommission continues only under social360-surface activation; §150 requires no *active* customer path change off-flag) | M11 | this report, D-05 |

## 3. Classification outcome (G061 / §116-§120)

Full inventory: `LEGACY_SOCIAL_TRUTH_MATRIX.md` (M0).
Classification applied per §117-§119:

- **Kill** — fixed-overlap aggregator, gold DDL (see ledger above).
- **Wrap (compat contract)** — legacy social route now a thin wrapper over the
  canonical aggregator; legacy payload shape (SocialTab) preserved for
  downstream consumers; field-level deprecation is a documented surface concern,
  deferred to activation (D-05) because flipping it off-flag changes active reads.
- **Keep honest** — unknown influence/engagement/following now propagates as
  *unknown*, never `0` / `"low"`.

No active customer path relies on fixed-overlap assumptions or fabricated
defaults (verified below). **Zero fabricated-default remnants** were found in the
governed social surfaces by both the manual grep (M11 acceptance check) and the
new CI validator `scripts/validate_social360_guardrails.py` (M12, gate #64).

## 4. Migration — why no runtime data migration this slice

All new projection state (silver social facts, incentive context, motifs,
relationship fidelity, path fidelity, lenses) is written only by flag-gated
components that are **OFF** (`AETHER_SOCIAL360_ENABLED=false` etc. —
`rollout_controls` in PROGRAM_STATE.yaml). Nothing in the new plane has produced
rows in a tenant graph, so there is no on-disk state to migrate and no schema
cutover to sequence. Migration is therefore an **activation-time** activity: the
first surface activation under `AETHER_SOCIAL360_ENABLED` runs the silver
normalizer forward and then reconciles against the legacy wrapper output before
shadow → warn → enforce promotion (§121-§122 modes). Recording this now keeps
the ledger honest: "migration not required yet" is true, and the activation
gate is named.

## 5. Replay / backfill posture

- **Replay-safe raw-before-canonical flow** is present on the substrate
  (`raw_store` + sync; bronze → silver pattern G019) and was used for the
  silver-plane tests (M3, 61/0).
- **Historical reconstruction/backfill** (§119) of social evidence from archived
  raw data is **deferred to activation**: the legacy raw corpus is not replayed
  into the silver plane while the plane is OFF, because doing so would write
  projection rows a surface never reads and would predate the consent gate that
  social360-surface activation will require (D-05). The seam is recorded;
  nothing about backfill is fabricated as done.
- **Fidelity recompute/restatement** (G033 §47-§50): recompute triggers +
  bitemporal restatement conventions exist (M7/M8). Relationship-fidelity
  recompute firing is bound to the fidelity runtime call chain, which has **no
  caller today** (D-04) — see residual seams below.

## 6. Shadow / comparison

Feature flags default OFF with `[off, shadow, warn, enforce]` modes (§121-§122,
G062). No shadow-mode dual-write is running this slice; dual-run comparison is
the activation sequence's step one. Nothing here is silent-fail: the guardrail
validator and the M2-M10 test suites are the standing sentinels until then.

## 7. Compatibility contracts (legacy → canonical)

`services/social/routes.py` is the single compatibility surface: it preserves
the legacy `/v1/.../social-intelligence` read shape while delegating computation
to `IntelligenceAggregator.social_intelligence` (the canonical aggregator).
`IntelligenceAggregator` enforces read permission; the consent model
(`social360.requiresHistoricalConsentEvaluation`) is intentionally **not** yet
gated on this route (D-05).

## 8. Acceptance evidence (§150)

> Acceptance: *no active customer path relies on fixed overlap assumptions or
> fabricated defaults.*

- Manual scan of governed social sources: only honest documentation strings
  remain (e.g. `routes.py` documents "never `followers = 0` …", and
  `services/exploration/adapters/social360.py` returns `provider_unavailable`
  rather than synthesized metrics).
- Machine scan (M12 validator, token-stripped so documentation cannot
  self-trigger): **42 governed files, 0 idioms** — `make ci-check` gate #64.
- Dead-code deletion verified by `git` absence of the two removed artifacts.

## 9. Residual seams recorded (not runtime-wired by this program)

| Id | Seam | Where it is named | Why not bridged here |
|---|---|---|---|
| D-04 | M6↔M7 evidence-independence resolver (`services.relationship_promotion.evidence_independence::resolve_independent_groups`) | PROGRAM_STATE.yaml, M7 module docstring | Forcing a coarse bucket bridge would fabricate an independence answer below M6's authoritative endpoint-aware grouping. Fidelity is OFF; no caller invokes it. |
| D-05 | Historical-consent evaluation on legacy social reads | PROGRAM_STATE.yaml | Flipping a consent gate now changes legacy API behavior outside the social360 flag; belongs to surface activation. |
| D-OPEN (G017) | Olympus corpus → tenant overlay projection rule (§14) | PROGRAM_STATE.yaml | Unresolved by design; must be resolved + documented (or recorded EXTERNALLY_BLOCKED) **before** corpus-derived relationships are written to the tenant-scoped graph. No corpus-derived graph writes exist today, so this does not block any active path. |

**D-OPEN disposition for M11**: recorded `unresolved`; re-asserted as a
pre-corpus-write gate. It is not closed by this milestone because it is an
*upstream-domain* decision (tenant-scoped projection of the Olympus corpus),
not a social360 migration defect. It will be resolved when the corpus→tenant
projection is implemented; until then no corpus-derived relationship is written.

## 10. Definition of done for M11

- [x] Decommission ledger recorded (this report).
- [x] Legacy classification outcome recorded (this report + LEGACY_SOCIAL_TRUTH_MATRIX).
- [x] Migration/replay/backfill posture honest and precise (this report).
- [x] Compatibility contract named (routes.py legacy wrapper).
- [x] §150 acceptance evidenced by scan + new CI validator.
- [x] Residual seams D-04/D-05/D-OPEN recorded with the exact future seam.
- [x] No fabricated-default / fixed-overlap idiom in any governed social source.
