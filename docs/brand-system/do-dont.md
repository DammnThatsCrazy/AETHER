---
title: Do and don't
slug: architecture/brand-system/do-dont
section: architecture
visibility: I
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Do and don't

| Do | Don't |
| --- | --- |
| Render `AetherLockup`, `KyberLockup`, or `OlympusLockup`. | Copy, redraw, recolor, or locally own brand SVG geometry. |
| Resolve a server provider ID, then use the provider renderer. | Fetch a provider logo, guess an unknown logo, or create a local color table. |
| Keep status and severity text beside their semantic indicators. | Use a provider mark, color, or animation as a state/severity cue. |
| Use `NavigationIcon` while retaining the route's existing gate. | Alter capability, permission, auth, or direct-route behavior in an icon migration. |
| Use entity taxonomy for base node identity and a provider separately as source. | Replace a person/wallet/org identity with its provider logo. |
| Apply named surfaces, focus, sizes, responsive and motion rules. | Add an arbitrary palette, radius, glow, shadow, breakpoint, or easing scale. |
| Keep visible labels/accessible names and non-color state cues. | Rely on raw Unicode/ASCII symbols, color alone, or motion alone. |
| Update the registry/test first and then the consumer. | Add a feature-local duplicate because a canonical entry is missing. |
