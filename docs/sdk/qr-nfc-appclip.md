---
title: QR, NFC & App Clip Attribution
slug: sdk/qr-nfc-appclip
section: sdks
visibility: I
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 6
---

# QR, NFC & App Clip Attribution

The SDKs attribute QR codes, NFC tags, and iOS App Clip invocations by routing
the decoded URL/URI through the **same canonical `AcquisitionEvidence` parser**
used for deep links (schema v3, `packages/shared/acquisition-evidence.ts`). The
SDK **observes evidence and names the entry method; the backend classifies.**

## Division of responsibility (important)

**The host app performs the hardware read; the SDK attributes the result.**

- The SDK does **not** access the camera or decode QR images.
- The SDK does **not** drive the NFC radio or parse NDEF records.
- The host app owns the scan/read (e.g. `AVCaptureSession` / `VNBarcode…`,
  `CoreNFC`, `NfcAdapter`) and hands the SDK the already-decoded URL/URI string.

The SDK then parses `aether_ref` / UTM / click IDs, sanitizes the URL (the
opaque `aether_ref` token and click IDs never appear in transmitted URL
strings), sets `destinationDomain`, and persists first/latest-touch evidence —
identical to the deep-link path.

## Events and entry methods

| Source | Entry method | Event |
|---|---|---|
| QR code | `qr_code` | `qr_code_scanned` |
| NFC tag | `nfc` | `nfc_tag_read` |
| App Clip via `NSUserActivity` (web URL) | `ios_universal_link` | `app_clip_invoked` |
| App Clip via invocation URL | `manual_sdk_evidence` | `app_clip_invoked` |

All four are `analytics`-purpose, consent-gated, `behavioral` events. Nothing
leaves the device without `analytics` consent.

## Android

```kotlin
// Host app decoded the QR payload; SDK attributes it.
Aether.handleQrScanResult(decodedUrl)

// Host app read the NFC tag URI; SDK attributes it.
Aether.handleNfcUri(decodedUri)
```

## iOS

```swift
// QR / NFC — host app supplies the decoded URL.
Aether.shared.handleQrScanResult(decodedURL)
Aether.shared.handleNfcUri(decodedURL)

// App Clip handoff via NSUserActivity (Universal-Link style web URL).
func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
    Aether.shared.handleAppClipInvocation(userActivity)
}

// Or directly from an App Clip invocation URL.
Aether.shared.handleAppClipInvocation(url: invocationURL)
```

**App Clip → full-app handoff.** An App Clip invocation persists **first-touch**
evidence. When the user later installs the full app, that install inherits the
source through the existing first-touch / deferred-handoff persistence — no
probabilistic fingerprint matching is used. Deferred attribution is
deterministic only.

## React Native

Identical method names across platforms:

```ts
Aether.attribution.handleQrScanResult(decodedUrl);
Aether.attribution.handleNfcUri(decodedUri);
```

Both delegate to the native canonical parser; deduplication and first/latest
touch persistence happen natively.

## Guarantees

- **One parser.** QR/NFC/App Clip reuse the deep-link evidence parser — there is
  no second, divergent code path.
- **URL sanitization.** Transmitted URLs are stripped of the `aether_ref` token,
  click IDs, and fragments; the token only ever travels inside
  `evidence.referralToken`.
- **No typed-URL inference.** Attribution is based solely on the decoded payload
  the host app supplies. The SDK never observes or reconstructs manually typed
  URLs.
- **Consent-gated.** Emission is gated on `analytics` consent like every other
  event.
