---
title: Mobile Distribution — profiles, versions, and honest release posture
slug: mobile/distribution
section: mobile
audience: [architect, mobile, release, security]
status: stable
---

# Mobile Distribution

Aether distributes two mobile apps — **Aether** (`apps/aether-mobile`) and
**Kyber** (`apps/kyber-mobile`) — from a single shared SDK
(`packages/mobile-core`) and a single mobile gateway
(`services/mobile/`, `GET /v1/mobile/config`). This document is the
distribution reference: the profile vocabulary, the per-build enforcement,
the version-support policy, and the honest release posture. It does **not**
claim a store submission that has not happened (see
[Honest boundaries](#honest-boundaries)).

The canonical machine-readable source of the distribution vocabulary is
`services/mobile/config.py` (`DistributionProfile`,
`profile_family`, `validate_distribution_profile`, version policy). The
per-build enforcement lives in `scripts/mobile_build_check.py`. The parity
test `tests/contracts/test_mobile_config_parity.py` keeps the two in
agreement, so a doc that drifts from the code would be caught, not trusted.

## Distribution profiles

Every build declares a **distribution profile** for each platform. The
vocabulary is deliberately small and family-scoped:

| Profile | Family | Meaning |
|---|---|---|
| `dev` | both (family-agnostic) | local / simulator / emulator development |
| `testflight` | ios | TestFlight beta build |
| `app_store` | ios | App Store release candidate |
| `play_internal` | android | Play internal-test track |
| `managed` | android | managed / enterprise-managed distribution |

- Values are **snake_case** (wire-contract rule, decision-log D6).
- `dev` is family-agnostic; `profile_family` resolves its effective family
  from the install platform when known.
- `validate_distribution_profile` rejects any value outside this vocabulary,
  so an unknown track name fails fast at config assembly rather than being
  silently accepted.

### Per-build enforcement

`scripts/mobile_build_check.py` **requires** every app scaffold to declare
`expo.extra.distributionProfiles = { "ios": ..., "android": ... }` and fails
the build if either is missing, unknown, or outside the per-platform allowed
set (`DISTRIBUTION_PROFILES` in the checker is drift-guarded against
`services/mobile/config.py` by the contract-parity test). Both shipping apps
currently declare `{ ios: "dev", android: "dev" }`.

The native compile step itself (`expo prebuild` → `xcodebuild` / `gradlew`)
is reported, not silently skipped: when the toolchain is absent, the checker
emits an `externally_blocked` posture and **exits 0** (a missing toolchain is
not a scaffold defect). It never claims a "compiled" artifact.

## Version-support policy

`GET /v1/mobile/config` serves the declared support floor and latest version:

| Value | Current | Meaning |
|---|---|---|
| `min_supported` | `8.10.0` | below this the app is out of support |
| `latest` | `8.12.0` | pinned to the platform version (`pyproject.toml` / app `package.json`, enforced by `scripts/check_version_consistency.py`) |

`upgrade_policy_for(app_version)` derives the policy:

- `app_version < min` → **required**
- `min <= app_version < latest` → **suggested**
- `app_version >= latest` → **none**
- unknown `app_version` → **required** (fail-safe floor — an unversioned client
  is never treated as current)

The module declares the support *policy*; it never re-defines the build
version, so version truth stays in one place.

## `GET /v1/mobile/config`

The route (mobile gateway, flag-gated by `settings.mobile.enabled`) returns a
typed `MobileConfig` with:

- **`app_kind`** / **`environment`** — which app and which backend environment.
- **distribution profile + app version** — the client's declared posture
  (`distribution_profile`, `app_version`), read off its installation row
  (`app_version` / `distribution_profile` persist on the existing
  `mobile_installations` table via the installation repository — no second
  registration table).
- **upgrade policy** — derived per `upgrade_policy_for`.
- **feature_flags** — per-version client feature surface, **all default OFF**;
  version-gated rollout is a future seam, not a fabricated capability.
- **service_capabilities** — a READ-ONLY projection of the existing
  `config/settings.py` flags (mobile_gateway, continuation, client_sync,
  exploration, delivery, command_center, data_quality). No second flag system.
- **externally_blocked_providers** — the honest static mirror of
  `reports/mobile-productization/external-blockers.json` ids. A provider
  listed there is **not live**, and no config claim flips that.

The TS twin (`packages/shared/mobile-config.ts`) mirrors the Python contract
with contract-parity tests, so the wire shape cannot silently diverge.

## Compliance umbrella

`make mobile-compliance-check` bundles the mobile gates:
privacy-manifest-check (`PrivacyInfo.xcprivacy` per app, drift-gated),
dsr-coverage-check (`scripts/release/check_dsr_coverage.py`), mobile
contracts-check (TS↔Python parity), and the SDK/permission inventory gate.
Distribution profiles are part of the same build posture, not a separate
release authority.

## Release workflow (design-partner demo)

For the local/automated demo path:

```make
make design-partner-demo-up      # postgres + backend (migrations applied)
make design-partner-demo-seed    # idempotent seed (notifications, continuations,
                                 #   exceptions, incidents, runs, reviews)
make design-partner-demo-check   # verify seeded state is provenance-clean + API-visible
make design-partner-demo-down    # stop the stack (seeded rows persist; reset via make demo-reset)
```

The demo seeds only in local/test (production is refused; staging requires an
enabled, allow-listed tenant) and never overwrites non-seeded records.

## Honest boundaries

| Capability | State |
|---|---|
| iOS-simulator / Android-emulator compile | `externally_blocked` — needs macOS + Xcode + Android SDK + Expo toolchain; defined to run in hosted (macOS) CI |
| Store submission (App Store / Play review) | `externally_blocked` — developer accounts + signing; no claim of a submitted or live build |
| Live push / email sends | `externally_blocked` — provider credentials; provider-shaped fakes fail closed outside local/dev |
| `dev` builds, local demo, all non-native gates | driven green in `make ci-check` |

Per the production-claims rule, nothing in this document asserts
production-ready distribution; the readiness scorecard
(`scripts/production_status.py`) is the canonical statement, and this doc
defers to it.
