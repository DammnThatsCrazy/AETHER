---
title: Derivatives Release Readiness Source of Truth
slug: source-of-truth/derivatives-release-readiness
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: "0.1.0"
---

# Derivatives Release Readiness Source of Truth

The PR5 release source of truth is `services/api/value/derivatives/multi_venue.py`, which defines the canonical multi-venue parity report. (The `ml_release.py` module that carried hard-coded governance, licensing and load attestations nothing enforced was removed; the strict release gate described below is therefore a requirement list, not a gate that runs today.)

A strict release gate must fail closed when adapters leak provider-specific APIs, markets cannot resolve, graph evidence is missing, replay is nondeterministic, credentials are not read-only, cross-tenant tests fail, OpenAPI or generated docs are stale, required runbooks are absent, staging ingestion is not represented, SLOs are unmet, model governance is absent, licensing controls are absent, or entitlement enforcement is frontend-only.
