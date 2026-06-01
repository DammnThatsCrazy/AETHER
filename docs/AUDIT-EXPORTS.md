# Audit Exports

Audit exports provide tenant-scoped evidence for graph-native recommendations, decisions, actions, dispatches, outcomes, playbook runs, agent governance, tenant value, and package readiness.

## Implemented formats

- `json`: primary generated payload.
- `csv`: supported for table-shaped exports.
- `pdf_summary`: structured summary placeholder; full PDF rendering is future work unless a PDF service is later wired in.

## Export types

- `recommendation_audit`: recommendations, evidence references, confidence breakdown, policy flags, data freshness, and status lifecycle.
- `decision_audit`: decisions, actor ID, selected/rejected actions, approval status, reasons/comments, and timestamps.
- `action_dispatch_audit`: actions, dispatches, delivery receipts, authorization metadata presence, status transitions, and idempotency keys.
- `outcome_audit`: outcomes, values, labels, confidence deltas, and observed windows.
- `playbook_run_audit`: playbook definition, run history, generated recommendations, linked decisions/actions/outcomes, and ROI metrics.
- `agent_governance_audit`: agent recommendations, approvals, actions, dispatches, outcomes, policy flags, and governance notes.
- `tenant_value_audit`: outcome ledger summary, playbook ROI, recommendation family performance, observed/pending value, and success/failure/neutral counts.
- `package_readiness_audit`: solution packages, readiness reports, deployment modes, and known gaps.

## Permission and isolation model

Tenant-facing endpoints require authenticated tenant permissions and force the requested `tenant_id` to match the active tenant. Exports never include cross-tenant records. Admin-only package readiness exports require admin/export intent. Raw secrets, API keys, webhook secrets, tokens, and password-like fields are redacted.

## Endpoints

- `GET /v1/intelligence/audit-exports/types`
- `POST /v1/intelligence/audit-exports`
- `GET /v1/intelligence/audit-exports/{export_id}`
- `GET /v1/intelligence/audit-exports/{export_id}/download`

Each generated export includes an `integrity_hash` over the generated payload and expires after seven days.
