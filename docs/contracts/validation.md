---
title: Contract Validation
slug: contracts/validation
section: reference
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
---

# Contract Validation

This document explains how contract validation is wired together: the
cross-consistency validator, the ownership map that ties source changes to
required updates, and the CI authority that enforces both.

## `scripts/validate_contracts.py`

This is the cross-file consistency validator for the canonical SDK contracts.
Per-file generators (`extract_events`, `extract_consent`, etc.) validate one
source in isolation and cannot catch drift *between* files — an event could
require a consent purpose that the consent contract doesn't define, and each
generator would still pass individually.

`scripts/validate_contracts.py` reads the generated artifacts under
`docs/_generated/` (`events.json`, `consent.json` — produced by
`scripts/docs_extract/run_all.py`, which CI runs immediately before this
validator) and runs seven checks:

1. **`check_event_consent_purposes`** — every event's `consent_purpose` must
   exist in the canonical `ConsentPurpose` set.
2. **`check_event_families`** — every event's `family` must be a declared
   `EventFamily`.
3. **`check_consent_purposes_self_consistent`** — every consent purpose the
   capability manifest advertises must be a real, canonical purpose.
4. **`check_python_backend_event_types`** — the Python
   `CANONICAL_EVENT_TYPES` frozenset (in `generated_registry.py`, preferred,
   or `batch.py` as a legacy fallback) must exactly match the generated event
   registry.
5. **`check_sdk_endpoint_not_ingest_events`** — SDK source files must not
   reference the deprecated `/v1/ingest/events` or `/v1/ingest/events/batch`
   routes; SDKs must use `/v1/batch`.
6. **`check_no_api_key_in_query_params`** — the web SDK's event-queue file
   must not send the API key as a `?token=` query parameter.
7. **`run_identity_security_checks`** — delegates to
   `scripts/validate_identity_security.py` for suppress-endpoint, mutating
   -endpoint-write-scope, raw-hash-in-alias-response, and tenant-scoping
   checks.

Exit code `0` means all checks pass; `1` means either an inconsistency was
found or a required generated artifact (`events.json`/`consent.json`) is
missing — in which case run `python scripts/docs_extract/run_all.py` first.

Run it directly with:

```bash
python scripts/docs_extract/run_all.py   # regenerate docs/_generated artifacts
python scripts/validate_contracts.py
```

It is also invoked with `--domain campaign` in some Makefile targets for a
narrower check scope (see `Makefile` line ~1141).

This validator does **not** replace the domain-specific registry validators —
`scripts/validate_spine_registry.py`, `scripts/validate_intelligence_projections.py`,
`scripts/validate_rights_vocabulary.py`,
`scripts/validate_field_trust_parity.py`, and
`scripts/generate_platform_contracts.py --check` each own structural
validation for their specific registry and are invoked separately, typically
via `make repo-doctor` or the ownership map's `required_commands` (below).

## The ownership map: `docs/source-of-truth/repo_consistency_ownership.json`

This file is the machine-checked source of truth for "if you change X, you
must also change Y and run Z." It defines a list of `change_categories`, each
with:

- `source_globs` — file patterns that trigger the category.
- `required_changed_globs` — file patterns that must also appear changed in
  the same diff.
- `required_commands` — commands that must pass.
- `remediation` — human-readable guidance on what to do.

Several categories are directly about contracts:

| Category id | Trigger | Required commands |
|---|---|---|
| `event_schema` | `packages/shared/events.ts`, `schemas/**`, `contracts/**` (excluding `*.md`), backend event sources | `validate_contracts.py`, `validate_sdk_release_alignment.py`, `npm run typecheck` |
| `event_field_trust_schema` | `packages/shared/contracts/event-registry.json`, its generator/gate | `generate_contracts.py --check`, `validate_field_trust_parity.py`, `validate_contracts.py`, `docs_drift.py --strict`, field-trust/semantic-boundary pytest suites |
| `intelligence_projection_architecture` | `packages/shared/contracts/intelligence-projection-registry.json` and its TS/Python twins | `generate_platform_contracts.py --check`, `validate_intelligence_projections.py`, `docs_drift.py --strict`, `make intelligence-projection-check` |
| `relationship_spine_registries` | `relationship-predicate-registry.json`, `relationship-motif-registry.json` | `generate_platform_contracts.py --check` |
| `spine_composition_kernel_architecture` | `spine-registry.json` and its twins | `generate_platform_contracts.py --check`, `validate_spine_registry.py`, `docs_drift.py --strict`, `make spine-registry-check` |
| `observation_envelope` | `observation-envelope-registry.json` and its Python/TS twins | `docs_drift.py --strict`, parity/unit pytest suites |
| `rights_irrl_authority` | `rights-vocabulary.json` and its Python/TS twins | `validate_rights_vocabulary.py`, `validate_no_parallel_rights_registries.py`, `validate_spine_registry.py`, `generate_platform_contracts.py --check`, `docs_drift.py --strict` |
| `measurement_integrity` | `metric-registry.json` and measurement services | `generate_contracts.py --check`, `docs_drift.py --strict` |
| `mobile_native_regions` | event-registry-generated iOS/Android regions | `generate_contracts.py --check`, `validate_mobile_event_parity.py` |

Every category's `required_commands` and `required_changed_globs` are what
`scripts/verification_disposition.py` (via `make verification-disposition`)
and `scripts/repo_doctor.py` (via `make repo-doctor`) check against the
actual diff. If you touch a contract's `source_globs` without touching its
`required_changed_globs`, or without the `required_commands` passing, the
disposition fails and names the exact category and remediation text.

## CI enforcement via `make verification-disposition`

Per `AGENTS.md`/`CLAUDE.md`, the single blocking authority for a normal PR is:

```bash
make verification-disposition BASE=<base> EXECUTE=1
```

This runs `scripts/verification_disposition.py`, which is the router that
decides which lanes/checks apply to a given diff (via
`config/verification_router.yaml` and `config/test_suites.yaml`) and enforces
the ownership map above. `make ci-check` runs the broader, non-blocking
evidence sweep (trusted-main/nightly/release scope) and is reported
separately — it is not a second blocking authority for a normal PR.

`make repo-doctor` (`scripts/repo_doctor.py --check`) is the read-only,
no-mutation consistency check that includes `python scripts/validate_contracts.py`
as one step (see the `docs:` Makefile target, which chains
`docs_extract/run_all.py` → `sync_docs.py` → `validate_docs.py` →
`validate_frontmatter.py` → `docs_drift.py` → `validate_contracts.py`).
`make repo-doctor-fix` regenerates the generated surfaces and then re-runs
the same checks.

## Practical validation sequence

For a change that touches any file under `contracts/delivery/` or
`packages/shared/contracts/`:

```bash
git fetch origin && git rebase origin/main
python scripts/docs_extract/run_all.py      # if event/consent sources changed
python scripts/validate_contracts.py
make repo-doctor                            # or repo-doctor-fix if it needs regeneration
make verification-disposition BASE=origin/main EXECUTE=1
git status --short
```

If `verification-disposition` names a specific `change_categories` entry as
unmet, consult `docs/source-of-truth/repo_consistency_ownership.json` for
that category's exact `required_changed_globs` and `required_commands`
rather than guessing — the remediation text on each entry states the fix.
