---
title: Android Install & Deep-Link Attribution
slug: sdk/android-attribution
section: sdks
visibility: I
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 8
---

# Android Install & Deep-Link Attribution

The Android SDK **observes acquisition evidence and names the entry method;
the backend classifies**. Evidence follows the shared `AcquisitionEvidence`
contract (schema v3, `packages/shared/acquisition-evidence.ts`): UTM fields,
click IDs, an opaque `referralToken` (`aether_ref`), the destination domain,
a one-way destination-path hash, the entry method, and expiry metadata.

Two invariants govern everything on this page:

1. **A deep link's host is the destination, never the referrer.**
   `destinationDomain` records where the user landed. `referrerDomain` is only
   populated when a real external referrer exists (the launching app's
   `Intent.EXTRA_REFERRER`); it is never derived from the link itself.
2. **All transmission is consent-gated.** Every attribution event
   (`deep_link_opened`, `app_install_attributed`) goes through the same
   consent-gated, durable event queue as every other event. In GDPR mode,
   nothing leaves the device without `analytics` consent.

## Automatic App Link handling

With `ModuleConfig.deepLinkAttribution = true` (the default), the SDK registers
`ActivityLifecycleCallbacks` at `Aether.initialize(...)` and observes
`ACTION_VIEW` intents with data URLs when an activity is created:

- `https` links are recorded with entry method **`android_app_link`**.
- Custom-scheme links are recorded as **`manual_sdk_evidence`** (Android has no
  OS verification for custom schemes, so they never claim App Link strength).
- Repeated deliveries of the same intent (activity recreation, configuration
  changes, process restore) are deduplicated by a processed marker on the
  intent plus a bounded recent-hash list persisted in preferences.

Warm starts to `singleTop`/`singleTask` activities do not recreate the
activity, so forward those deliveries explicitly:

```kotlin
override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    Aether.onNewIntent(intent)
}
```

### assetlinks.json requirements

`android_app_link` entries are only OS-verified when the destination domain
publishes a Digital Asset Links statement at
`https://<domain>/.well-known/assetlinks.json` and the app's manifest declares
`android:autoVerify="true"` on the corresponding intent filter:

```json
[
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "com.example.app",
      "sha256_cert_fingerprints": [
        "AA:BB:CC:...:ZZ"
      ]
    }
  }
]
```

Without verification, Android may route the link through a browser or a
chooser dialog instead of the app — the SDK still records whatever evidence
actually reaches the app, and the backend classifier decides what it proves.

## Sanitized URLs

Any landing/deep-link URL the SDK transmits is sanitized first: the fragment,
all click-ID parameters (`gclid`, `fbclid`, `ttclid`, ...), and all Aether
opaque tokens (`aether_ref`, `aether_cid`) are removed. UTM parameters are
retained. Click IDs and tokens still travel — but as structured evidence
fields, never inside URL strings. Destination paths are transmitted only as a
truncated SHA-256 hash (`destinationPathHash`).

## Install attribution (Google Play Install Referrer)

On the first eligible launch the SDK connects to the Play Install Referrer
service (`com.android.installreferrer:installreferrer`), reads the referrer
payload, parses it through the same canonical evidence parser with entry
method **`android_install_referrer`**, captures the click and install-begin
timestamps plus the install app version, persists the result as first-install
evidence, and emits **one** `app_install_attributed` event through the
consent-gated queue.

A state machine persisted in preferences guarantees install attribution never
duplicates:

| State | Meaning |
|---|---|
| `not_requested` | No attempt yet (fresh install). |
| `pending` | Connection in flight (a crash here counts as a retryable attempt). |
| `retrieved` | Payload read; emission in progress. Never re-requested. |
| `consumed` | Payload handed to the queue. Final. |
| `unavailable` | `SERVICE_UNAVAILABLE` persisted after 3 attempts across launches. Final. |
| `unsupported` | `FEATURE_NOT_SUPPORTED` (old Play Store / no Play). Final immediately. |
| `failed_retryable` | Transient failure; retried on a later launch (3 attempts max). |
| `failed_terminal` | Developer/permission error or retries exhausted. Final. |

`resolveDeferredHandoff` (React Native) always resolves `null` on Android:
installs resolve through the Install Referrer automatically, so there is no
clipboard or pasteboard handoff step.

## First-touch vs latest-touch

Evidence is persisted under versioned keys (`aether_acq_first_touch_v1`,
`aether_acq_latest_touch_v1`) with an expiry (default 30 days, configurable via
`ModuleConfig.attributionEvidenceTtlDays`):

- **First touch** is only written when absent or expired — later evidence never
  overwrites it.
- **Latest touch** always reflects the most recent evidence and is attached to
  every outgoing event as `context.acquisitionEvidence` until it expires.
- `Aether.reset()` (logout) clears both touches. The install-referrer state
  machine survives reset because it is install-scoped, not identity-scoped.

## Explicit APIs

```kotlin
Aether.handleDeepLink(url)            // escape hatch; https → android_app_link,
                                      // custom schemes → manual_sdk_evidence
Aether.onNewIntent(intent)            // forward warm-start deliveries
Aether.getFirstTouchAttribution()     // JSONObject? (null when absent/expired)
Aether.getLatestTouchAttribution()    // JSONObject? (null when absent/expired)
```

React Native (Android): `getFirstTouchAttribution()`,
`getLatestTouchAttribution()` (promise of JSON string or null),
`handleURL(url)`, `resolveDeferredHandoff(identifier)` (resolves null on
Android).

## What the SDK does not claim

The SDK records only what it can observe. It makes **no typed-URL claims** —
there is no way to know a user typed a link rather than tapped it — and it
never infers a referrer from the destination. Links opened in a browser
instead of the app (unverified App Links, user chose the browser) produce web
SDK evidence on the landing page, not Android SDK evidence; the two joins are
reconciled server-side.

### Example: organic profile link

A link in a social profile bio carries no click ID and no referrer once it
passes through the app's in-app browser or an install. Declare it:

```
https://shop.example.com/?utm_source=twitter&utm_medium=social&utm_content=profile_bio
```

The SDK captures the UTM declaration as evidence; the backend classifies it as
declared organic social. **Preferred alternative:** issue a verified referral
link (an `aether_ref` token minted by your backend) for the bio instead — the
token is captured as an opaque `referralToken`, verified server-side, and
yields provable attribution instead of a self-declaration.

## Consent gating summary

- No Accessibility Services, no keyboard interception, no raw secrets
  persisted.
- Evidence persistence is local until an event is transmitted; transmission
  requires consent under GDPR mode (`analytics` purpose).
- `app_install_attributed` dropped by consent gating is not retried — the
  state machine still marks the referrer consumed, honoring the user's choice.
