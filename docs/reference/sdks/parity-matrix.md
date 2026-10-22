---
title: SDK Parity Matrix
slug: sdks/parity-matrix
section: reference
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: 0.1.0
---

# SDK Parity Matrix

| Capability | Web | React | React Native | iOS | Android |
|---|---|---|---|---|---|
| Installable package | Alpha | Alpha | Alpha | Alpha | Alpha |
| Tenant/app/site config | Alpha | Alpha | Alpha | Alpha | Alpha |
| First heartbeat | Alpha | Alpha | Alpha | Alpha | Alpha |
| Session lifecycle | Alpha | Alpha | Alpha | Alpha | Alpha |
| Page/screen view | Alpha | Alpha | Alpha | Alpha | Alpha |
| Custom event | Alpha | Alpha | Alpha | Alpha | Alpha |
| Identity hint | Alpha | Alpha | Alpha | Alpha | Alpha |
| Batch emit to `/v1/batch` | Alpha | Alpha | Alpha | Alpha | Alpha |
| Offline spool | Alpha | Alpha | Alpha | Alpha | Alpha |
| Idempotent retry | Alpha | Alpha | Alpha | Alpha | Alpha |
| Privacy controls | Alpha | Alpha | Alpha | Alpha | Alpha |
| Version metadata | Alpha | Alpha | Alpha | Alpha | Alpha |
| Diagnostics/debug mode | Alpha | Alpha | Alpha | Alpha | Alpha |

## Reading this table

"Alpha" means the capability exists at `0.1.0-alpha.0` and may change before a
stable release; it is not a production-readiness claim.

- **React** is the `react` entry point of `@aether/sdk-web`
  (`packages/sdk/web/src/react.tsx`), not a separate package.
- **React Native** is a JS bridge. Batching, retry and the offline spool are
  enforced by the native iOS/Android layers it wraps (`delegated_native`).
- The **server** SDK (`packages/sdk/server`) and the **Python** envelope builder
  (`packages/sdk/python`) are not columns here. The server SDK keeps a bounded
  in-process queue with no cross-restart persistence and only forwards consent as
  an ingestion hint; the Python package has no client-side emit pipeline.
- The runtime-behaviour rows (observe, consent gating, batching, manifest fetch
  and signature verification, batch health, retry, offline queue) are governed
  per SDK by `packages/shared/sdk-parity.json`, which is canonical and
  validator-enforced (`scripts/validate_sdk_parity.py`). The remaining rows are
  not machine-checked.
