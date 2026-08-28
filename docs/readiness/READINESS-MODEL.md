---
title: "Multidimensional Readiness Model"
slug: readiness/readiness-model
section: operations
visibility: I
audience: [ops, architect, exec, security]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 12
toc_depth: 3
---

# Multidimensional Readiness Model

A single readiness percentage collapses independent facts into one misleading
number. A connector that is **fully built, runtime-wired, tested, and needs only
a secret** is not "50% implemented" because the secret has not been pasted in.
Missing external activation must never reduce repository-controlled
implementation completion.

This model replaces percentage-only reporting with independent dimensions and a
per-release-profile disposition decided by **hard gates, never by averaging**.

Canonical sources:

| Artifact | Purpose |
|---|---|
| `config/readiness_model.yaml` | Vocabulary, ceilings, release-profile registry, percentage rules |
| `config/readiness/schema.json` | JSON Schema for a feature record |
| `config/readiness/features/*.yaml` | The feature records |
| `config/readiness/scope_locks.yaml` | Scope denominator locks (version-bump guard) |
| `scripts/lib/readiness_model.py` | Loader + evaluator (pure stdlib) |
| `scripts/readiness_status.py` | Status cards, profile reports, artifacts, docs |
| `scripts/validate_readiness_model.py` | Fail-closed validator |
| `scripts/migrate_readiness_data.py` | Legacy migration + report |
| `artifacts/readiness/{features,profiles,migration-report}.json` | Machine-readable outputs |
| `docs/_generated/{FEATURE-READINESS,RELEASE-PROFILE-READINESS}.md` | Generated reports |

## Platform coverage

The model covers the **entire platform**: there is one feature record per
capability on the legacy `scripts/production_status.py` scorecard (plus
cross-cutting capabilities like event transport), so every legacy 0-5 area now
has a decomposed, multidimensional record. `make readiness-migrate` reports the
mapping (0 areas requiring manual classification), and
`tests/readiness/test_readiness_coverage.py` fails if a scorecard area ever
loses its record. Records generated from the legacy scorecard carry
`historical.migration_derived: true` and a confidence gap noting that the 0-5
score is a proxy pending per-capability SME review — it is decomposed across the
dimensions below, never used as an authoritative number.

Release-profile participation follows the real founding-tenant scope
(`config/founding_tenant_release.yaml`): excluded domains (derivatives,
economic, financial, payments, rewards, stablecoin, agent-execution) are
`not_in_release` for the production profiles and appear only as experimental in
staging/pilot, exactly as the platform ships them.

**Staging floor.** Staging's implementation floor is `VERIFIED` (not `TURNKEY`):
staging is where a verified capability is validated toward turnkey/production.
The production profiles keep the `TURNKEY` floor, so a capability that is
`VERIFIED` but not yet certified turnkey reads as `READY_TO_VALIDATE` in staging
and `BLOCKED_BY_CODE` (turnkey work remains) for production — a true, useful
gradient rather than one collapsed number.

## The dimensions

Each is tracked **independently**. None may rewrite another.

1. **Implementation completion** — repository-controlled work only (contracts,
   core behavior, runtime wiring, persistence, authorization, error handling,
   required flags). States: `NOT_STARTED → SCAFFOLDED → IMPLEMENTED →
   RUNTIME_INTEGRATED → VERIFIED → TURNKEY`. It **never** includes credentials,
   cloud accounts, provider approval, or live traffic.
2. **Productionization completion** — security, consent, observability,
   idempotency, retry/replay, rollback, backups, runbooks, admin controls,
   capacity/cost limits, CI/release gates. Separate from whether credentials or
   infrastructure have been supplied.
3. **External activation** — conditions outside source control, tracked as
   typed blockers (`CREDENTIAL_WAITING`, `INFRASTRUCTURE_WAITING`,
   `ACCOUNT_WAITING`, `DNS_WAITING`, `EXTERNAL_APPROVAL_WAITING`, …). Each
   blocker names its type, owner, required action, whether a **source-code
   change** is expected, affected environments/profiles, and the evidence
   required to clear it.
4. **Environment evidence** — per environment (`local`, `ci`, `integration`,
   `preview`, `demo`, `staging`, `pilot`, `production`, `scale`). States:
   `NOT_APPLICABLE`, `NOT_ATTEMPTED`, `BLOCKED_EXTERNAL`, `FAILED`, `VERIFIED`,
   `EXPIRED`. Offline evidence (`local`/`ci`) is **never** presented as
   production verification.
5. **Dependency readiness** — hard/soft/optional dependencies with their own
   state. A dependency failure produces **effective** dependency-blocking
   without rewriting the feature's **intrinsic** implementation completion.
6. **Operational ownership** — team, technical/operational owner, escalation,
   runbook, dashboards, alerts, SLO/RTO/RPO. May reduce productionization or
   release eligibility; **never** functional implementation completion.
7. **Business/organizational readiness** — docs, onboarding, pricing, legal,
   compliance, support, sales enablement. Independent of technical release
   eligibility.
8. **Evidence confidence** — `UNPROVEN → LOW → MODERATE → HIGH → VERY_HIGH`,
   reflecting the strength/freshness of evidence. A feature can be 100%
   implemented with only MODERATE confidence because it has not run in a
   credentialed environment. That is **implementation complete + environment
   validation pending**, not partially implemented.

## Repository ceilings

