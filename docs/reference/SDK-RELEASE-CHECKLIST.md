---
title: SDK Release Checklist
slug: sdks/sdk-release-checklist
section: reference
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: 0.1.0
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# SDK Release Checklist

Process for cutting an SDK release. Publishing is automated via
`.github/workflows/publish-sdk.yml` (npm + CocoaPods + Maven + GitHub Release).

## Checklist

- [ ] Tests green for all SDKs (`@olympuslabs/aether-web` vitest; native build checks).
- [ ] Cross-SDK conformance matrix derives cleanly
      (`python scripts/release/sdk_conformance.py --quiet` — every claimed
      capability cell verified against SDK sources; also enforced by the
      repo-doctor SDK runtime-parity gate).
- [ ] Contracts unchanged or `schema_version` bumped + manifest updated.
- [ ] Per-SDK CHANGELOG entry (Keep a Changelog) + version bump across packages
      (`make bump-version` / the publish workflow).
- [ ] Backward-compatibility notes for any changed event/field.
- [ ] Sample integration verified (Demo App / quickstart).
- [ ] Dispatch a `workflow_dispatch` on `publish-sdk.yml` (use `dry_run` first). A real publish must
      be dispatched from `development`; the version bump is pushed there with the tag.
- [ ] Verify published artifacts: npm (`@olympuslabs/aether-web`, `@olympuslabs/aether-react-native`,
      `@olympuslabs/aether-shared`), CocoaPods (`AetherSDK`), Maven (`com.olympuslabsml:aether-android`).
- [ ] Staged rollout: set `rollout_percentage` in the SDK manifest; monitor
      `sdk_health` / `sdk_drift`; roll back via the manifest if needed.

## Rollback / versioning policy

SDKs follow semver. The signed manifest can pin `min_sdk_version` and roll back
`schema_version` to a previous known-good. See [SDKs](SDKS.md) and
[SDK API Contracts](SDK-API-CONTRACTS.md).
