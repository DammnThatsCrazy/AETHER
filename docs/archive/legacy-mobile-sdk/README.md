# Legacy Mobile SDK (Archived)

> **Status: archived for provenance. Do not build against these files.**

These Swift, Kotlin, and TSX files were once a parallel implementation of
Aether's mobile SDK. They have been superseded by:

- **iOS — canonical:** [`packages/ios/Sources/AetherSDK/`](../../../packages/ios/Sources/AetherSDK/) (Swift Package Manager)
- **Android — canonical:** [`packages/android/src/main/java/com/aether/sdk/`](../../../packages/android/src/main/java/com/aether/sdk/) (Gradle AAR)
- **React Native — canonical:** [`packages/react-native/src/`](../../../packages/react-native/src/)

These are the files that production builds use, that ship to npm / SPM /
Maven, and that the canonical contract in [`packages/shared/`](../../../packages/shared/)
binds against.

## Why this directory exists

These archived files retain useful prior-art commentary on:

- Wallet integration across 7 VMs (EVM, SVM, Bitcoin, MoveVM, NEAR, TVM, Cosmos)
- Feedback / NPS modeling
- Update manager / OTA strategy
- Semantic context collection

They are preserved as a reference, not a dependency. Future SDK work happens
exclusively under `packages/`.

## If you arrived here from a link

The original documentation that lived alongside these files is preserved at
[`_LEGACY-README.md`](./_LEGACY-README.md). For current SDK integration,
see:

- [`docs/SDK-IOS.md`](../../SDK-IOS.md)
- [`docs/SDK-ANDROID.md`](../../SDK-ANDROID.md)
- [`docs/SDK-REACT-NATIVE.md`](../../SDK-REACT-NATIVE.md)

## Removal policy

This directory is **kept**, not deleted, so commit history and external links
remain resolvable. Do not edit files in here; open an issue against the
canonical `packages/` SDK instead.
