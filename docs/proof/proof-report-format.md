---
title: Proof Report Format
slug: proof/proof-report-format
section: concepts
visibility: I
audience: [dev-junior, dev-senior, ops]
status: experimental
since_version: 0.1.0
---

# Proof Report Format

## Purpose

The proof report is the structured record of a Functionality Proof Spine run. It records the result of every check and flow, the evidence that supports each result, and the typed failures and blockers where applicable. The report is the artifact that feeds the dev-senior readiness decision, and it is the artifact that makes a proof run reproducible and reviewable.

The report format is defined here so that every proof run produces a report that can be read, compared, and audited. A report that does not follow this format is not a proof report; it is a log.

## Required sections

Every proof report must contain these sections, in this order:

1. **Run metadata.** The tenant ID, workspace, environment, run timestamp, platform list, and dev-senior candidate identifier (if applicable).
2. **Smoke check results.** The result of each smoke check, with `PASS`, `FAIL`, `BLOCKED`, or `NOT_APPLICABLE` for each.
3. **E2E flow results.** The result of each of the seven E2E flows, with `PASS`, `FAIL`, `BLOCKED`, or `NOT_APPLICABLE` for each.
4. **Mobile device results.** The result of the mobile device checklist for each platform in scope, with `PASS`, `FAIL`, `BLOCKED`, or `NOT_APPLICABLE` for each.
5. **Failure output.** The typed FAIL reasons and likely owning subsystems for every failure.
6. **Blocker list.** The blockers that prevented a check or flow from running.
7. **Evidence references.** The report files, screenshots, logs, and any other evidence that supports the results.

A report that is missing a section is incomplete. A report that has a section with no content where content is expected is incomplete.

## Example report table

The smoke check results and E2E flow results are recorded in tables. The tables have the same shape: one row per check or flow, with the result and any typed reason.

### Smoke check results table

| Check | Result | Reason | Likely owning subsystem |
|---|---|---|---|
| staging reachability | PASS | — | — |
| proof tenant reachability | PASS | — | — |
| proof tenant reset | PASS | — | — |
| web SDK smoke | PASS | — | — |
| iOS SDK smoke | BLOCKED | Missing physical device for this run | Mobile / QA |
| Android SDK smoke | NOT_APPLICABLE | Android not in platform list for this run | — |
| Shopify connector smoke | FAIL | STAGING_UNREACHABLE | Platform / staging operations |

### E2E flow results table

| Flow | Result | Reason | Likely owning subsystem |
|---|---|---|---|
| tenant activation | PASS | — | — |
| Web SDK activation | PASS | — | — |
| connector activation | FAIL | Sync did not reach healthy state | Connector implementation |
| Profile 360 | BLOCKED | Depends on connector activation | — |
| Campaign 360 | BLOCKED | Depends on connector activation | — |
| Communications 360 | BLOCKED | Depends on connector activation | — |
| lens activation | NOT_APPLICABLE | Lens not in platform list for this run | — |

The example tables are illustrative. The actual report reflects the run that was performed.

## Failure output format

Every FAIL and BLOCKED result must include a typed reason and a likely owning subsystem. The typed reason is a stable, human-readable code that describes what failed. The likely owning subsystem is the team or area that owns the fix.

### Typed reason codes

The typed reason codes are the stable vocabulary for proof failures. They are not free-form text. A failure that does not have a typed reason is not a reportable failure.

| Reason code | Meaning |
|---|---|
| `STAGING_UNREACHABLE` | The staging environment did not respond or responded unexpectedly. |
| `TENANT_UNREACHABLE` | The proof tenant was not reachable. |
| `TENANT_RESET_FAILED` | The proof tenant reset did not complete or did not return to a clean state. |
| `API_KEY_INVALID` | The proof tenant API key was rejected. |
| `ENVIRONMENT_MISMATCH` | The environment value did not match the expected staging environment. |
| `INITIALIZATION_FAILED` | The SDK or proof app failed to initialize. |
| `HEARTBEAT_NOT_SENT` | The SDK did not emit a heartbeat. |
| `EVENT_NOT_TRACKED` | The SDK did not track a canonical event. |
| `IDENTITY_NOT_ATTACHED` | The SDK did not attach an identity hint. |
| `VISIBLE_STATE_WRONG` | The proof app's visible state did not match the expected state. |
| `SYNC_NOT_HEALTHY` | A connector sync did not reach a healthy state. |
| `CURSOR_MISSING` | A connector's cursor state was missing after sync. |
| `PROJECTION_FAILED` | Data was not projected into the graph. |
| `TENANT_ISOLATION_VIOLATED` | Tenant isolation was violated. |
| `PROFILE_EMPTY_WHEN_NOT` | Profile 360 was empty when it should not have been. |
| `PROFILE_MISSING_SDK_DATA` | Profile 360 was missing SDK data. |
| `PROFILE_MISSING_CONNECTOR_DATA` | Profile 360 was missing connector data. |
| `METRIC_WRONG` | A 360 metric was computed incorrectly. |
| `EMPTY_CASE_WRONG` | An empty or zero case was handled incorrectly. |
| `LENS_NOT_HEALTHY` | A lens did not reach a healthy state. |
| `LENS_DATA_MISSING` | A lens did not surface the expected data. |
| `MOBILE_INIT_CRASH` | The mobile proof app crashed on initialization. |
| `MOBILE_HEARTBEAT_MISSING` | The mobile SDK did not emit a heartbeat. |
| `MOBILE_EVENT_MISSING` | The mobile SDK did not track an event. |
| `ATT_GATING_WRONG` | iOS ATT gating did not behave as documented. |
| `QUEUE_LOST_ON_RESTART` | Android queued events were lost after process restart. |
| `BLOCKED_MISSING_ENV` | A required environment variable was missing. |
| `BLOCKED_MISSING_DEVICE` | A required device was not available for the run. |

