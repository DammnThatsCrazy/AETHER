---
title: SDK Manifest Signing
slug: sdks/manifest-signing
section: reference
visibility: P
audience: [dev-junior, dev-senior]
status: beta
since_version: 0.1.0
source_files: [services/api/ingestion/sdk_config/manifest_signing.py, services/api/ingestion/sdk_config/service.py, packages/sdk/web/src/health/manifest-signature.ts, packages/sdk/android/src/main/java/com/aether/sdk/Manifest.kt, packages/sdk/ios/Sources/AetherSDK/ManifestSignature.swift, tests/fixtures/sdk/manifest-signing-vectors.json]
canonical_owner: sdk@aether
estimated_read_minutes: 6
toc_depth: 3
---

# SDK Manifest Signing

The remote SDK manifest (`GET /v1/config/sdk/manifest`) carries feature flags,
endpoint overrides and rollout settings that change how an installed SDK behaves.
It is signed so that an SDK configured with the platform's **public key** applies
only manifests the backend produced, and otherwise keeps its last known-good
configuration.

This page is normative. The backend (`manifest_signing.py`), the web verifier
(`manifest-signature.ts`), the Android verifier (`Manifest.kt`) and the iOS
verifier (`ManifestSignature.swift`) all implement it, and all four are tested
against the same vectors in `tests/fixtures/sdk/manifest-signing-vectors.json`.

## Scheme

| Item | Value |
|---|---|
| `signature_alg` | `ecdsa-p256-sha256` (ES256) |
| Signature | base64url, **unpadded**, of the 64-byte raw `r ‖ s` (IEEE P1363), always 86 characters |
| Public key | base64url, unpadded, of the DER `SubjectPublicKeyInfo` for a P-256 key |
| Signed bytes | UTF-8 of the canonical JSON of the manifest object **without** `signature` |

`signature_alg` is part of the signed object, so an attacker cannot downgrade the
algorithm or strip it: a manifest whose `signature_alg` is missing or is not
exactly `ecdsa-p256-sha256` is rejected before any cryptography runs.

### Why asymmetric

An earlier design used HMAC-SHA256 with `SDK_CONFIG_SECRET` as the verification
key. A client-side HMAC key has to ship inside every app, and anyone who extracts
it can forge manifests for every tenant. With ES256 only the server holds a
signing key; clients hold a public key that is safe to publish.

The signing key is derived deterministically from `SDK_CONFIG_SECRET`
(HKDF-SHA256, info `aether.sdk-manifest.signing.v1`, 48 bytes reduced into the
P-256 scalar range). No new secret has to be provisioned, and the secret itself
never leaves the server.

## Canonical JSON

The signed bytes are produced by one deterministic serialization:

1. Objects: keys sorted by code point (all keys must be ASCII, so this equals
   UTF-16 order), no whitespace, `{"k":v,...}`.
2. Arrays: element order preserved, `[v,...]`.
3. Strings: UTF-8, with only these escapes — `\"`, `\\`, `\b`, `\f`, `\n`, `\r`,
   `\t`, and any other code point below U+0020 as lowercase `\u00xx`. Everything
   else (including `/`, DEL, U+2028/2029 and astral characters) is written
   literally.
4. Integers: base-10, no leading zeros, no `+`, no exponent, within ±(2^53 − 1).
5. `true`, `false`, `null`.
6. **Fractional numbers are not representable.** A manifest containing one cannot
   be signed (the backend rejects publishing it with HTTP 400) and a verifier
   rejects it. JSON parsers disagree about number formatting, and no manifest
   field needs a fraction. Note that some parsers cannot tell `1.0` from `1`;
   the backend never emits the former, so this does not affect valid manifests.

Every field of the manifest object is signed, including ones a given client does
not use (`endpoints`, `flags`, `source`, `publisher_id`). A field added after
signing therefore invalidates the signature.

## Verification procedure

Given the parsed manifest object (the contents of the response's `data`
envelope) and the configured public key:

1. `signature` must be a string matching `^[A-Za-z0-9_-]{86}$`.
2. `signature_alg` must equal `ecdsa-p256-sha256`.
3. Remove `signature`, canonicalize the rest, encode as UTF-8.
4. Import the public key; it must be a P-256 `SubjectPublicKeyInfo`.
5. Verify the ECDSA signature (SHA-256) over those bytes.

Any failure, malformed input, missing cryptography or unsupported platform
returns **false**. Verification never throws to its caller and never fails open.

## Client behavior

| Public key configured | Manifest | Result |
|---|---|---|
| yes | valid signature | applied |
| yes | unsigned, malformed, tampered, wrong key, downgraded | **rejected**; last known-good config kept |
| no | anything | applied **without verification** |

Production apps should always configure the public key. Without it the SDK cannot
distinguish a genuine manifest from a forged one.

| SDK | Configuration | Verifier |
|---|---|---|
| web | `advanced.manifestPublicKey` | WebCrypto ECDSA (`crypto.subtle`); fails closed if unavailable |
| Android | `AetherConfig.manifestPublicKey` | `java.security` `SHA256withECDSA` |
| iOS | `AetherConfig.manifestPublicKey` | CryptoKit `P256.Signing` |
| React Native | `manifestPublicKey` in `AetherRNConfig` | the native iOS/Android verifier (Hermes has no WebCrypto): forwarded to the native SDKs at init, and `Aether.verifyManifest()` is used by the JS manifest path; fails closed if the native method is missing |

The backend response wraps the manifest in the standard `APIResponse` envelope
(`{"data": {...}}`); clients verify the object inside `data`.

## Getting the public key

```bash
SDK_CONFIG_SECRET=... python scripts/sdk_manifest_public_key.py
```

The backend signs each manifest **when it is delivered**, so a stored version is
never served with a stale signature. Rotating `SDK_CONFIG_SECRET` changes the
public key: ship the new key in an app update first, because clients holding the
old key reject newly signed manifests and keep their last known-good config.

## Test vectors

`tests/fixtures/sdk/manifest-signing-vectors.json` holds the public key, the
canonicalization cases (including rejected inputs), and signed and tampered
manifests with the expected verdict. It is generated by
`scripts/generate_sdk_manifest_vectors.py`; ECDSA signatures are randomized, so
regenerate it only when this specification changes.

## Known gaps

- The Python and server SDKs do not fetch manifests and are out of scope.
- The React Native Android package does not yet declare the native `com.aether.sdk`
  core as a dependency, so consumers must add it themselves (this predates manifest
  signing and affects every native feature of the bridge).
