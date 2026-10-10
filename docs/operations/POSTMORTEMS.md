---
title: Incident Postmortems
slug: reliability/postmortems
section: operations
visibility: I
audience: [ops, buyer, architect]
status: beta
since_version: "0.1.0"
source_files: [services/api/governance/reliability/service.py, services/api/governance/reliability/routes.py]
related: [reliability/incident-response, reliability/operations]
canonical_owner: platform@aether
estimated_read_minutes: 3
source_hashes:
  "services/api/governance/reliability/routes.py": "sha256:aa8f7b1739acbda7065e85fd6c9a1e60805e542d4f60563adf3010ed7f35ee54"
  "services/api/governance/reliability/service.py": "sha256:71fe39c503316a915a02f154dececd6385e7e07ed074ddea7ddb24915551d20c"
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
