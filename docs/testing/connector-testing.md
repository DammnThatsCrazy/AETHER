---
title: Connector Testing — Functionality Proof Spine
slug: testing/connector-testing
section: concepts
visibility: I
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# Connector Testing — Functionality Proof Spine

## Scope

This doc covers how the Functionality Proof Spine validates Aether connectors. Connector testing combines fixture tests, sandbox tests, backfill verification, incremental sync verification, webhook replay, token refresh, disconnect/reconnect, and graph/360 verification. Each technique targets a different part of the connector lifecycle described in `docs/connectors/connector-lifecycle.md`.

Tickets referenced: FPS-014 (connector smoke), FPS-015 (Shopify connector smoke), FPS-018 (connector fixture tests), FPS-019 (backfill and incremental verification), FPS-020 (webhook replay), FPS-021 (token refresh and disconnect/reconnect).

## The connector testing layers

### 1. Fixture tests

Fixture tests verify that a connector can ingest a known, confined set of provider records and normalize them into the canonical Aether contracts. They run locally and in CI without hitting a real provider.

Fixtures are described in [Proof Fixtures](../proof/proof-fixtures.md). Each fixture provides a set of provider-shaped records and the expected canonical output after normalization. A fixture test runs the connector's normalizer against the fixture records and compares the output to the expected canonical shape.

Fixture tests cover:

- Normalization accuracy: provider fields map to the correct canonical fields.
- Cursor semantics: the connector emits cursor state consistent with the fixture's record ordering and timestamps.
- Deduplication: duplicate provider records produce a single canonical event.
- Error handling: malformed fixture records produce the expected failure mode, not a crash.

Fixture tests are owned by the connector's implementing team and live alongside the connector code. The proof fixture package at `packages/proof-fixtures` provides shared stubs for FPS scaffolding, not provider-specific fixture data.

### 2. Sandbox tests

Sandbox tests exercise a connector against a real provider sandbox or test instance. They validate the full path from authorization through normalization to graph projection, using provider data that is known but live.

Sandbox tests cover:

- OAuth flow against the provider's test granting screen.
- Webhook registration with the provider's test webhook system.
- Initial sync against a known set of sandbox records.
- Incremental sync after new sandbox records are created.
- Provider-specific error responses and rate limits.

Sandbox tests require provider sandbox credentials and are typically run by the connector owner before a release, not in the default CI lane.

### 3. Backfill verification

Backfill verification confirms that a connector's historical sync pulls the expected range of records and that the resulting graph projection matches the provider's known state at the start of the backfill window.

Backfill verification covers:

- The connector starts from the correct cursor position (or the absence of one).
- The backfill completes without gaps across the declared window.
- The volume of synced records matches the provider's known count for the window, within the connector's documented tolerance.
- The projected graph contains the expected entities and edges for the backfilled records.

Backfill verification is performed as part of connector activation in the E2E flow for connector activation (see [E2E Testing](./e2e-testing.md)). It is not a per-commit check.

### 4. Incremental sync verification

Incremental sync verification confirms that a connector picks up new and updated records after the initial sync, using its cursor state, without re-sending historical data.

Incremental sync verification covers:

- After the initial sync, the connector's cursor reflects the last-synced position.
- New provider records appear in the graph after the next sync cycle.
- Updated provider records are reflected correctly, including deleted or deactivated records if the connector supports that.
- No historical records are re-synced during incremental cycles.

This verification is part of the connector activation E2E flow and is re-run when cursor behavior is changed.

### 5. Webhook replay

Webhook replay verifies that a connector correctly processes provider webhook payloads, including signature verification, duplicate suppression, and out-of-order delivery.

Webhook replay covers:

- A known webhook payload is delivered to the connector's webhook endpoint.
- The payload is verified against the provider's signature mechanism.
- The resulting canonical event matches the expected normalization.
- A duplicate webhook payload is suppressed and does not produce a duplicate canonical event.
- An out-of-order webhook payload is handled according to the connector's documented behavior (e.g., cursor advance, event acceptance).

