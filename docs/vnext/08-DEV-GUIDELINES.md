# 08 — Development Guidelines

Coding conventions, commit standards, PR template, and architectural decision records for v-Next.

---

## Code conventions

### Python

| Convention | Rule |
|---|---|
| Style | `ruff` + `black`; PEP 8 |
| Type hints | Required on all new public functions |
| Docstrings | Google style; required on all public classes/functions |
| Async | Prefer `async def` for I/O; use `asyncio` consistently |
| Imports | Sorted by `ruff`; absolute imports only |
| Naming | `snake_case` functions/variables, `PascalCase` classes, `UPPER_SNAKE` constants |
| Errors | Custom exception classes; no bare `except` |
| Logging | Structured JSON; no f-string interpolation in log messages |
| Tests | `pytest`; fixtures in `conftest.py`; parametrize for table-driven |

### TypeScript

| Convention | Rule |
|---|---|
| Style | `prettier` + `eslint` |
| Types | `strict: true` in tsconfig |
| Naming | `camelCase` variables/functions, `PascalCase` types/components |
| React | Functional components + hooks; no class components |
| State | Existing state mgmt pattern (do not introduce new libraries) |
| Tests | `vitest` or `jest` per existing repo convention |

---

## File header

Every new Python file starts with:

```
"""
<Module name>

<One-line purpose>

Pillar: P<N> — <Pillar name>
Feature flag: <flag name or "always on">
Preservation: <what existing behavior this does NOT change>
"""
```

Every new TypeScript file starts with:

```
/**
 * <Component name>
 *
 * <One-line purpose>
 *
 * Pillar: P<N> — <Pillar name>
 * Feature flag: <flag name>
 */
```

---

## Commit message convention

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `security`, `perf`, `ci`

**Scopes:** `p0`, `p1`, ..., `p10`, `foundation`, `security`, `testing`, `cicd`, `shiki`, `agent`, `ml`, `graph`, `lake`, `crypto`, `ingest`

**Examples:**
```
feat(p1): add Mission vertex type and reconstruction service

Introduces the Mission first-class object that binds objective -> tasks ->
payments -> outcome. Registers additive vertex + edge types. Implements
reconstruction from existing event provenance.

Pillar: P1 Causal Mission Graph
Preservation: no /v1 endpoints changed; existing graph traversals untouched
Tests: unit + integration + contract + preservation
```

```
security(p7): enforce EIP-712 attestation replay protection

Adds nonce + expiry + chain-id binding to all attestations. Updates
Solidity verifier. No production attestations issued until audit complete.

Pillar: P7 Provenance Substrate
```

---

## PR template

Every PR must use this template:

```
## Pillar
P<N> — <Pillar name>

## Summary
<1-3 sentences: what and why>

## Preservation guarantees
- [ ] No existing /v1 endpoint response shape modified
- [ ] No existing DB column/table dropped or renamed
- [ ] No existing graph vertex/edge type semantics changed
- [ ] No existing controller removed or renamed
- [ ] No existing Shiki view removed or restructured
- [ ] No existing SDK API surface modified
- [ ] No existing MLflow model name changed
- [ ] External data-provider adapters untouched (unless adding new)

## Feature flag
<flag name> — defaults to `False`

## Tests
- [ ] Unit tests added (coverage ≥85%)
- [ ] Integration tests added
- [ ] Contract tests added (if new endpoint)
- [ ] Preservation tests pass
- [ ] Security checks pass (if applicable)

## Security
- [ ] No new secrets committed
- [ ] SBOM updated if deps changed
- [ ] Threat model considered
- [ ] Conformal wrapper applied (if ML)

## Documentation
- [ ] OpenAPI updated (if new endpoint)
- [ ] ADR added (if architectural decision)
- [ ] Model card added (if ML)
- [ ] Feature flag documented

## Rollback
<how to disable this PR's behavior>

## Related docs
- docs/vnext/02-PILLARS.md#p<N>
- docs/vnext/07-BUILD-SEQUENCE.md#phase-<N>
```

---

## Architecture Decision Records (ADRs)

Every significant architectural decision gets an ADR under `docs/vnext/adr/`:

```
docs/vnext/adr/
├── 001-bitemporal-schema.md
├── 002-witness-signatures.md
├── 003-mission-vertex.md
├── 004-conformal-abstention.md
├── 005-psi-federation.md
└── ...
```

ADR template:

```
# ADR <NNN>: <Title>

**Status:** Proposed | Accepted | Deprecated | Superseded
**Date:** YYYY-MM-DD
**Pillar:** P<N>

## Context
What is the problem we're solving?

## Decision
What did we decide?

## Alternatives considered
- Option A: ...
- Option B: ...
- Option C: ...

## Consequences
- Positive: ...
- Negative: ...
- Neutral: ...

## References
- Related pillars
- Related docs
- External references
```

