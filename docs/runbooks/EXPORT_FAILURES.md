---
title: Runbook — Export Failures
slug: runbooks/export-failures
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 2
source_files:
  - Backend Architecture/aether-backend/services/export/service.py
  - Backend Architecture/aether-backend/services/export/routes.py
  - Backend Architecture/aether-backend/repositories/artifacts.py
  - Backend Architecture/aether-backend/services/security/export_governance.py
last_synced_commit: "845b1c14"
---

# Runbook — Export Failures

Operate the durable export service when an export job is stuck, an artifact
won't download, or a tenant reports a missing/expired export. Every artifact
export runs as a durable job on the jobs platform — an export is never "ready"
until its bytes are persisted **and** their checksum re-verified. Inline row
responses (the legacy audit mode) still work on their original routes, but every
`/download` comes from a verified artifact.

## Lifecycle recap

`POST /v1/exports` → governance check (`authorize_create`) → durable
`export.generate` job → exporter produces rows → serialize (CSV formula-injection
safe) → `build_manifest` (sha256 + size + params-with-secrets-redacted) →
`ArtifactRepository.put` (Postgres BYTEA, 32 MB cap, 7-day TTL) →
**`repo.verify` re-checksums the stored bytes; a mismatch FAILS the job** →
`export.ready` event + inbox notification. Download re-authorizes
(`authorize_download`) every time and refuses expired/deleted artifacts.

Registered export domains (`GET /v1/exports/types`): `audit_log` (reference),
`targeting_package`, `governance_evidence_pack`. All exporters are read-only and
tenant-scoped.

## Triage

1. **Find the job.** `request_export` returns `{job_id, status_url}`. Inspect via
   `GET /v1/jobs/{id}` and `/{id}/events` — the export flow's whole timeline
   (queued → running → succeeded/failed, plus `export.ready`) lives there.
2. **Find the artifact.** `GET /v1/exports` lists the tenant's artifacts;
   `GET /v1/exports/{id}` returns metadata (sha256, size, expires_at, deleted_at,
   manifest). No content is served from these routes — only `/download` does.

## Symptoms → actions

### Export job stuck in `running` or landed `failed`
Read `GET /v1/jobs/{id}/events`. The handler heartbeats after the exporter runs;
a dead worker's lease is swept and the job requeues (at-least-once). A terminal
`failed` job carries the reason:
- `no exporter registered for '<type>'` — the `export_type` is not one of the
  registered exporters. Check `GET /v1/exports/types`; exporters self-register by
  decorator when `services/export/service.py` is imported at startup.
- `artifact exceeds 33554432 byte cap` — the serialized export is over the 32 MB
  `MAX_ARTIFACT_BYTES` limit. Narrow the export (time window, `sources`, a single
  `export_id`) and re-request; do not raise the cap without a storage review.
- `artifact checksum verification failed after write` — the stored bytes did not
  re-hash to the manifest sha256. This is the fail-closed guard doing its job:
  the job stays `failed` and no download is offered. Do NOT hand-serve the row;
  re-request the export, and if it recurs escalate — the artifact store is
  suspect.

### `POST /v1/exports` returns 403
`authorize_create` denied it. Causes: the caller lacks `export`/`admin`
permission, or the export governance policy blocked it (e.g. a cross-tenant
`target_tenant`). The route pins `target_tenant = tenant.tenant_id`, so a tenant
can only ever export its own data — a 403 here means a genuine permission gap,
not isolation being bypassed.

### Download returns 403 or 404
`GET /v1/exports/{id}/download` re-runs `authorize_download` on every call
(permissions can change after generation) and writes the download audit record.
- **403 `audit export has expired`** — the artifact is past `expires_at`. Expired
  content is physically gone (see below); re-request a fresh export.
- **404 `export artifact (deleted)` / `(expired)`** — the row is a tombstone (id,
  sha256, manifest retained; `content` NULLed). Expected after a `DELETE` or the
  expiry sweep. Re-request.
- **404 `export artifact`** — no artifact with that id for this tenant. Confirm
  the id and that the generating job actually succeeded.

### Tenant reports an artifact "disappeared"
Artifacts have a 7-day TTL. The `export.expire_sweep` job (and the supervised
`run_export_expiry_sweep_loop`) NULLs the content of expired rows and stamps
`deleted_at`, keeping the tombstone for audit. This is by design, not data loss —
the manifest + checksum remain as proof the export existed. Re-request to
regenerate.

### Checksum mismatch reported by a downstream consumer
Every download sets `X-Checksum-SHA256`. A consumer whose local hash differs
should re-download (transport corruption) before escalating; the stored bytes are
verified at write time and again by `repo.verify`, so a persistent mismatch means
the transport, not the artifact.

## Escalation

If `verify` fails on generation twice, or the expiry sweep is not reclaiming
storage, capture the `export.generate` job's `job_events` and the artifact
metadata (id, sha256, size, expires_at) and escalate to `platform@aether`. Do not
disable the checksum-verify guard or hand-serve unverified bytes.
