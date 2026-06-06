---
title: SDK Release Readiness Report
slug: sdks/release-readiness-report
section: sdks
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "8.9.0"
canonical_owner: sdk@aether
estimated_read_minutes: 6
---

# SDK Release Readiness Report — 8.9.0

## Release alignment

Aether SDK 8.9.0 uses `packages/shared` as the canonical contract source for event types, consent purposes, schema metadata, health payload shape, wallet VM metadata, commerce, agent, and x402 payloads. Runtime constants and package metadata are synchronized by `scripts/bump-sdk-version.sh` and enforced by `scripts/validate_sdk_release_alignment.py`.

## Canonical ingestion contract

All SDKs POST canonical batch envelopes to `POST /v1/batch`. `/v1/ingest/events` and `/v1/ingest/events/batch` are reserved for server-side ingestion/connectors and are documented as non-SDK aliases/deprecated paths where legacy backend components still expose them.

## Consent and event compliance

Every SDK enforces the canonical event-to-consent-purpose map before enqueue/send. Consent events are never blocked. Raw custom events must be wrapped as `type: "track"` with `properties.event`; static release validation fails on raw non-canonical `enqueueEvent` calls.

## Coverage policy

Release CI requires >=95% coverage for Shared, Web, React Native, Android, iOS, and backend ingestion contract checks. The validation workflow runs package tests, native build/test or lint equivalents where available, and the release-alignment drift script.

## Remaining limitations

- Native iOS/Android queues are bounded and retried, but durable disk-backed persistence remains partial compared with Web localStorage persistence.
- Native multi-VM wallet support is manual metadata emission; automatic provider detection remains Web-only.
- Native health payloads do not yet include every Web-only metric such as detailed endpoint latency histograms.