---

## Naming conventions (v-Next specific)

| Concept | Convention | Example |
|---|---|---|
| New API routes | `/v2/<resource>/<action>` | `/v2/missions/reconstruct` |
| New vertex types | PascalCase, descriptive | `Mission`, `Gap`, `AgentBalanceSheet` |
| New edge types | VERB_NOUN, uppercase | `CAUSED_OUTCOME`, `HAS_AUTHORITY` |
| New feature flags | `vnext.<pillar>.<feature>` | `vnext.mission_graph.enabled` |
| New MLflow models | `vnext_<model_name>` | `vnext_hawkes_journey` |
| New database tables | `vnext_<table_name>` | `vnext_mission_summary` |
| New Python modules | `<snake_case>` | `mission_vertex.py` |
| New TS components | `<PascalCase>.tsx` | `MissionTimeline.tsx` |

---

## Module README requirements

Every new module directory has a `README.md` with:

```
# <Module name>

**Pillar:** P<N> — <Pillar name>
**Feature flag:** <flag>
**Owner:** <team/role>

## Purpose
<1-paragraph explanation>

## API
<public interface>

## Dependencies
<what this depends on (internal + external)>

## Data model
<vertices, edges, tables this introduces>

## Tests
<test file locations + what they cover>

## Preservation guarantees
<what existing behavior this does NOT change>

## Rollback
<how to disable>

## Related
<links to ADRs, pillar docs, etc.>
```

---

## Model cards

Every new ML model (challenger or champion) ships with a model card under `docs/ml/model-cards/`:

```
# Model Card: <model_name>

**Version:** <semver>
**Pillar:** P<N>
**Status:** Challenger | Champion | Deprecated

## Intended use
<who uses this, for what>

## Training data
- Source: <Gold tier query / synthetic>
- Time range: <dates>
- Size: <rows>
- Hash: <lineage hash>

## Features
<input features w/ descriptions>

## Performance
- Metric: <AUC / F1 / NLL / ...>
- Test set: <description>
- Value: <number> +/- <CI>
- Baseline: <current champion>

## Fairness + bias
<bias audit results, subgroup performance>

## Limitations
<known failure modes>

## Security
- [ ] Neural Cleanse scan passed
- [ ] STRIP scan passed
- [ ] Adversarial robustness tested
- [ ] DP epsilon: <value>
- [ ] SBOM attached

## Conformal calibration
- Coverage guarantee: <alpha>
- Calibration set: <description>
- Abstention rate: <percent>
```

---

## Data cards

Every new training dataset or feature family ships with a data card:

```
# Data Card: <dataset_name>

**Version:** <semver>
**Pillar:** P<N>

## Source
<Gold tier query / Silver aggregation / synthetic>

## Schema
<columns w/ types + semantics>

## PII handling
<fields tokenized / redacted / encrypted>

## Provenance
- Witness-signed events: <percent>
- Unsigned events: <percent>
- Quarantine filtered: <percent>

## Quality
- Completeness: <percent>
- Freshness: <lag>
- Known issues: <list>

## Retention
<retention policy + deletion SLA>

## Privacy
- DP epsilon applied: <value or N/A>
- k-anonymity: <k>
```

---

## Secrets handling

| Never | Always |
|---|---|
| Commit secrets to repo | Use AWS Secrets Manager |
| Log full secrets | Log secret metadata (name, rotation date) |
| Pass secrets as env vars directly | Load at runtime via broker |
| Share keys across environments | Per-env key isolation |
| Store keys in code | Store in HSM/KMS |
| Log PII + secrets in same line | Structured logs w/ PII scrubber |

---

## Error handling

| Pattern | Use when |
|---|---|
| Custom exception class | Domain errors (e.g., `MissionNotFoundError`) |
| HTTPException | API route errors |
| Context manager | Resource cleanup |
| Retry w/ exponential backoff | Transient infra errors |
| Circuit breaker | Downstream service failures |
| Never: bare `except:` | — |
| Never: `except Exception: pass` | — |

---

## Observability requirements per new code path

| Signal | Required |
|---|---|
| Structured log (info on entry, debug on exit) | Yes |
| Prometheus counter | Yes |
| Prometheus histogram (for latency) | If external I/O |
| Trace span (OpenTelemetry) | For request handlers |
| Error rate alert | For every new endpoint |
| SLO defined | For every new endpoint |

---

## When to write an ADR

- Introducing new architectural pattern
- Choosing between libraries/frameworks
- Changing data model or schema
- Changing security boundary
- Changing deployment model
- Deprecating existing capability
- Cross-cutting decisions affecting multiple pillars
