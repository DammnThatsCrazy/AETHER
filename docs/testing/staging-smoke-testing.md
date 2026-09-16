---
title: Staging Smoke Testing — Functionality Proof Spine
slug: testing/staging-smoke-testing
section: concepts
visibility: I
audience: [dev-junior, dev-senior, ops]
status: experimental
since_version: 0.1.0
---

# Staging Smoke Testing — Functionality Proof Spine

## Scope

This doc describes the `pnpm smoke:staging` command, the required environment variables, the proof tenant reset, the expected PASS output, common FAIL states with typed reason and likely owning subsystem, remediation ownership, and the report output location. Staging smoke is the gateway that confirms the staging environment and the proof tenant are reachable before the deeper E2E flows run.

Tickets referenced: FPS-010 (staging smoke), FPS-023 (staging smoke output format), FPS-024 (smoke environment variables), FPS-025 (proof tenant reset).

## The command

```bash
pnpm smoke:staging
```

This runs the staging smoke script at `scripts/smoke/staging.ts`. It is the first smoke command in the sequence. The full smoke sequence is:

```bash
pnpm smoke:staging
pnpm smoke:web-sdk
pnpm smoke:ios-sdk
pnpm smoke:android-sdk
pnpm smoke:stripe-connector
pnpm smoke:shopify-connector
pnpm smoke:email-connector
```

The combined sequence is available as `pnpm smoke:all`. Each `smoke:<target>` command is a ticket-owned stub that will become a real staging check as the proof spine is implemented. Currently, all smoke commands are stubs per FPS-010 through FPS-015.

## Required environment variables

The staging smoke command and the downstream smoke commands require these environment variables to be set before running:

| Variable | Purpose | Example |
|---|---|---|
| `AETHER_STAGING_BASE_URL` | Staging API base URL | `https://staging.aether.example` |
| `AETHER_STAGING_API_KEY` | API key with staging proof tenant access | `aether-staging-***` |
| `AETHER_PROOF_TENANT_ID` | The proof tenant to target | `aether-proof-tenant` |
| `AETHER_PROOF_WORKSPACE` | The proof workspace | `proof-lab` |
| `AETHER_STAGING_ENVIRONMENT` | The environment name for the run | `staging` |

If any required variable is missing, the smoke command exits with a `BLOCKED` result and a typed reason that names the missing variable. Do not hardcode credentials in the script or in the repository. The staging smoke command reads from the environment, not from a config file in the repo.

## Proof tenant reset

Before the staging smoke runs, the proof tenant must be reset to a known state. The proof tenant reset clears the tenant's ingested data and graph state so the smoke run starts from a clean baseline. The reset is part of the smoke:staging command when the command is fully implemented, per FPS-025.

Until the reset is implemented, the proof tenant must be reset manually before running the smoke sequence, or the smoke run must be preceded by a reset step documented in the run log. A smoke run that starts from a dirty tenant state is not a valid pass, because the expected PASS output assumes a clean baseline.

The proof tenant is identified by `AETHER_PROOF_TENANT_ID` (default `aether-proof-tenant`) and `AETHER_PROOF_WORKSPACE` (default `proof-lab`). These are the values documented in [Proof Tenant Specification](../proof/proof-tenant.md).

## Expected 24-line PASS output

The staging smoke command is expected to produce a 24-line PASS output when all checks pass. The exact lines are defined by the smoke check inventory, which maps each line to a named check with a pass condition. The output is structured so each line is a self-contained PASS or FAIL entry.

A 24-line PASS output has the following shape:

- One header line identifying the command and the run.
- One line for the staging environment reachability check.
- One line for the proof tenant reachability check.
- One line for the proof tenant reset confirmation.
- Lines for each smoke check in the inventory, each reporting `PASS` with the check name.
- One summary line reporting the total PASS count and the overall result.

When all checks pass, the output ends with an explicit confirmation that the staging smoke passed and downstream smoke commands may proceed.

The 24-line count is not arbitrary. It is the current approved inventory of staging smoke checks. If the inventory changes, the expected output count changes with it, and the change is ticketed and documented.

## Common FAIL states

When a staging smoke check fails, the output is a FAIL line with a typed `reason` and a likely owning subsystem. The reason is a stable, human-readable code that describes what failed, and the subsystem is the team or area that owns the fix.

The following FAIL states are the ones the staging smoke command is designed to surface:

| FAIL reason | Likely owning subsystem | What it means |
|---|---|---|
| `STAGING_UNREACHABLE` | Platform / staging operations | The staging API base URL did not respond, or responded with an unexpected status. |
| `TENANT_UNREACHABLE` | Platform / tenant management | The proof tenant was not reachable at the staging endpoint. |
| `TENANT_RESET_FAILED` | Platform / tenant management | The proof tenant reset did not complete or did not return to a clean state. |
| `API_KEY_INVALID` | Platform / credentials | The staging API key was rejected. |
| `ENVIRONMENT_MISMATCH` | Platform / staging operations | The `AETHER_STAGING_ENVIRONMENT` value did not match the expected staging environment. |
| `SMOKE_CHECK_FAILED` | Depends on the check | A named smoke check failed its pass condition. The check name is included in the output. |
| `BLOCKED_MISSING_ENV` | Operator / run setup | A required environment variable was missing. The variable name is included in the output. |

Each FAIL line is reportable. It is not enough to say "smoke failed." The failure must be reproducible from the output line, with a typed reason and a likely owning subsystem, so the right team can act on it.

## Remediation ownership

The likely owning subsystem is a starting point, not a final assignment. The ownership model is:

- **Platform / staging operations** owns staging reachability, environment configuration, and the staging API endpoint.
- **Platform / tenant management** owns the proof tenant, tenant reset, and tenant reachability.
- **Platform / credentials** owns staging API keys and credential validation.
- **The owning team of a named smoke check** owns that check's pass condition and remediation. If the check is a stub, the owning team is the team ticketed to implement it.

When a FAIL state is reported, the named subsystem is the first place to look. If the subsystem is a stub, the remediation is to implement the check, not to work around it.

## Report output location

The staging smoke command writes its report to a known output location so the result can be captured, attached to a run, and included in a release readiness summary. The output location is:

- **stdout** for the live run, so the operator sees the PASS/FAIL lines as they happen.
- **A timestamped report file** in the run's output directory, so the result is persistent. The exact path is determined by the smoke runner and is reported at the end of the command.

The report file is the artifact that gets included in the proof report. It is not sufficient to screenshot stdout. The report file is the canonical output.

## How staging smoke relates to the rest of the proof spine

Staging smoke is the gateway. If it fails, the downstream smoke commands and E2E flows should not proceed, because they depend on a reachable staging environment and a clean proof tenant. If it passes, the downstream smoke commands exercise individual SDKs and connectors against that reachable staging environment, and the E2E flows compose those into a full tenant proof.

A change to the staging environment or the proof tenant should be reflected in the staging smoke command first. A new staging endpoint, a new proof tenant field, or a new reset behavior should add a smoke check before it is relied on by an E2E flow.