Every capability declares a repository-controlled ceiling — the highest state
the repository alone can reach:

`CODE_COMPLETE`, `RUNTIME_INTEGRATED`, `VERIFIED`, `CREDENTIAL_TURNKEY`,
`INFRASTRUCTURE_TURNKEY`, `RELEASE_TURNKEY`, `LIVE_VERIFIED`, `SCALE_VERIFIED`.

The model distinguishes the declared ceiling, whether it is **achieved**, what
must happen after it, and whether the remaining actions are repository-controlled
or external. A `CREDENTIAL_TURNKEY` capability that is achieved reports
implementation **100%** and activation `CREDENTIAL_WAITING` — never 50%/75%.

## Versioned scopes

Every measurement has an explicit, versioned scope: `id`, `version`, `title`,
`target`, and `included` / `excluded` / `deferred` requirements. A capability
may be 100% complete for a V1 pilot while incomplete for a future GA scope.
**Any material denominator change requires a scope-version bump** — enforced by
`config/readiness/scope_locks.yaml` (regenerate with
`python scripts/validate_readiness_model.py --update-locks` after review). Adding
V2 requirements never retroactively reduces a completed V1.

## Hard gates vs percentages

Percentages summarize coverage; they **never** override a failed hard gate. Each
percentage names its denominator and counts only in-scope controls. The
authoritative signal is the per-profile **disposition**:

`NOT_IN_PROFILE`, `DISABLED_INTENTIONALLY`, `BLOCKED_BY_CODE`,
`BLOCKED_BY_PRODUCTIONIZATION`, `BLOCKED_BY_DEPENDENCY`, `READY_TO_ACTIVATE`,
`READY_TO_VALIDATE`, `TECHNICALLY_RELEASE_ELIGIBLE`, `BUSINESS_READINESS_PENDING`,
`PILOT_ELIGIBLE`, `PRODUCTION_ELIGIBLE`, `LIVE_VERIFIED`, `SCALE_VERIFIED`.

The evaluator applies hard gates in order — participation → code → productionization
→ dependency → activation → environment evidence → business — and a release
profile is only as ready as its **weakest required capability**.

### Intrinsic vs effective

- **Intrinsic** disposition is the feature's own readiness.
- **Effective** disposition additionally accounts for unsatisfied hard
  dependencies. A dependency block sets the effective disposition to
  `BLOCKED_BY_DEPENDENCY` while leaving intrinsic implementation completion
  untouched.

## Two readings, materially different

```
Implementation: 100%
Activation: Credential waiting
Staging evidence: Pending
Disposition: Ready to activate
```

is **valid** and materially different from:

```
Implementation: 70%
Activation: Not applicable
Disposition: Blocked by code
```

The first has no remaining repository work; the second does. The model keeps
them apart on purpose.

## Commands

```
make readiness-status                       # multidimensional overview
make readiness-validate                     # fail-closed honesty validation
make feature-readiness FEATURE=<feature-id> # one feature status card
make profile-readiness PROFILE=<profile-id> # one release-profile report
make readiness-artifacts                    # regenerate artifacts + generated docs
make readiness-migrate                      # legacy migration report
```

`scripts/readiness_status.py` supports `--format text|json|markdown`,
`--scope <id>`, `--profile <id>`, `--environment <env>`, and `--strict`.

The report separates, and never blends: **repository work remaining**,
**external actions remaining**, **environment-evidence gaps**, **dependency
blockers**, **operational gaps**, and **business-readiness gaps**.

## How-to

### Add a feature record

1. Copy an existing file in `config/readiness/features/` (e.g.
   `financial-observability.yaml`) and give it a unique `feature_id`.
2. Fill every dimension. Keep implementation controls **repository-controlled
   only**; put external conditions under `activation.blockers`.
3. Name a denominator on every control block.
4. `python scripts/validate_readiness_model.py --update-locks` (records the
   scope denominator), then `make readiness-validate`.
5. `make readiness-artifacts` to regenerate outputs.

### Define a release profile

Add an entry under `release_profiles:` in `config/readiness_model.yaml` with its
default `implementation_floor`, `productionization_required`, `environment_gate`,
and `business_gate`. Each feature then declares its per-profile `participation`
(`required` / `experimental` / `disabled_intentionally` / `not_in_release`) and
may tighten (never loosen) the floor.

### Clear a blocker

When the external condition is satisfied, remove or downgrade the blocker,
update the affected `environment_evidence` (e.g. `staging: VERIFIED`,
`credentialed: true`), attach the evidence reference, and update `confidence`.
Re-run `make readiness-validate` and `make readiness-artifacts`.

### Attach evidence

Environment records carry `evidence`, `verified_at`, `verification_method`,
`environment_identifier`, `credentialed`, `suite`, and `expires_at`. A
credentialed environment (`integration`/`staging`/`pilot`/`production`/`scale`)
marked `VERIFIED` **must** set `credentialed: true` — offline evidence cannot
buy credentialed verification.

### Migrate legacy records

`scripts/production_status.py`'s 0-5 average is retained as
`historical_maturity_index` and is **non-authoritative**. Run
`make readiness-migrate` to produce `artifacts/readiness/migration-report.json`,
which lists what mapped automatically, what needs manual classification, the old
score, and the new per-dimension states with explicit assumptions. Never
silently reinterpret a legacy score as implementation-incompleteness — separate
implementation from activation and environment evidence first.
