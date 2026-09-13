---
title: Readme
slug: archive/readme
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Archive

Historically useful material that no longer represents current runtime.

- **`legacy-spec/`** — pre-v8 SDK spec `.ts` files that were never wired into
  any `packages/*` build. They are preserved because the original module
  boundaries and event taxonomy are still referenced by older audits. The
  canonical SDK contracts now live in `packages/shared/*.ts`.
- **`audits/`** — point-in-time design, privacy, web3-coverage, profile-360,
  population-omniview, and release-hardening audits. Kept for provenance.

**Do not treat anything here as authoritative.** The single source of truth
for SDK behavior is `packages/shared/`, `packages/{web,ios,android,react-native}/`,
and `docs/source-of-truth/`.
