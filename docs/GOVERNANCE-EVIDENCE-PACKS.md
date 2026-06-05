---
title: Governance Evidence Packs
slug: enterprise/governance-evidence-packs
section: enterprise
visibility: I
audience: [exec, buyer, security]
status: stable
since_version: "13.0.0"
---

# Governance Evidence Packs

`EvidencePackService` (`services/security/evidence_packs.py`) generates
**security-review evidence** packs that summarize a control area for a buyer's
security team.

## Implemented controls

- Pack types: `access_control`, `tenant_isolation`, `audit_logging`,
  `data_retention`, `integration_security`, `ai_recommendation_governance`,
  `operator_access`.
- Each pack includes: a **control summary**, **relevant policies**, **audit-event
  summaries**, **verifier results** (where applicable), **known gaps**, a
  `generated_at` timestamp, an `expires_at`, and an `integrity_hash`.
- Status lifecycle: `queued → generated` (or `failed`/`expired`).
- Generated and listed via Kyber:
  `GET /v1/admin/kyber/security/governance-evidence-packs`,
  `POST /v1/admin/kyber/security/governance-evidence-packs/generate`.

## Purpose

These packs are designed to accelerate an enterprise/government **security
review** by presenting demonstrable controls and their gaps in one artifact.

> **Not a certification.** A pack is evidence of implemented software behavior. It
> is **not** SOC 2, ISO 27001, FedRAMP, or any other attestation, and must not be
> represented as one. Known gaps are included in every pack precisely so the
> representation stays honest.

## Planned controls

- Signed, exportable PDF/zip artifacts with an external integrity anchor.
- Scheduled regeneration tied to verifier runs.

## Known gaps / not certified

- The `integrity_hash` covers pack contents at generation time; it is not an
  externally notarized signature. No certification is claimed.
