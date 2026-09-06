---
title: Execution State — Reconciled Control Plane (Phase 0)
slug: productization/reconciled-control-plane/execution-state
section: operations
visibility: I
audience: [architect, ops, exec]
status: experimental
since_version: "8.12.0"
canonical_owner: platform@aether
---

# Execution State — Reconciled Control Plane (Phase 0)

> **Delivery model:** Phase 0 ships as a stacked lane
> (`feat/reconciled-control-plane`) on the SDK-universal-ingestion integration
> head (`ws/lane0-basefix` @ `1b616a62`) and is meant to ride the same merged
> program. The canonical gate is env-stripped `make ci-check` = 0 at the lane
> tip, docs-drift strict clean, generated docs regenerated, `git status` empty.

## Phase 0 — managed-integration abstraction + reconcile skeleton

**Delivered.** A reconciliation *skeleton* with durable state and a read-only
operator surface — flag-gated OFF, additive, fail-closed. Governing principles
and boundary: `docs/architecture/RECONCILED_CONTROL_PLANE.md`.

| Deliverable | Evidence |
|---|---|
| Contract-Spine twin extension (`packages/shared/managed-integrations.ts` ↔ `services/managed_integrations/contracts.py`) | `tests/contracts/test_managed_integrations_parity.py` (const-array + barrel parity) |
| Governance domain `reconciled_control` (twin + explicit operator grants, out of `ALL_DOMAINS`) | `tests/unit/test_security_governance_domain_twin.py::test_reconciled_control_domain_is_in_both_sides` |
| Desired-state + observed-state assembly from existing authorities | `desired_policy.py` / `sensors.py` (read-only, evidence-backed) |
| Reconcile classification (§32 steps 1–11) | `tests/unit/reconciled_control/` (match/actionable/blocked/unknown + CP-12 distinctness + flag-OFF parity) |
| Durable `managed_integrations` + `reconcile_runs` + direct-SQL repos | alembic `20260906_rcp_managed_integrations.py` (additive, migration-safety + temporal-integrity clean); `Backend Architecture/aether-backend/tests/managed_integrations/` |
| Read-only operator surface | `services/managed_integrations/routes.py` (2 GETs), mounted in `main.py` behind `reconciled_control.enabled AND kyber_route_enabled` (default OFF) |
| Registries + docs | `docs/source-of-truth/repo_consistency_ownership.json` category `reconciled_control_plane`; architecture + phases + this page authored. `config/implementation_ledger.yaml` is reserved for founding-tenant/release-governance items (no prior lane — data-exchange, financial-normalization — adds lane rows); this lane follows that precedent and adds none. |

### Honest boundaries (Phase 0)

- **No live reconcile trigger and no actuator.** No scheduler runs in Phase 0;
  the reconcile function is exercised by tests only. Applying a ChangeSet is
  explicitly deferred (CP-08 boundary). Production flips are Phase 1+.
- **No route-registry capability declaration.** The operator GETs are covered
  by the `/v1/admin/kyber/*` known-prefix default-deny classification and the
  handler Kyber-operator gate. A `kyber_routes` capability declaration needs a
  reconciled-control capability in the separate Kyber workforce capability
  vocabulary — reserved for the later console phase.
- **Blueprint truncated at §40.** The §41+ spec remainder was unavailable at
  Phase-0 planning time and must be reviewed before later phases.

## Phase 1+ — reserved

Live reconcile hook, integration registration, ChangeSet/actuator engine,
drift automation and the Kyber console surface are reserved; see
`docs/plans/RECONCILED_CONTROL_PHASES.md`. Nothing past Phase 0 is claimed.
