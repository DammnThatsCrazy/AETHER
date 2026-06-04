---
title: SDK Release Checklist
slug: sdks/sdk-release-checklist
section: sdks
visibility: I
audience: [dev-senior, ops]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# SDK Release Checklist

Process for cutting an SDK release. Publishing is automated via
`.github/workflows/publish-sdk.yml` (npm + CocoaPods + Maven + GitHub Release).

## Checklist

- [ ] Tests green for all SDKs (`@aether/web` vitest; native build checks).
- [ ] Contracts unchanged or `schema_version` bumped + manifest updated.
- [ ] Per-SDK CHANGELOG entry (Keep a Changelog) + version bump across packages
      (`make bump-version` / the publish workflow).
- [ ] Backward-compatibility notes for any changed event/field.
- [ ] Sample integration verified (Demo App / quickstart).
- [ ] Dispatch a `workflow_dispatch` on `publish-sdk.yml` (use `dry_run` first).
- [ ] Verify published artifacts: npm (`@aether/web`, `@aether/react-native`,
      `@aether/shared`), CocoaPods (`AetherSDK`), Maven (`com.aether:sdk-android`).
- [ ] Staged rollout: set `rollout_percentage` in the SDK manifest; monitor
      `sdk_health` / `sdk_drift`; roll back via the manifest if needed.

## Rollback / versioning policy

SDKs follow semver. The signed manifest can pin `min_sdk_version` and roll back
`schema_version` to a previous known-good. See [SDKs](SDKS.md) and
[SDK API Contracts](SDK-API-CONTRACTS.md).
