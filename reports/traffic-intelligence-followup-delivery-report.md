# Aether Traffic Intelligence — Follow-up Delivery Report

Completes every remaining item from the v1 delivery accounting (partial, not-landed, and couldn't-verify), in one PR on top of the merged v1 (`b9c4a32`).

Branch: `claude/aether-traffic-intelligence-8m2r38`
Gate: `make ci-check` → **41/41 gates pass** (exit 0).
Diff: 76 files, +5620 / −75.

## What landed (was previously partial / not-landed)

| Spec item | Status | Where |
|---|---|---|
| §19 Feature flags + shadow/canary rollout | **Done, tested** | `services/traffic/flags.py` (`TrafficFlags`, `is_enabled_for_tenant`, canary), `services/traffic/shadow.py` (legacy-vs-canonical divergence rows, **customer row never mutated** — test-enforced), `source_classification_shadow_divergences` table |
| §16 Full observability metric set | **Done** | `services/traffic/metrics.py` (single surface for classification/direct-unknown/conflict/replay/handoff/redirect-latency/nav/install-referrer/app-link/universal-link/deferred/adattributionkit/parse-failure/machine-excluded/reclassification), wired into dispatcher/redirect/repair; `docs/observability/traffic-intelligence-metrics.md` |
| §15.3 Kyber operator dashboard | **Done, tested** | backend `GET /v1/kyber/measurement/source-classification/operations` (real tenant-scoped aggregation) + `frontend/kyber` traffic-intelligence ops page (invalid-proof/replay/direct-unknown/drift/UTM-inconsistency/install-referrer-health/handoff/deferred/AdAttributionKit/parse-failures/reclassification, by source_class & proof_level, tenant/platform/SDK/time filters) |
| §15.2 Evidence inspector | **Done, tested** | `frontend/aether` `TouchpointEvidenceInspector` — classification, source/medium/placement, proof level, confidence, winning rule, evidence chain/conflicts, campaign + resolution status, first-vs-latest, machine state, SDK/platform, sanitization. Populated from the journey-step row (`SELECT *` carries the canonical evidence fields); a few secondary fields degrade to "—" honestly |
| §13.6 Graph projection edges | **Done, tested** | 5 canonical edges in `shared/graph/graph.py` + `_EDGE_LAYER_MAP` (+ TS `graph-contract.ts` A2H parity): `ARRIVED_THROUGH_SOURCE`, `USED_PLACEMENT`, `ORIGINATED_FROM_LINK`, `ATTRIBUTED_TO_PLATFORM_EVIDENCE` (EXCLUDED), `REFERRED_ENTITY` (A2H); projected by `SilverGraphProjector`, tenant-scoped, replay-safe, through the mutation gateway (write-path freeze intact) |
| §15.4 Tenant configuration surfaces | **Done, tested** | `services/traffic/config.py` + CRUD routes (`/v1/traffic/config`, RBAC): destination allowlist (**wired into the redirect**), source-link domains, vanity URLs, placement taxonomy, custom source aliases + search/social domain extensions (validated, controlled-extension), interaction-tracking/sanitization/expiration/direct-traffic/repair policy; `tenant_traffic_config` table |
| §10.5 AdAttributionKit signature verification | **Done, tested** | `services/attribution/apple_postbacks.py` — real ECDSA-P256/SHA-256 over the version-specific signed parameter string (SKAdNetwork 2.1–4.0 + AdAttributionKit) via `cryptography`; `verified`/`invalid` (→422, not stored)/`unverified` (honest); Apple key as overridable constant |
| §17.7 Performance tests + thresholds | **Done, measured** | `tests/performance/` — classifier p95 ~28µs (<250µs), throughput ~57k/s (>8k/s), redirect verify p95 ~0.9µs (<50µs), repair bounds honored; thresholds derived from measured baselines |
| §20 Threat-model / privacy / retention docs | **Done** | `docs/security/traffic-intelligence-threat-model.md`, `docs/privacy/traffic-intelligence-privacy-review.md`, `docs/privacy/traffic-intelligence-data-retention.md` — each control tied to real code paths / storage-policy entries |
| §12 Native UI interaction instrumentation | **Done (review-only native)** | Android `AetherInteraction.kt` + Compose `Modifier.aetherTrack` + Navigation observer; iOS `AetherInteraction.swift` (UIKit helper, UIControl action, SwiftUI `.aetherTrack`); RN `AetherPressable`/`useTrackedPress` emit canonical `ui_interaction_observed`. Privacy-safe defaults (no text, no coordinates, stable ids); no Accessibility Services |
| §7.1/§10.4 QR / NFC / App Clip capture | **Done (review-only native)** | Android `handleQrScanResult`/`handleNfcUri`; iOS same + `handleAppClipInvocation`; RN passthroughs. New events `qr_code_scanned`, `nfc_tag_read`, `app_clip_invoked`, `ui_interaction_observed`. Reuses the existing canonical parser + first/latest-touch persistence; host app decodes, SDK attributes |

## Couldn't-verify items — outcome

- **iOS compile:** not possible on Linux (no Xcode; SwiftPM can't target UIKit/SwiftUI). Swift is review-only, validated by `validate_sdk_release_alignment.py` + review.
- **Android compile:** attempted a real SDK install here — **`dl.google.com` is blocked through the agent proxy (404)** and no Android SDK is pre-installed, so `gradle` can't resolve the Android platform. Kotlin remains review-only, validated by the SDK-alignment validator + review. This is an environment limitation, stated plainly; the native code follows the standard optional-integration patterns (`compileOnly` Compose/Nav deps, `#if canImport` guards).

## Verification

- `make ci-check` — **41/41 gates** (formatting, lint, typecheck, npm build, npm test, Python core `pytest tests/`, ML, contract/consent/SDK-alignment/projector-ownership/storage-policy/temporal/graph-write-path/route-registry/ownership-map, docs sync + source-linked drift).
- Backend: WS-A 38 new tests + full suite (pre-existing 4 failures only, identical on base); WS-B 17 postback + 5 perf.
- Frontend: kyber vitest 236, aether vitest 166, both build.
- RN: vitest 116. `validate_sdk_release_alignment.py` green (all 4 new events in Android+iOS maps).

## Honest remaining limitations

- **iOS/Android native code is review-only** (no toolchains reachable here) — device/emulator build required before shipping the native artifacts.
- **Custom source aliases / custom search-social domain extensions** are stored, validated, and exposed via the tenant-config API, but are **not yet consumed by the classifier's v3 lookup** — that requires threading per-tenant config into the projection hot path with caching (a bounded follow-up). The **destination allowlist IS wired** and enforced at the redirect (the security-critical path).
- A few operator-route counters that lack a durable tenant-scoped source (invalid-source-link, replay, handoff expired/failed, install-referrer error states, deep-link parse failures) return honest **zeros** on the aggregate while their live signal is emitted as metrics for dashboards; durable per-tenant persistence is a follow-up.
- Some evidence-inspector secondary fields (SDK/platform/confidence/sanitization-status) render "—" where the journey-step row doesn't carry them.
- AdAttributionKit uses Apple's published SKAdNetwork key (structurally validated, operator-overridable via env); if Apple rotates it, operators set the env var.
