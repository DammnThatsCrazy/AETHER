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

- **React** is the `./react` entry point of `@aether/web`
  (`packages/sdk/web/src/react.tsx`), imported as `@aether/web/react`, not a
  separate package.
- **React Native** is a JS bridge. Batching, retry and the offline spool are
  meant to be enforced by the native iOS/Android SDKs it wraps
  (`delegated_native`). On Android the React Native package does not declare the
  native `com.aether.sdk` core as a dependency, so consumers must add it
  themselves. Manifest signature verification is delegated to native
  too: set `manifestPublicKey` and the native SDKs verify the manifests they
  fetch, while the JS manifest path verifies through `Aether.verifyManifest()`
  (see `sdks/manifest-signing`).
- The **server** SDK (`packages/sdk/server`) and the **Python** envelope builder
  (`packages/sdk/python`) are not columns here. By default the server SDK keeps a
  bounded in-process queue; setting `durable: true` or `spoolPath` selects the
  disk-backed `DurableEventQueue`, which persists accepted events and replays
  them at startup. The server SDK only forwards consent as an ingestion hint.
  The Python package has no client-side emit pipeline.
- The runtime-behaviour rows (observe, consent gating, batching, manifest fetch
  and signature verification, batch health, retry, offline queue) are recorded
  per SDK in `packages/shared/sdk-parity.json`, which is canonical.
  `scripts/validate_sdk_parity.py` checks that each claimed cell's evidence
  file and symbol exist; it does not prove the behavior is enforced end to end.
  Other validators cover other things (for example
  `scripts/validate_sdk_release_alignment.py` for versions and the publish
  workflow, and `scripts/validate_sdk_distribution_artifacts.py` for the web and
  React entry-point artifacts); the remaining rows here have no dedicated check.
