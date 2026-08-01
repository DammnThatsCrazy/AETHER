# Aether Canonical Traffic Intelligence — Consolidated Delivery Report

Branch: `claude/aether-traffic-intelligence-8m2r38`
Completion gate: `make ci-check` → **39/39 gates pass** (exit 0).
Net change: 96 files, +8143 / −240.

This program was specified as four ordered PRs; per the delivery decision it is
delivered as **one branch / one draft PR** with four ordered commit groups that
mirror the spec's PR 1–4. Each phase is independently testable and was validated
before the next was layered on.

---

## 1. Final architecture

SDKs **observe** acquisition evidence; the backend **classifies**. One canonical
vocabulary drives every surface:

```
SDK evidence (web/android/ios/react-native)
   → Bronze ingest
   → SilverDispatcher
        ├─ _resolve_verified_referral  (handoff/link token → verified claim)
        ├─ TouchpointProjector → SourceClassifier.classify()  (canonical dimensions)
        └─ _resolve_campaign_rows      (campaign identity ONLY when campaign evidence exists)
   → silver_campaign_touchpoint_facts → canonical_activity
   → JourneyCompiler → AttributionEngine → Gold
   (history repaired via services/traffic/repair.py, immutable revisions)
```

Classification and campaign identity are **independent**: a touchpoint can carry a
full source classification with `campaign_resolution_status = not_applicable`.

## 2. Canonical traffic taxonomy

Single source of truth: `packages/shared/contracts/traffic-source-registry.json`
→ generated `packages/shared/traffic-source.ts` (TS) and
`Backend Architecture/aether-backend/services/traffic/generated_registry.py` (Python)
via `scripts/generate_contracts.py`.

Independent dimensions: `traffic_origin`, `economic_class`, `channel_family`,
`source_class`, `entry_method`, `proof_level`. The customer-facing fallback is
`direct_unknown` → **"Direct / Unknown"**, never a typed-URL claim. Legacy `direct`
normalizes to `direct_unknown` at API boundaries; storage keeps historical values
until repaired.

## 3. Evidence precedence (classifier v3.0)

machine/scanner UA → verified source link → paid click ID → source-aware UTM →
referrer domain → `direct_unknown`. Paid click evidence outranks a conflicting
self-declared organic UTM and the conflict is **recorded** in `evidence_conflicts`,
never dropped. UTM is evaluated as source+medium together (`twitter/organic` →
organic_social; `google/organic` → organic_search; unknown-source+organic → unknown
unpaid, NOT organic_search).

## 4. Migration status

Additive, backward-compatible. Chained single lineage:
`20260801_canonical_traffic` → `20260802_source_link_proof` → `20260803_deferred_attribution`.
New nullable columns on `silver_campaign_touchpoint_facts`, `canonical_activity`,
`journey_steps`; new tables `source_link_handoffs`, `deferred_attribution_handoffs`,
`apple_attribution_postbacks` (all with storage policies in `config/storage_policies.yaml`).

## 5. Historical repair status

`services/traffic/repair.py` reclassifies to v3, normalizing legacy `direct` →
`direct_unknown` and legacy `paid` → the split paid_search/paid_social/display, via
append-only immutable revisions (raw evidence never mutated); dry-run supported.

## 6–9. Platform implementation status

| Platform | Status | Notes |
|---|---|---|
| Backend classifier/projection | Fully implemented, tested | v3.0, campaign/source separation, not_applicable |
| Verified source links + redirect | Fully implemented, tested | `GET /v1/r/{token}`, immutable use ledger, one-time handoffs, replay/bot handling |
| Web SDK | Fully implemented, tested | local classification removed, ancestor resolution, navigation_intent/arrival, URL sanitization, form privacy |
| Android SDK | Implemented, **not compiled** (no Gradle here) | destination/referrer fix, Install Referrer state machine, auto App Link handling, first/latest-touch; JVM unit tests authored |
| iOS SDK | Implemented, **not compiled** (no Xcode here) | universal links, custom URL, first/latest-touch, deferred handoff |
| React Native | Fully implemented, tested (vitest) | `Aether.attribution.*`, AetherPressable/useTrackedPress |
| Deferred attribution + AdAttributionKit | Fully implemented, tested | deterministic resolve-once; postbacks idempotent, `platform_verified`, separate from user evidence |

