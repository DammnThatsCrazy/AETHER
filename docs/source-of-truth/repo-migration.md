---
title: Repository migration map
slug: source-of-truth/repo-migration
section: reference
visibility: I
audience: [dev-senior, architect, ops]
status: stable
since_version: 0.1.0
canonical_owner: platform@aether
---

# Repository migration map

PR #627 established the repository-truth contract, but its first landing did
not physically move the implementation tree. This follow-up closes that gap.
The root now contains entry points and configuration; active implementation
trees use the canonical paths below, while retired duplicates remain available
only as historical archive material.

## Canonical paths

| Former root-era tree | Current path | State |
|---|---|---|
| `Backend Architecture/aether-backend/` | `services/backend/` | Deployed Python backend, ingestion, lake, graph, and intelligence |
| Former standalone journey service | `services/backend/services/measurement/` | Active journey compilation, persistence, attribution, and API surface; archived FSM fixture is test-only |
| `ML Models/aether-ml/` | `services/ml/` | ML training, serving, and model governance support |
| `Agent Layer/` | `services/agents/` | Internal broker-coupled workers; registered, not independently deployable |
| `GDPR & SOC2/aether-compliance/` | `services/compliance/` | Compliance control implementation |
| `AWS Deployment/aether-aws/` | `deploy/aws/` | AWS and Terraform deployment implementation |
| `Smart Contracts/` | `contracts/smart-contracts/` | EVM and multi-chain contract project |
| `Data Ingestion Layer/` | `docs/archive/legacy-architecture/data-ingestion-layer/` | Deprecated, un-deployed TypeScript duplicate |
| `Data Lake Architecture/` | `docs/archive/legacy-architecture/data-lake-architecture/` | Deprecated, un-deployed TypeScript duplicate |
| Backend orphan modules and service shells | `docs/archive/legacy-architecture/backend/` | Deprecated historical material |

## Consumer surfaces updated

The migration updated the path consumers that can affect behavior or repository
truth:

- GitHub Actions, Docker build contexts, Makefile subsystem variables, and
  Terraform working directories;
- `config/impact_graph.json`, verification routing, test inventory, readiness
  artifacts, and ownership registries;
- backend runners, generators, validators, parity tests, and release tooling;
- README/development/architecture docs and source-linked documentation paths;
- CODEOWNERS, ignore rules, deployment manifests, and contract-analysis paths.

Historical changelog entries continue to use the paths that existed when those
features shipped. Current and generated documentation must use the canonical
map above.

## Intentional support roots

Not every top-level directory is a deployable service. The following roots are
deliberately retained as support surfaces and are not missing migrations:

| Root | Ownership and meaning |
|---|---|
| `config/` | Canonical registries, policy, readiness, and verification configuration |
| `scripts/` | Repository generators, validators, release checks, and operator tooling |
| `security/` | Active shared model-extraction defense package used by runtime services |
| `tests/` | Cross-surface verification suites; not an application runtime |
| `artifacts/` | Tracked readiness and generated evidence artifacts |
| `reports/` | Authored audit, delivery, and productization evidence; not runtime code |
| `cicd/` | Legacy/fixture CI package retained for compatibility; GitHub Actions remains the hosted authority |
| `data-modules/` | Static chain, protocol, and wallet reference data |
| `lambda/` | Small AWS operational entry points, not a service tree |
| `playground/` | Local SDK demonstration app |
| `release-evidence/` | Profile and credential-readiness evidence bundles |

These roots are included in the ownership and impact-graph review where they
can affect CI or release evidence. They must not be mistaken for alternate
backend, ML, agent, compliance, deployment, or contract implementations.

## Enforcement

`scripts/validate_canonical_ingestion_trees.py` and
`scripts/allowlists/repo_tree_ownership.json` register the canonical service
units and archived legacy units. The gate fails when a tracked tree disappears
without a reviewed registry update or when a new unregistered tree appears.
`config/impact_graph.json` is the build-selection authority and includes the
canonical active paths, so a path-only change cannot silently bypass the right
verification lane.

The remaining product gaps in the ingestion blueprint are functional workstream
items, not repository-layout ambiguity. They remain classified in
[`REPO_TRUTH_AND_GAP_MATRIX.md`](../productization/sdk-universal-ingestion-alignment/REPO_TRUTH_AND_GAP_MATRIX.md).
