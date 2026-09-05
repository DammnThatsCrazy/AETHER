# Social360 + Relationship Fidelity — LEGACY SOCIAL TRUTH MATRIX

Milestone M0 deliverable (blueprint §116 inventory + §117 classification). Every legacy social
component is classified **REUSE | EXTEND | MIGRATE | COMPATIBILITY_WRAPPER | DEPRECATE |
DELETE_AFTER_CUTOVER | EXTERNAL_BLOCKED** (exactly one, with recommended owner milestone).
Evidence collected 2026-09-03. Absolute paths in §8 reference list.

## 0. Key architectural findings (read first)

1. **The live social endpoint is an empty stub.** `GET /v1/profile/{id}/social-intelligence`
   is served by `services/social/routes.py:24` (`get_social_intelligence`), which returns
   hardcoded empty `items` + `summary = {total_followers_deduped:0, influence_level:"low",
   engagement_rate:0.0, platforms_connected:[]}`. It is mounted BEFORE the profile router in
   `main.py:909-911` and therefore **shadows** the real handler
   (`services/profile/routes.py:1088` → `IntelligenceAggregator.social_intelligence`,
   `profile/intelligence.py:337`). `main.py`'s comment claiming the social_router is "richer"
   is false.
2. **`services/social/social_aggregator.py` is dead code.** `SocialAggregator` is never
   imported anywhere; its dependency `identity_repo.get_social_handles(...)` has **no
   implementation** in the repo. This is where the fixed cross-platform overlap percentages
   live (§12 targets).
3. **Fixed overlap assumptions** (`social_aggregator.py:36-47`): `_OVERLAP_WITHIN_VIDEO=0.20`,
   `_OVERLAP_CRYPTO_NATIVE=0.15`, `_OVERLAP_INSTAGRAM_TIKTOK=0.25`; dedupe math
   `int(x*0.85)`, `int((yt+tt)*0.80)`, `int(ig*0.75)` (`:510-535`). No identity bridging code
   exists despite docstring claims.
4. **Fabricated defaults** pervade the legacy path: `.get(...,0)`/`int(...0)` in every
   fetcher (`social_aggregator.py:175…478`), hardcoded `followers=0` for Discord (`:409`),
   stub zeros (`services/social/routes.py:47-49`), `avg_engagement ... else 0.0`
   (`profile/intelligence.py:550`), and `"verified": d.get("verified", False)`
   (`intelligence.py:354`). The repo's own "unknown never 0" standard is already enforced in
   the profile/economic dimension-state path (`shared/dimension_state.py`,
   `profile/read_result.py`, `profile/economic.py:_decimal`), so legacy social is an outlier.
5. **Two different "gold social" artifacts**: `Data Lake Architecture/schemas/
   gold_social_intelligence.py` (a ClickHouse DDL, non-bitemporal, NOT imported anywhere) vs.
   the LIVE gold store used by the endpoint — `GoldRepository("social_intelligence")`
   (`repositories/lake.py:611`, keyed metric rows). `gold_social = GoldRepository("social")`
   (`lake.py:584`) is separate, used by `composer._compose_lake_data`.
6. **Aether SocialTab consumes a shape no backend produces**: `frontend/aether/.../
   user-profile-page.tsx:1029-1099` reads top-level `platforms[]` + `content_count`, which
   neither the stub nor `IntelligenceAggregator.social_intelligence` (which returns `items[]` +
   `summary.platforms` as a list of strings) emits. Speculative/unwired contract.
7. **Social providers are catalogued but off-UPR**: `services/provider_catalog/catalog.py`
   — `twitter_x`/`reddit`/`telegram_bot`/`discord_bot` are `DISABLED_COMPLIANCE_REVIEW`
   (`RiskTier.HIGH`; telegram/discord flagged "surveillance-sensitive"), `farcaster_neynar`/
   `github_api` are `CREDENTIAL_GATED`, `lens_protocol` `SCAFFOLDED`, `ens_public`/`snapshot`
   public. None route through `provider_runtime`.
8. **Consent gap**: social route/aggregator paths only call `require_permission("read")`
   (`services/social/routes.py:31`, `profile/routes.py:1096-1098`); no consent gate, though the
   registry declares `social360.requiresHistoricalConsentEvaluation: True` and
   `exportClass:"governed"` (`shared/intelligence_projections/generated_registry.py:1107-1109`).
   Contrast the `web2` method which gates on `credit` consent (`profile/intelligence.py:516-577`).
9. Registry `social360` legacy binding: `legacyBindings.services = ("services/social",)`,
   `migrationMode:"adapter"`, `migrationBlueprint:"docs/blueprints/social360.md"` (file does not
   exist yet — this program will author it in M1).

## 1. Component → classification matrix

