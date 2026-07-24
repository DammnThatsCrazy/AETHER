---
title: Native UI Interaction Tracking
slug: sdk/interaction-tracking
section: sdks
visibility: I
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.12.0"
canonical_owner: platform@aether
estimated_read_minutes: 7
---

# Native UI Interaction Tracking

The mobile SDKs can optionally observe **explicit, developer-instrumented UI
controls** and emit the canonical `ui_interaction_observed` event. The SDK
**observes; the backend classifies**. This capability is **off by default** and
is **metadata-only**.

## What is guaranteed (no-surveillance)

- **No Accessibility Services** (Android) and **no view-tree scraping**. The SDK
  never enumerates the screen or hooks the platform accessibility pipeline.
- **No keyboard interception** and **no text-field content capture**. Rendered
  control text, labels, and field values are never read.
- **No third-party surveillance.** The SDK observes only the controls the host
  app explicitly instruments.
- **Metadata-only by default.** Events carry a stable control identifier, a
  control type, an action, the current screen, and an optional navigation id.
  Control text is only ever included if `captureControlText` is explicitly
  enabled; coordinates only if `captureCoordinates` is explicitly enabled.
- **Consent-gated.** Every `ui_interaction_observed` event flows through the
  same consent-gated queue as all other events (`analytics` purpose). Nothing
  leaves the device without consent.
- **Not acquisition proof.** Interaction events are kept entirely separate from
  `AcquisitionEvidence` and are never used to attribute a traffic source.

## Configuration

All privacy-affecting switches default to the safest value.

| Option | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Master switch. When false, every observation is a no-op. |
| `captureControlText` | `false` | Include rendered control text/label. Keep off. |
| `captureCoordinates` | `false` | Include touch coordinates. Keep off. |
| `requireStableIdentifiers` | `true` | Drop interactions that lack a stable id. |
| `allowlistedScreens` | `[]` | When non-empty, only these screens may emit. |
| `denylistedScreens` | `[]` | These screens never emit (takes precedence). |

## Event shape

`ui_interaction_observed` carries a payload aligned across Android, iOS, and
React Native:

| Key | Notes |
|---|---|
| `controlId` | Stable, developer-assigned identity (never rendered text). |
| `controlType` | Semantic kind (e.g. `button`, `composable`, `swiftui`, `pressable`). |
| `action` | Interaction action (e.g. `tap`, `press`). |
| `screen` | Current screen, when set via the navigation observer. |
| `navigationId` | Per-destination id correlating interactions to a screen. |

Session id and consent-state travel on the standard event envelope.

## Android

```kotlin
import com.aether.sdk.AetherInteraction

// Opt in (typically once, after Aether.initialize).
AetherInteraction.configure(
    AetherInteraction.Config(
        enabled = true,
        allowlistedScreens = setOf("checkout", "cart"),
    ),
)

// Explicit tracked-view helper (emits; does not alter behavior).
AetherInteraction.trackInteraction(button, controlId = "checkout.confirm")

// Controlled click instrumentation that PRESERVES the tenant handler.
AetherInteraction.instrumentClick(
    view = button,
    controlId = "checkout.confirm",
    delegate = { /* your existing onClick */ },
)

// Assign a stable id to a view that lacks a meaningful android:id.
AetherInteraction.setAetherId(button, "checkout.confirm")
```

Jetpack Compose (Compose is an optional `compileOnly` dependency):

```kotlin
import com.aether.sdk.aetherTrack

Button(onClick = onCheckout, modifier = Modifier.aetherTrack("checkout.confirm")) {
    Text("Confirm")
}
```

`Modifier.aetherTrack` observes the tap **without consuming** it, so the
tenant's own `onClick` still fires.

AndroidX Navigation (optional `compileOnly` dependency):

```kotlin
import com.aether.sdk.AetherInteractionNavigation

navController.addOnDestinationChangedListener(AetherInteractionNavigation.listener())
```

Stable resource ids (via `resources.getResourceEntryName`) or explicit Aether
ids are used — never rendered text.

## iOS

```swift
import AetherSDK

AetherInteraction.shared.configure(
    AetherInteraction.Config(enabled: true, allowlistedScreens: ["checkout"])
)

// Explicit UIKit helper (uses accessibilityIdentifier when no id is passed).
AetherInteraction.shared.trackInteraction(confirmButton, id: "checkout.confirm")

// Additive UIControl observation — never replaces the tenant's own targets.
AetherInteraction.shared.instrument(confirmButton, id: "checkout.confirm")
```

SwiftUI:

```swift
Button("Confirm", action: onCheckout)
    .aetherTrack(id: "checkout.confirm")

// Navigation-stack destination context.
CheckoutView().aetherScreen("checkout")
```

`.aetherTrack(id:)` attaches a **simultaneous** gesture, so the tenant's own
tap handling is unaffected. Accessibility identifiers or explicit Aether ids are
used — never text-field content.

## React Native

`AetherPressable` and `useTrackedPress` emit the same `ui_interaction_observed`
payload shape as native:

```tsx
import { AetherPressable } from '@aether/react-native';

<AetherPressable aetherId="checkout.confirm" onPress={onCheckout}>
  <Text>Confirm</Text>
</AetherPressable>
```

```ts
import { useTrackedPress } from '@aether/react-native';

const onPress = useTrackedPress('checkout.confirm', handleConfirm);
```

The stable `aetherId` is the only identity captured — the rendered text is never
read.