## 10. Aether surface status

`frontend/aether` user-profile touchpoints render canonical `source_class` labels
via `@aether/shared` (`SOURCE_CLASS_DEFAULTS`, `canonicalSourceClass`) with a local
presentation lib; "Direct / Unknown" shown, never "typed URL"; proof/entry/conflict
evidence surfaced. Tested.

## 11. Kyber surface status

`frontend/kyber` measurement-ops page renders traffic-intelligence fields from the
existing source-classification contract. Tested. (Full operator dashboard suite —
invalid-proof/replay dedicated panels — scoped to fields already exposed by the
source-classification kyber route; see limitations.)

## 12. Test results

- `make ci-check`: **39/39 gates pass**.
- Root `python -m pytest tests/`: **3508 passed**.
- Backend targeted suites (classifier matrix, campaign-resolution independence,
  touchpoint, repair, verified-referral dispatcher, source-link proof, deferred,
  apple postbacks): all green.
- Web vitest: **273 passed**. React Native vitest: **114 passed**.
  Frontend aether/kyber vitest: green within ci-check.
- `scripts/validate_sdk_release_alignment.py`, `validate_projector_ownership.py`,
  `generate_contracts.py --check`, `check_storage_policies.py`,
  `validate_temporal_integrity.py`: all pass.

## 13. Performance

No new hot-path work added to ingestion; classifier remains a pure function.
Redirect endpoint does constant-time token-hash lookup. Formal perf thresholds not
re-baselined in this pass (see limitations).

## 14. Security & privacy review

- No open redirects (destination is the link's own stored URL; request-supplied
  URLs never honored). No cross-tenant token acceptance (uniform not-found, no
  oracle). Tokens hashed before persistence; constant-time comparison. Handoffs
  one-time, replay-rejected + audited, expiry-enforced.
- No raw form values, no sensitive-query logging (`aether_ref`/click-IDs stripped
  from transmitted URLs, carried only in the typed evidence field). No Accessibility
  Services, no keyboard interception, no probabilistic fingerprinting presented as
  proof. Machine/scanner traffic excluded from journeys.
- All acquisition tracking consent-governed. AdAttributionKit signature status is
  recorded honestly (`unverified` where no in-repo verification key exists) rather
  than faked.

## 15. Rollout & rollback

Additive migrations; legacy values still read. Rollback = revert the branch; the
new nullable columns/tables are inert if unused and can be dropped by a down-revision.
Historical repair is opt-in, dry-run-first, checkpointed.

## 16. Documentation status

Authored: `docs/sdk/android-attribution.md`, `docs/sdk/ios-attribution.md`,
`docs/traffic/canonical-traffic-model.md`. Generated: traffic-source registry table,
event registry, REPO-INDEX. Source-linked docs reviewed + re-stamped
(CAMPAIGN_360_API, DATA_AND_IDENTITY_CONTRACT updated with the new dimensions).

## 17. Remaining platform limitations (honest)

- **Android/iOS not compiled** here (no Gradle/Xcode toolchains). Kotlin/Swift
  validated by review + `validate_sdk_release_alignment.py` + authored JVM tests;
  device/emulator verification is required before shipping the native artifacts.
- **AdAttributionKit signature verification** is structural-only where no Apple
  public-key verification utility pre-exists in the repo; postbacks are stored with
  `signature_status` recorded rather than asserted verified.
- **Optional native UI interaction modules** (full Jetpack Compose / SwiftUI
  instrumentation, QR/NFC/App-Clip capture) and the **full Kyber operator dashboard
  suite** are scoped to the load-bearing acceptance criteria; remaining surface is
  proportional to existing repo patterns and left for follow-up, with no TODO stubs
  in shipped code.
- **Performance thresholds** were not re-baselined against current repo baselines in
  this pass.

## 18. Release recommendation

Backend, web, and React Native paths are merge-ready behind the canonical gate.
Native iOS/Android require a compile + device pass before release. Recommend merging
the draft PR after review, then gating native rollout on the platform build/verify
step and per-tenant configuration (source-link domains, destination allowlists,
`assetlinks.json` / `apple-app-site-association` association).