| Legacy component | Where | What it is today | §117 classification | Owner milestone |
|---|---|---|---|---|
| Social stub route | `services/social/routes.py` (`get_social_intelligence`) | Empty stub fabricating zero/low; shadows real handler | **MIGRATE** → **COMPATIBILITY_WRAPPER** (delegate to Social360) → **DELETE_AFTER_CUTOVER**; fix mount-order defect in M4 | M4 |
| Real handler | `services/profile/routes.py:1088`, `profile/intelligence.py:337` | Aggregator-backed social_intelligence (no consent gate) | **COMPATIBILITY_WRAPPER** onto canonical Social360 dimension | M4 |
| Aggregator | `services/social/social_aggregator.py` | Dead code; fixed overlap %; fabricated zeros; `influence_level` thresholds | **DELETE_AFTER_CUTOVER** (never referenced). Do NOT re-adopt its heuristics (§12/§118). | M4 |
| Social Gold (live) | `repositories/lake.py:611` `GoldRepository("social_intelligence")` | Keyed metric-row gold the endpoint reads | **EXTEND** per §57 "reuse existing gold where migration is safer"; reconcile with semantic/relationship Gold ownership | M4 |
| Social Gold DDL | `Data Lake Architecture/schemas/gold_social_intelligence.py` | Non-bitemporal ClickHouse DDL; **not imported** | **DEPRECATE** (dead schema) unless M4 decides DDL migration is the safer reuse path (§57) | M4 |
| TS contract | `packages/shared/social-intelligence.ts` (`SocialProfile`) | `total_followers_deduped`/`influence_level`/`engagement_rate`/`platforms_connected` | **COMPATIBILITY_WRAPPER** + deprecation metadata (§56); new canonical Social360 section added alongside | M1 + M4 |
| Kyber social panel | `frontend/kyber/.../social-intelligence-panel.tsx` | Reads `items[]`+`summary`; fallback `influence_level:'low'` | **MIGRATE** to canonical Social360 payload (M10), interim compatibility in M4 | M4 + M10 |
| Aether SocialTab | `frontend/aether/src/pages/user-profile/user-profile-page.tsx:1029` | Consumes speculative top-level `platforms[]` shape no backend emits | **MIGRATE** (rebuild against canonical contract); record shape-mismatch defect | M10 |
| Profile360 contract | `packages/shared/profile360-contract.ts:207` `social_intelligence?` | Field on profile contract | **COMPATIBILITY** (deprecate) → replaced by canonical section | M1/M10 |
| Provider catalog entries | `services/provider_catalog/catalog.py` (twitter/reddit/telegram/discord/farcaster/lens/github/ens/snapshot) | Compliance states already honest (`DISABLED_COMPLIANCE_REVIEW`, `CREDENTIAL_GATED`, `SCAFFOLDED`) | **EXTEND** onto UPR social capability registration (M2); keep compliance states | M2 |
| Social capability registry | `shared/intelligence_projections/generated_registry.py:1073-1132` (`social360` entry) | `in_flight`, `migrationMode:adapter`, requiresHistoricalConsentEvaluation | **REUSE** — the reserved projection contract this program implements | M1 |
| `identity_repo.get_social_handles` | referenced `social_aggregator.py:82,107,166` | **No implementation exists** | **DEPRECATE** (delete with aggregator) | M4 |
| Legacy tests | `tests/profile360/test_intelligence_endpoints.py` `TestSocialIntelligence` (2 tests) | Cover aggregator handler only | **MIGRATE** → canonical Social360 tests (§133) | M4 |
| Router mount + comment | `main.py:906-911` | False "richer responses" comment; stub shadows real handler | **MIGRATE** (remove stub mount; wire canonical route) | M4 |
| `main.py`/worker supervision | `main.py`, worker roles | Runtime supervision exists (other domains) | **EXTEND** for §59 worker roles where absorbable | M3/M6/M7 |

## 2. Pre-existing defects discovered (blueprint §2 record — not hidden, not absorbed)

```text
defect: stub social-intelligence route shadows the real aggregator handler and returns
       fabricated zeros/lows; main.py comment claims the opposite.
source path: services/social/routes.py; main.py:906-911 (mount order)
impact: any client of GET /v1/profile/{id}/social-intelligence receives empty/fabricated
       data instead of the aggregator or a consent-gated result.
depends on repair? yes — M4 legacy honesty migration is blocked on removing the stub shadow.
recommended follow-up: fix within this program's M4 (attributed to social360); do not
       opportunistically rewrite other social surfaces in the same change.

defect: Aether frontend SocialTab consumes a payload shape (top-level platforms[] +
       content_count) that no backend route produces.
source path: frontend/aether/src/pages/user-profile/user-profile-page.tsx:1029-1099;
       frontend/aether/src/lib/api/endpoints.ts:1891-1908
impact: the customer-facing social tab can never be populated as written.
depends on repair? yes — M10 surface wiring.
recommended follow-up: rebuild SocialTab against the canonical Social360 contract in M10.

defect: declared gold schema (gold_social_intelligence DDL) is dead and non-bitemporal;
       the live social gold is a metric-row GoldRepository — the declared storage and the
       actual storage disagree.
source path: Data Lake Architecture/schemas/gold_social_intelligence.py vs repositories/lake.py:611
impact: schema-of-record drift; no valid_from/valid_to for §48 temporal reconstruction.
depends on repair? yes — M4/M11 temporal + storage model.
recommended follow-up: M4 decides single gold path (§57), M11 backfill/replay.
```

## 3. Reference file list (absolute paths)

`services/social/{routes.py, social_aggregator.py, __init__.py}` · `services/profile/{routes.py,
intelligence.py, composer.py, economic.py, read_result.py}` · `shared/dimension_state.py` ·
`repositories/lake.py` · `services/provider_catalog/catalog.py` ·
`shared/intelligence_projections/generated_registry.py` · `main.py` ·
`tests/profile360/test_intelligence_endpoints.py` ·
`Data Lake Architecture/schemas/gold_social_intelligence.py` ·
`packages/shared/{social-intelligence.ts, targeting-intelligence.ts, profile360-contract.ts,
entity-extensions.ts}` · `frontend/kyber/src/components/profile360/{social-intelligence-panel.tsx,
profile360-view.tsx}` · `frontend/kyber/src/lib/api/endpoints.ts` ·
`frontend/aether/src/pages/user-profile/user-profile-page.tsx` ·
`frontend/aether/src/features/users/use-user-profile.ts` ·
`frontend/aether/src/lib/api/endpoints.ts` (all under `/Users/osazehunt/AETHER/`,
`Backend Architecture/aether-backend/` for the Python paths above).
