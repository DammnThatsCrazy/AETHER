---
title: Temporal Integrity Plane Source of Truth
status: stable
source_files:
  - Backend Architecture/aether-backend/shared/temporal/instant.py
  - Backend Architecture/aether-backend/shared/temporal/zones.py
  - Backend Architecture/aether-backend/shared/temporal/clock.py
  - Backend Architecture/aether-backend/shared/temporal/windows.py
  - Backend Architecture/aether-backend/shared/temporal/recurrence.py
  - Backend Architecture/aether-backend/shared/temporal/envelope.py
  - Backend Architecture/aether-backend/shared/temporal/authority.py
  - Backend Architecture/aether-backend/services/ingestion/temporal_enforcement.py
  - Backend Architecture/aether-backend/services/temporal_preferences/routes.py
  - packages/shared/temporal.ts
  - packages/shared/contracts/temporal-policy-registry.json
  - frontend/shared/src/time/format.ts
  - frontend/shared/src/time/time-provider.tsx
  - scripts/validate_temporal_integrity.py
last_synced_commit: c6d0e08
---

# Temporal Integrity Plane

## Canonical invariant

> All exact moments are stored and ordered as UTC instants. Source-local
> temporal context is retained as evidence. Calendar-based operations are
> evaluated using an explicitly registered temporal authority. Interactive
> presentation is localized to the current viewer by default.

## Ownership

| Concern | Canonical owner |
|---|---|
| Strict instant parsing / canonical `Z` serialization | `shared/temporal/instant.py` (`parse_instant_strict` rejects naive values with stable reason codes) |
| IANA zone validation (abbreviations rejected), offset facts, tzdb version | `shared/temporal/zones.py` |
| Injectable clocks (no test touches the real wall clock) | `shared/temporal/clock.py` |
| DST-safe local windows (half-open `[start, end)`) + wall-clock recurrence with gap/overlap policies | `shared/temporal/windows.py`, `shared/temporal/recurrence.py` |
| Temporal authorities, skew/lag math, state classification | `shared/temporal/authority.py` |
| Event temporal envelope + bitemporal graph envelope (Py mirror of `graph-contract.ts`) | `shared/temporal/envelope.py` |
| Reason-code dispositions, mode ladder, per-family skew/lateness bounds | `packages/shared/contracts/temporal-policy-registry.json` → generated twins via `scripts/generate_platform_contracts.py` |
| Ingestion enforcement (off → shadow → warn → enforce, canary-scoped) | `services/ingestion/temporal_enforcement.py` + the hook in `services/ingestion/batch.py` |
| Viewer/tenant temporal preferences (display only, never business authority) | `services/temporal_preferences/` |
| Frontend formatting (the ONLY sanctioned Intl home) + time lenses | `frontend/shared/src/time/` |
| Static gates + shrink-only debt allowlists | `scripts/validate_temporal_integrity.py`, `scripts/allowlists/temporal_*.json` |

## Enforcement ladder

`AETHER_TEMPORAL_ENFORCEMENT_MODE` (default `off`, canary-scoped via
`AETHER_TEMPORAL_CANARY_TENANTS`): reason codes and meters
(`ingestion_temporal_state_total`, `ingestion_temporal_reason_total`,
`ingestion_temporal_blocked_total`) are computed identically in every active
mode, so shadow telemetry predicts enforcement impact. The computed envelope
rides the normalized payload (`temporal` key) into Bronze. SDK-supplied
context fields (`timezone`, `utcOffsetMinutes`, `timeZoneSource`,
`clockSource`) are evidence only — the server computes the authoritative
envelope.

## Non-negotiables

- Never attach an assumed timezone to a naive timestamp — reject or record
  the reason code; quarantine dispositions come from the registry, not code.
- Timezone abbreviations (`EST`, `GMT`, `Zulu`) are never persistent
  calendar authorities.
- A calendar period is not a fixed duration (one month ≠ 30 days); adjacent
  local windows partition without gap or overlap.
- Viewer presentation never changes billing, retention, reward, or security
  truth; those resolve their own registered authority.
- New date/time logic outside the kernel/time-layer fails CI
  (`make temporal-integrity`); the debt allowlists only shrink.
