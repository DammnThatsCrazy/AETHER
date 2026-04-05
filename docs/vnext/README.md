# AETHER v-Next Build Spec

> **Status:** Draft spec, not yet implemented. Target branch: `claude/explore-ml-improvements-Mr3Kz`.
> This spec layers on top of the existing v8.8.0 repo. **Nothing here breaks existing behavior** — every new capability ships behind feature flags or as a parallel module.

---

## What this spec is

This is the complete build specification for AETHER v-Next: a set of 10 additive pillars that transform AETHER from a graph-native behavioral analytics platform into a **causal operating layer for the hybrid Web2/Web3 + agent economy**.

The spec is organized so that **Claude Code can execute it step-by-step without breaking the existing repo**. Every pillar has:

- Exact file paths to create/modify (no ambiguity)
- API contracts (request/response shapes)
- Feature flags that gate every new behavior
- Tests that must pass before merging
- Security controls baked in from Day 1
- Explicit backward-compatibility guarantees

---

## How to read this spec (in order)

| File | Purpose | When to read |
|---|---|---|
| `00-VISION.md` | Core thesis, pillar summary, glossary | Read first — context for everything else |
| `01-ARCHITECTURE.md` | As-is vs to-be system architecture with diagrams | Read second — understand the system delta |
| `02-PILLARS.md` | Full detail on all 10 pillars (APIs, files, data models) | Reference while building |
| `03-SECURITY.md` | Threat model + Day-1 security controls | Read before implementing any pillar |
| `04-LAYERING.md` | **Critical** — how to add without breaking existing repo | Read before first commit |
| `05-TESTING.md` | Unit/integration/contract/adversarial test strategy | Reference per pillar |
| `06-CICD.md` | CI/CD pipeline, gates, deploy process | Reference once at start |
| `07-BUILD-SEQUENCE.md` | Ordered checklist of implementation steps | **Execute top to bottom** |
| `08-DEV-GUIDELINES.md` | Code conventions, commit style, PR template | Reference continuously |

---

## The 10 Pillars at a glance

| # | Pillar | One-line description | Depends on |
|---|---|---|---|
| P0 | Foundation | Bitemporal schema + witness signatures + SBOM + conformal + doc reconciliation | — |
| P1 | Causal Mission Graph | Cross-domain attribution from goal → agent → payment → outcome | P0 |
| P2 | Counterfactual Runtime | Absence-aware scoring: "what should have happened" + ranked interventions | P0, P1 |
| P3 | Agent Credit & Delegation | Agent balance sheets + dynamic authority bands + ZK trust attestations | P0, P1 |
| P4 | Coverage Autopilot | Self-healing graph via active-learning routed review queue | P0 |
| P5 | Collusion Detection | Motif library + spectral cluster integrity + temporal community anomaly | P0, P3 |
| P6 | AETHER-GPT (Graph FM) | Self-supervised foundation model over the unified graph | P0 |
| P7 | Provenance Substrate | Bitemporal + witness-signed + ZK attestations (cross-cuts all) | — |
| P8 | Federated Identity (PSI) | Privacy-preserving cross-tenant reputation | P0, P3 |
| P9 | Safety Mesh | Conformal abstention + neuro-symbolic bytecode prover | P0 |
| P10 | Temporal Intelligence | Neural Hawkes TPP for continuous-time event modeling | P0 |

**Build order** (see `07-BUILD-SEQUENCE.md` for full detail):
P0 → P7 → P1 → P9 → P4 → P2 → P10 → P3 → P6 → P5 → P8

---

## Core non-negotiables

1. **No existing endpoint changes semantics.** Every new behavior lives at a new path, behind a flag, or as an opt-in header.
2. **No database migration drops or renames columns** in the first pass. Additive-only.
3. **Every pillar ships behind a feature flag** that defaults to `off`.
4. **Every pillar has a kill switch** that fully disables it via env var or config.
5. **Every new ML model registers through the existing MLflow pattern** — no parallel registries.
6. **Every new graph vertex/edge type is additive** — no existing type semantics change.
7. **Every new route is documented in OpenAPI** before implementation.
8. **Every commit passes existing CI** plus new security gates.

---

## What Claude Code needs to do (high level)

1. Read this README + `00-VISION.md` + `01-ARCHITECTURE.md` + `04-LAYERING.md` + `07-BUILD-SEQUENCE.md` first.
2. Implement **P0 Foundation** completely and get it green before touching any other pillar.
3. Implement pillars in the order specified in `07-BUILD-SEQUENCE.md`.
4. For each pillar:
   - Create skeleton (routes, models, services) with feature flag wired off
   - Implement core logic
   - Write unit + integration + contract tests
   - Run security checks (see `03-SECURITY.md`)
   - Enable feature flag locally, run e2e
   - Commit with structured message (see `08-DEV-GUIDELINES.md`)
5. Never commit a pillar that breaks existing tests.
6. Use the TodoWrite tool to track progress through build sequence.

---

## Success criteria

The spec is successfully executed when:

- [ ] All 10 pillars implemented and gated behind flags
- [ ] All existing tests still pass
- [ ] All new tests pass (unit + integration + contract + adversarial)
- [ ] Security gates pass (SBOM, signed artifacts, secret scan, threat-model checklist)
- [ ] All new endpoints documented in OpenAPI
- [ ] All new models registered in MLflow with model cards
- [ ] All new graph types documented in `docs/INTELLIGENCE-GRAPH.md`
- [ ] PR description references every checklist item in `07-BUILD-SEQUENCE.md`
- [ ] Branch rebases cleanly onto `main`

---

## Related existing documents

These remain the authoritative reference for what already exists:

- `docs/ARCHITECTURE.md` — current system architecture
- `docs/INTELLIGENCE-GRAPH.md` — current graph schema
- `docs/AGENT-CONTROLLER.md` — current agent runtime
- `docs/APPROVAL-MODEL.md` — current staged mutation workflow
- `docs/MODEL-EXTRACTION-DEFENSE.md` — existing defense mesh
- `docs/ML-TRAINING-GUIDE.md` — existing ML pipeline
- `docs/PRODUCTION-READINESS.md` — launch gates

**v-Next does not replace any of these.** It extends them.
