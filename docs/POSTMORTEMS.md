---
title: Incident Postmortems
slug: reliability/postmortems
section: operations
visibility: I
audience: [ops, exec, architect]
status: beta
since_version: "9.0.0"
source_files:
  - Backend Architecture/aether-backend/services/reliability/service.py
  - Backend Architecture/aether-backend/services/reliability/routes.py
related:
  - reliability/incident-response
  - reliability/operations
canonical_owner: platform@aether
estimated_read_minutes: 3
last_synced_commit: c63cb2f
---
# Incident Postmortems

Postmortems capture the learning from significant incidents. Runbooks indicate
when a postmortem is required (`postmortem_required`), and incidents can be moved
to `postmortem_pending`.

## Postmortem model

| Field | Notes |
|---|---|
| `postmortem_id`, `incident_id` | Identity + linkage |
| `summary` | What happened |
| `timeline` | Ordered events |
| `root_cause` | Primary cause |
| `contributing_factors` | Secondary causes |
| `customer_impact` | Observed impact |
| `detection_gap`, `mitigation_gap` | Where response fell short |
| `prevention_actions` | Follow-up actions |
| `owner_id` | Accountable owner |
| `status` | `draft` / `reviewed` / `closed` |

## Process

1. Incident reaches `postmortem_pending`.
2. Draft postmortem created (`status: draft`).
3. Reviewed by owners (`reviewed`).
4. Closed once prevention actions are tracked (`closed`).

## APIs

- `GET /v1/admin/kyber/postmortems`
- `POST /v1/admin/kyber/postmortems`
- `PATCH /v1/admin/kyber/postmortems/{postmortem_id}`

## Tenant-safe vs internal

Postmortems are **internal only**. No postmortem content is exposed to tenants;
tenant-facing communication is limited to incident `customer_impact`.

## Known gaps

- Prevention-action tracking is free-text; structured action items are planned.

## Rollout notes

- Postmortems are linked to incidents by `incident_id`; the Kyber Incident Detail
  view surfaces the linked postmortem id when present.
