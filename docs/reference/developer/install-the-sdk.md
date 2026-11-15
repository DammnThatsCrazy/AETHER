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

Use the key Aether issues for each SDK during onboarding. Browser SDKs (Web,
React) get a site-bound **publishable key** (`pk_…`), which is safe to ship in
page code. The Server SDK uses a **secret key**; keep it in an environment
variable and never send it to a browser or app.

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
