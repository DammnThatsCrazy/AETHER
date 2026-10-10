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

## Web SDK

```bash
npm install @aether/web
```

## Server SDK (Node.js)

```bash
npm install @aether/server
```

## React Native SDK

```bash
npm install @aether/react-native
```

## iOS SDK

Add the Aether iOS SDK via Swift Package Manager:

```swift
dependencies: [
    .package(url: "https://github.com/aether/ios-sdk", from: "0.1.0")
]
```

## Android SDK

Add the Aether Android SDK via Gradle:

```kotlin
implementation("com.aether:android-sdk:0.1.0")
```

## Next Steps

After installing the SDK, proceed to [Send Your First Event](./send-first-event.md).