The reason code list is the current approved vocabulary. A new failure mode that does not fit an existing code requires a new code, ticketed and documented, before it is used in a report.

### Likely owning subsystem

The likely owning subsystem is the team or area that owns the fix. It is not a final assignment; it is a starting point for remediation.

| Likely owning subsystem | Areas covered |
|---|---|
| Platform / staging operations | Staging environment, staging API endpoint, environment configuration. |
| Platform / tenant management | Proof tenant, tenant reset, tenant reachability, required state fields. |
| Platform / credentials | Staging API keys, credential validation. |
| Web SDK | Web SDK initialization, heartbeat, event tracking, identity attachment, visible state. |
| React SDK | React SDK initialization, hooks, heartbeat, event tracking, identity attachment, visible state. |
| iOS SDK | iOS SDK initialization, heartbeat, screen tracking, identity attachment, ATT gating, fingerprint gating. |
| Android SDK | Android SDK initialization, heartbeat, activity tracking, identity attachment, durable queue, background lifecycle. |
| Connector implementation | Connector authorization, sync, cursor, webhook handling, token refresh, disconnect/reconnect, projection. |
| Ingestion pipeline | Batch ingestion, event normalization, graph projection. |
| Graph | Graph projection, entity modeling, identity resolution, tenant isolation. |
| Profile 360 | Profile 360 data, state handling, projection. |
| Campaign 360 | Campaign 360 data, metrics, empty/zero case handling. |
| Communications 360 | Communications 360 data, state handling, projection. |
| Lens implementation | Lens activation, data, state handling. |
| Mobile / QA | Mobile device availability, mobile device checklist execution. |

## Example failure output

When a proof run has failures, the failure output section lists each failure with its typed reason, likely owning subsystem, and the evidence reference that supports it.

```
FAIL  connector activation — SYNC_NOT_HEALTHY — Connector implementation
       Evidence: reports/proof-2026-09-15T14-00-00Z/connector-activation.log

FAIL  Profile 360 — BLOCKED — Depends on connector activation
       Evidence: reports/proof-2026-09-15T14-00-00Z/profile-360.log

BLOCKED  iOS SDK smoke — BLOCKED_MISSING_DEVICE — Mobile / QA
         Evidence: reports/proof-2026-09-15T14-00-00Z/ios-smoke.log
```

The failure output is not a log. It is a structured record of the failures in the run, with enough detail to reproduce the decision and route the fix.

## Report output location

The proof report is written to a timestamped directory under the run's output location. The directory name reflects the run timestamp, so runs are ordered and reproducible.

A representative output location:

```
reports/proof-2026-09-15T14-00-00Z/
├── report.md
├── staging-smoke.log
├── web-sdk-smoke.log
├── profile-360.log
├── screenshots/
└── mobile/
```

The `report.md` is the canonical proof report. The log files are the evidence that supports the report. The screenshots and mobile logs are the evidence for the mobile device checklist.

The report output location is not a choice. It is the location the proof runner writes to, and it is reported at the end of the run so the operator can find the report.

## How the report format relates to the rest of the proof spine

The report format is the end of the proof spine. Every check, flow, and mobile device result is recorded in the report, and the report is the input to the dev-senior readiness aggregation. A proof run that does not produce a report in this format has not completed the proof spine, because there is no artifact to review or aggregate.

A change to the report format, the reason codes, or the likely owning subsystems should be reflected in this doc first. A new reason code or a new owning subsystem should be documented here before it is used in a report.
