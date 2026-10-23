---
title: "Unreleased"
slug: releases/unreleased
section: changelog
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Unreleased

Changes not yet assigned to a pre-release version.

## Added

- Repository truth reset documentation structure
- Source-of-truth documentation model
- SDK parity matrix
- Connector lifecycle documentation
- Architecture decision records
- Root gateway documents (`ARCHITECTURE.md`, `RELEASES.md`, `DEVELOPMENT.md`)
- Root-layout and deprecated-language validation gates

## Changed

- SDK manifest signatures now work end to end. The backend signs each delivered manifest with ES256 (ECDSA P-256) over a canonical JSON form, derived from `SDK_CONFIG_SECRET` so clients only need a public key; web, iOS and Android verify it with `manifestPublicKey` (print it with `scripts/sdk_manifest_public_key.py`). Previously the backend signed one payload with a server secret while the web and native clients verified two different, incompatible payloads with a client-held HMAC key, so no client could verify a real manifest. Specification and shared test vectors: `docs/reference/sdks/manifest-signing.md`, `tests/fixtures/sdk/manifest-signing-vectors.json`.
- The iOS and Android SDKs read the remote manifest from the top level of the response instead of the `data` envelope the backend returns, so they never applied one. They now unwrap the envelope.
- The web SDK no longer skips manifest verification when WebCrypto is unavailable; with a public key configured it now fails closed.
- React Native stopped advertising `manifestSignatureVerification` (now `false`); no verification path exists there yet, and `sdk-parity.json` records it as `unsupported`.
- Reorganized legacy root architecture folders
- Normalized version to `0.1.0-alpha.0`
- First external SDK release target is `0.1.0-alpha.0`
- The `economic360` projection now displays as `Value 360`
