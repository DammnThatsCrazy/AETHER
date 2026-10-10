---
title: SDK Release Readiness Report
slug: sdks/release-readiness-report
section: reference
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: 0.1.0
canonical_owner: sdk@aether
estimated_read_minutes: 6
---

# SDK Release Readiness Report — 1.0.0-alpha.0

## Release alignment

The first external SDK release target is **1.0.0-alpha.0**. The repository
platform and package source currently remain at `0.1.0-alpha.0`; the manual
`publish-sdk.yml` workflow applies the explicit `1.0.0-alpha.0` release version
across the publishable SDK packages and native artifacts immediately before
publication. No package is advertised as published until that workflow has
completed its dry run, required credentials are present, and the publish jobs
finish successfully.

Aether SDK uses `packages/shared` as the canonical contract source for event
types, consent purposes, schema metadata, health payload shape, wallet VM
metadata, commerce, agent, and x402 payloads. Runtime constants and package
metadata are synchronized by `scripts/bump-sdk-version.sh` and enforced by
`scripts/validate_sdk_release_alignment.py`.

## Canonical ingestion contract

All SDKs POST canonical batch envelopes to `POST /v1/batch`. `/v1/ingest/events` and `/v1/ingest/events/batch` are reserved for server-side ingestion/connectors and are documented as non-SDK aliases/deprecated paths where legacy backend components still expose them.

## Consent and event compliance

Every SDK enforces the canonical event-to-consent-purpose map before enqueue/send. Consent events are never blocked. Raw custom events must be wrapped as `type: "track"` with `properties.event`; static release validation fails on raw non-canonical `enqueueEvent` calls.

## Coverage policy

Release CI requires >=95% coverage for Shared, Web, React Native, Android, iOS, and backend ingestion contract checks. The validation workflow runs package tests, native build/test or lint equivalents where available, and the release-alignment drift script.

## Conformance evidence

The cross-SDK conformance matrix is machine-derived, never hand-asserted:
`scripts/release/sdk_conformance.py` verifies every claimed capability cell in
`packages/shared/sdk-parity.json` against its declared evidence file/symbol in
the SDK sources, inventories each SDK's real test manifest, and fails closed on
any unverifiable claim. The derivation runs inside the repo-doctor SDK
runtime-parity gate and is embedded in the release evidence bundle
(`scripts/release/collect_evidence.py`).

## First-release scope

The first release exposes the shared, Web, and React Native SDK families when
their release gates pass. React Native is a conditional SDK release surface:
its typecheck, conformance evidence, and hosted native compile gates must pass
before it is included in the release announcement. The Aether and Kyber mobile
applications themselves are not part of this release; they remain in
design-partner/development posture and are explicitly disabled in the staging
and production-lean feature-flag manifests.

The publish workflow publishes SDK libraries and artifacts only. It does not
submit either mobile application to TestFlight, the Play internal track, or a
store.

## Remaining limitations

- Native iOS/Android queues persist bounded, versioned envelopes with atomic
  replacement, restore after restart, and quarantine corrupt state; unlike the
  Web SDK's localStorage persistence, storage remains capped, so the oldest
  events are dropped first under sustained offline backlog.
- Native multi-VM wallet support is manual metadata emission; automatic provider detection remains Web-only.
- Native health payloads do not yet include every Web-only metric such as detailed endpoint latency histograms.
- Publication still requires the repository's external npm, CocoaPods, and
  GitHub Packages credentials; this checkout contains the workflow and release
  gates, not those credentials.
