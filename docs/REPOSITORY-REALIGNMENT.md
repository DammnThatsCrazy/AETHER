# Repository realignment

## Purpose

Aether is a pre-release monorepo. This plan makes the repository describe the
implemented platform rather than preserving each historical layout as an equal
entry point. It is the organizing record for the realignment branch; follow-up
commits should stack here and remain independently reviewable.

## Canonical map

| Concern | Canonical location | Rule |
| --- | --- | --- |
| Platform behavior | `docs/source-of-truth/` | Resolve contradictory prose in favor of these pages. |
| Shared contracts | `packages/shared/contracts/` | Generate TypeScript, Python, and documentation mirrors; do not hand-edit mirrors. |
| Client observation | `packages/web/`, `packages/ios/`, `packages/android/`, `packages/react-native/` | SDKs observe and send canonical batches; they do not own intelligence. |
| Runtime services | `Backend Architecture/aether-backend/` | Own enrichment, policy, identity, graph, projections, and APIs. |
| Product applications | `frontend/` and `apps/` | Separate customer, operator, documentation, marketing, demo, and mobile surfaces. |
| Generated inventory | `docs/_generated/`, `docs/REPO-INDEX.md`, `docs/AUTOMATION.md` | Change generators or source inputs, never generated output alone. |

## Architecture narrative

The canonical flow is:

1. Thin SDKs, provider connectors, signed webhooks, imports, and replays create observations.
2. SDK observations enter through `POST /v1/batch`; server-side sources use their governed ingestion adapters.
3. Bronze retains raw immutable evidence, Silver validates and normalizes it, and Gold materializes features and metrics.
4. Contract-governed projections update graph and outbox surfaces.
5. Lenses and 360 views expose evidence-backed intelligence to Kyber, Aether, Noesis, and tenant runtimes.

SDKs are not provider connectors. Connectors hold server-side provider credentials
and retrieval logic; SDKs are consent-gated observation clients. Compatibility
paths may remain while consumers migrate, but they are not new extension points.

## Documentation taxonomy

- **Source of truth:** normative contracts and behavior.
- **Architecture:** current system boundaries and decisions.
- **Guides and runbooks:** task-oriented build and operations material.
- **Readiness and evidence:** dated control evidence, never certification by implication.
- **Generated:** inventories derived deterministically from code and contracts.
- **Archive:** historical context that is explicitly non-normative.

Every maintained page should have one role. Duplicate explanations should link
to a canonical page rather than silently diverge.

## Migration sequence

1. Establish pre-release version and release-history policy.
2. Correct root navigation and the primary architecture narrative.
3. Classify documentation and contain legacy material.
4. Normalize SDK, connector, provider, and ingestion vocabulary.
5. Propose physical path moves separately, with import, build, ownership-map,
   deployment, and source-linked documentation updates in the same commit.
6. Remove compatibility trees only after references and consumers are proven absent.

Physical directory movement is intentionally not part of the first pass. Large
moves obscure semantic review and can invalidate deployment paths; each move
must be its own evidenced migration.

## Completion controls

Every stacked commit follows `AGENTS.md`, the ownership map in
`docs/source-of-truth/repo_consistency_ownership.json`, and the canonical
generation and CI gates. A clean directory tree alone is not evidence that the
runtime, contracts, docs, and release surfaces agree.
