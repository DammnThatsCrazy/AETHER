---
title: Proof Fixtures
slug: proof/proof-fixtures
section: testing
visibility: I
audience: [dev-junior, dev-senior, qa]
status: experimental
since_version: 0.1.0
---

# Proof Fixtures

## Purpose

Proof fixtures are the fixture data used to test connectors and normalizers in isolation. They provide a known set of provider-shaped records and the expected canonical Aether output after normalization. Fixtures let connector tests run locally and in CI without hitting a real provider, and they let the proof spine validate connector behavior against a known baseline.

Proof fixtures are not provider-specific test data. Provider-specific fixtures live alongside the connector that consumes them. The proof fixture package at `packages/proof-fixtures` provides shared stubs and scaffolding for FPS test construction, not the full provider fixture sets.

## Package location

The shared proof fixture package lives at:

```
packages/proof-fixtures
```

It is a pnpm workspace package with the name `@aether/proof-fixtures`. It ships TypeScript types and stubs used by connector fixture tests and by the proof runner when constructing test scenarios.

## Directory tree

A representative fixture package directory tree looks like this:

```
packages/proof-fixtures
├── fixtures
│   ├── sdk
│   │   ├── heartbeat.json
│   │   └── event.json
│   ├── connectors
│   │   ├── stripe
│   │   │   ├── charge.json
│   │   │   └── customer.json
│   │   ├── shopify
│   │   │   ├── order.json
│   │   │   └── product.json
│   │   └── email
│   │       ├── send.json
│   │       └── bounce.json
│   └── graph
│       ├── entity.json
│       └── edge.json
├── src
│   ├── index.ts
│   ├── sdk.ts
│   ├── connectors.ts
│   └── graph.ts
├── package.json
└── tsconfig.json
```

The exact tree grows as new fixture scenarios are added. The top-level shape is stable: a `fixtures/` directory divided by domain, and a `src/` directory that exports typed access to those fixtures.

## Fixture shape

Each fixture file is one of eight file types, chosen to cover the different shapes a test needs. A fixture file is not just a JSON blob; it is a file with a known shape that the test can load and assert against.

The eight fixture file types are:

1. **Provider record.** A provider-shaped record, such as a Stripe charge or a Shopify order. This is the input to a normalizer test.
2. **Canonical event.** The expected canonical Aether event after normalization. This is the output a normalizer test asserts against.
3. **Cursor state.** A cursor snapshot representing the last-synced position for a connector. This is used to test incremental sync and cursor semantics.
4. **Batch envelope.** A batch-shaped envelope that matches the `POST /v1/batch` contract. This is used to test SDK batch emission and ingestion contract compliance.
5. **Webhook payload.** A provider webhook payload with the provider's signature shape. This is used to test webhook handling and signature verification.
6. **Identity map.** A set of identity hints and their expected graph resolution. This is used to test identity resolution and entity association.
7. **360 surface snapshot.** A snapshot of a 360 surface's expected state for a given tenant and data set. This is used to test 360 projection and state handling.
8. **Failure envelope.** A typed failure shape that a test asserts against when a connector or normalizer is expected to fail in a specific way. This is used to test error handling and failure modes.

Each file type has a shape that is documented in the fixture package's types. A fixture file that does not match its declared type is not a valid fixture.

## Required fixture scenarios

The proof fixture package must include the scenarios needed to exercise the proof spine's connector and SDK checks. The required scenarios are:

- **SDK heartbeat.** A heartbeat event fixture that matches the canonical heartbeat shape. Used by SDK contract tests and the proof runner to verify that a heartbeat is shaped correctly.
- **SDK canonical event.** A canonical event fixture that matches the canonical event shape. Used by SDK contract tests and the proof runner to verify that a tracked event is shaped correctly.
- **Connector initial sync.** A set of provider record fixtures that represent the initial sync window for a connector. Used by connector fixture tests to verify normalization accuracy across a known range.
- **Connector incremental sync.** A pair of fixtures: a cursor state after the initial sync, and a new provider record that should be picked up by incremental sync. Used by connector fixture tests to verify cursor semantics and incremental update behavior.
- **Connector webhook.** A webhook payload fixture with the provider's signature shape, and the expected canonical event after handling. Used by connector fixture tests to verify webhook handling and deduplication.
- **Connector error.** A provider record or webhook payload that is malformed or out of spec, and the expected failure envelope. Used by connector fixture tests to verify error handling.
- **Identity resolution.** An identity map fixture that associates SDK identity hints with connector-derived entities. Used by graph fixture tests to verify identity resolution and entity association.
- **360 empty and zero cases.** 360 surface snapshot fixtures that represent `no data yet`, `empty result`, and `zero value` states. Used by 360 tests to verify state handling.

These scenarios are required because they cover the proof spine's connector and SDK checks. A fixture scenario that is missing means the corresponding check cannot be fully verified in isolation.

## How fixtures are used

Fixtures are used at three levels:

1. **Connector fixture tests.** A connector's normalizer is tested against its provider record fixtures and asserted against its canonical event fixtures. This is the fastest, most repeatable layer of connector testing. It runs locally and in CI.
2. **SDK contract tests.** The SDK's batch emission is tested against batch envelope fixtures, and the SDK's event emission is tested against canonical event fixtures. This is the fastest layer of SDK testing.
3. **Proof runner scenarios.** The proof runner uses fixtures to construct test scenarios for the smoke and E2E flows. For example, the proof runner may use a webhook payload fixture to replay a webhook against a staging connector, or a 360 surface snapshot fixture to assert that a 360 surface is in the expected state after an E2E flow.

Fixtures are not hardcoded test data that is only used once. They are the known baseline that connector and SDK tests assert against. When a canonical event type changes, the fixture that represents it must be updated, and the tests that assert against it must be updated too.

## Pass condition

The fixture system passes when:

- The required fixture scenarios exist and match their declared file types.
- The fixture files are loadable and valid against their declared shapes.
- The connector fixture tests that use the fixtures pass.
- The SDK contract tests that use the fixtures pass.
- The proof runner can load the fixtures it needs for the smoke and E2E flows.

A fixture that is missing, malformed, or out of date causes the tests that depend on it to fail, which surfaces as a typed failure in the proof report.
