---
title: Derivatives Release Readiness Source of Truth
slug: source-of-truth/derivatives-release-readiness
section: operations
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: "8.11.0"
---

# Derivatives Release Readiness Source of Truth

The PR5 release source of truth is `services/derivatives/multi_venue.py` plus `services/derivatives/ml_release.py`. These files define the canonical multi-venue parity report, deterministic intelligence validation, ML governance cards, coordinated-behavior safeguards, load and recovery matrices, provider licensing controls, deployment profiles, and strict release gate keys.

The strict release gate fails closed when adapters leak provider-specific APIs, markets cannot resolve, graph evidence is missing, replay is nondeterministic, credentials are not read-only, cross-tenant tests fail, OpenAPI or generated docs are stale, required runbooks are absent, staging ingestion is not represented, SLOs are unmet, model governance is absent, licensing controls are absent, or entitlement enforcement is frontend-only.