Webhook replay can be performed with fixture payloads against a staging connector or with a provider sandbox that supports replay.

### 6. Token refresh

Token refresh verifies that a connector's OAuth or API key lifecycle works without manual intervention. It is the most common cause of connector health degradation in staging and production.

Token refresh covers:

- An expiring access token is refreshed using the provider's refresh grant.
- The refreshed token is stored and used for subsequent sync operations.
- A refresh failure surfaces in connector status as `needs attention` or `failed`, not as silent data loss.
- A connector whose refresh token itself is expired enters the re-authorization flow described in `docs/connectors/auth-and-credentials.md`.

### 7. Disconnect and reconnect

Disconnect and reconnect verifies that a connector recovers from a non-credential failure, such as a provider outage, a network partition, or a temporary rate limit.

Disconnect and reconnect covers:

- A connector in `syncing` or `healthy` state is subjected to a simulated provider unavailability.
- The connector surfaces `delayed` or `failed` as appropriate, without losing cursor state.
- When the provider becomes available again, the connector resumes sync from the last cursor position.
- No duplicate historical data is produced during reconnection.

### 8. Graph and 360 verification

Graph and 360 verification confirms that the connector's normalized events are projected into the intelligence graph and are visible in the relevant 360 surfaces.

Graph and 360 verification covers:

- After connector sync, the expected entities exist in the graph for the proof tenant.
- The entity relationships reflect the connector's normalized data (e.g., a customer entity linked to orders from an e-commerce connector).
- Profile 360, Campaign 360, and Communications 360 surfaces reflect the connector's data where applicable.
- The connector's data is not visible to other tenants (tenant isolation).

## Required connector behaviors

For the FPS to pass, every activated connector must demonstrably do the following in the proof tenant:

1. **Authorize** against the provider (OAuth or API key) and store credentials in the credential management system, not in code or environment variables.
2. **Register webhooks** with the provider during authorization where the provider supports webhooks.
3. **Perform an initial sync** that pulls the expected historical range and normalizes it into canonical contracts.
4. **Maintain cursor state** per tenant, per connector, per sync type, and use it for incremental sync.
5. **Emit incremental updates** after new or changed provider records, without re-sending historical data.
6. **Refresh tokens** automatically and surface refresh failures in connector status.
7. **Handle webhook payloads** with signature verification, deduplication, and out-of-order tolerance.
8. **Retry transient failures** with exponential backoff and surface persistent failures in tenant health.
9. **Project normalized events** into the intelligence graph for the proof tenant.
10. **Appear in the connector status surface** with one of the defined product states (`not connected`, `connected`, `syncing`, `healthy`, `delayed`, `failed`, `needs attention`).

## How the layers relate

```
fixture tests (local, normalizer correctness)
    → sandbox tests (provider integration, pre-release)
        → backfill verification (activation E2E)
            → incremental sync verification (activation E2E)
                → webhook replay (activation E2E or staged test)
                    → token refresh (activation E2E or staged test)
                        → disconnect/reconnect (staged test)
                            → graph/360 verification (activation E2E)
```

Fixture tests are the fastest and most repeatable layer. Sandbox tests validate the provider contract. The E2E activation flow ties the connector to the proof tenant and verifies the full path to graph and 360.

## Pass condition

Connector testing passes when:

- All fixture tests for the connector pass.
- The connector's sandbox test passes against the provider sandbox (where available).
- The connector activation E2E flow completes with the connector in a `healthy` state and its data visible in the graph and relevant 360 surfaces.
- Token refresh and disconnect/reconnect behave as documented, with no silent data loss.
- The connector does not produce duplicate historical data during incremental sync or reconnection.

If any layer fails, the failure is typed with a reason and a likely owning subsystem, per the report format in [Proof Report Format](../proof/proof-report-format.md).
