---
title: Install the SDK
slug: install-the-sdk
section: developer
visibility: P
audience: [dev-junior, dev-senior]
status: experimental
since_version: 0.1.0
---

# Install the SDK

The SDKs are in alpha (`0.1.0-alpha.0`). Pin the exact version until 1.0, since
pre-1.0 minor releases may contain breaking changes.

Use the key Aether issues for each SDK during onboarding. Browser and app SDKs
(Web, React, React Native, iOS, Android) get a site-bound **publishable key**
(`pk_…`) together with a **site id** (`site_…`). Configure both: the SDK sends
the site id as `X-Aether-Site`, and the backend accepts the key only for that
site. A web site is bound to the origins it is served from; an app is bound to
its bundle ID or package name, because native apps send no `Origin`. The key is
readable from page source or an app binary, so it can only send events for its
site. The Server SDK uses a **secret key**; keep it in an environment variable
and never ship it in a browser or app.

## Web SDK (browser, React)

```bash
npm install @olympuslabs/aether-web@0.1.0-alpha.0
```

React apps use the same package: `import { AetherProvider } from '@olympuslabs/aether-web/react'`.

## Server SDK (Node.js)

```bash
npm install @olympuslabs/aether-server@0.1.0-alpha.0
```

## React Native SDK

```bash
npm install @olympuslabs/aether-react-native@0.1.0-alpha.0
cd ios && pod install
```

The package includes its native iOS and Android modules. Autolinking pulls in
`AetherSDK` (CocoaPods) and `com.olympuslabsml:aether-android` (Maven Central),
so no extra native dependency lines are needed.

## iOS SDK

Swift Package Manager (Xcode: **File → Add Package Dependencies…**, or in `Package.swift`):

```swift
dependencies: [
    .package(url: "https://github.com/DammnThatsCrazy/aether-ios.git", exact: "0.1.0-alpha.0")
]
// target dependency:
.product(name: "AetherSDK", package: "aether-ios")
```

CocoaPods:

```ruby
pod 'AetherSDK', '0.1.0-alpha.0'
```

## Android SDK

The SDK is on Maven Central, which Android projects include by default:

```kotlin
dependencies {
    implementation("com.olympuslabsml:aether-android:0.1.0-alpha.0")
}
```

The Kotlin package is `com.aether.sdk` (for example `import com.aether.sdk.Aether`).

## Next Steps

After installing the SDK, proceed to [Send Your First Event](./send-first-event.md).
