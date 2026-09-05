---
title: Brand-system principles
slug: architecture/brand-system/principles
section: architecture
visibility: I
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.12.0"
canonical_owner: frontend@aether
---

# Brand-system principles

## Product hierarchy

**Olympus Labs** is the corporate parent and attribution layer. Use it for
corporate, documentation, marketing, legal, and combined-product contexts; it
is not routine application chrome.

**Aether** is the customer product: a public marketing surface and a protected
tenant application. Its layered mark, warm/stone surfaces, Deep Steel/Sky Blue
accents, and Geist-led typography are the default product language. On public
material it appears as "Aether by Olympus Labs"; inside the tenant application
Olympus Labs branding stays secondary to Aether.

**Kyber** is Olympus Labs' private internal operator application — never
customer-facing, never linked from public marketing. It uses the same corporate
and product lineage with an operator-oriented descriptor; it is not a third
visual identity or a reason to introduce a competing base palette.

The shell taxonomy — which surface each identity leads on, and the brand weight
per shell — is the web-ecosystem source of truth
([`docs/source-of-truth/WEB_ECOSYSTEM_SHELLS.md`](../source-of-truth/WEB_ECOSYSTEM_SHELLS.md)).

Use a manifest lockup rather than re-composing a wordmark:

| Context | Preferred lockup | Reduction rule |
| --- | --- | --- |
| Corporate/docs/marketing header | `OlympusLockup` / Olympus `full` | Olympus `mark` only when attribution remains accessible elsewhere. |
| Standard Aether shell | Aether `full` | `compact` at 72px+ inline width; `mark` only in collapsed/mobile shell. |
| Kyber operator shell | Kyber `full` | `compact` at 84px+; `mark` in collapsed navigation with an accessible Kyber name. |

The exact responsive thresholds are exported by
`packages/brand/src/responsive/lockup.ts`. Do not squeeze a wordmark smaller
than its policy; select the next manifest variant instead.

## Typography, spacing, and surfaces

Geist is the product sans. Geist Mono is for IDs, structured data, code, and
compact operational labels—not a replacement body typeface. The typed scale is
in `packages/brand/src/tokens/typography.ts`.

Keep the established warm/stone CSS surfaces from
`frontend/shared/src/styles/tokens.css`. A card is generally border-led:
`surfaceRecipes` reserves stronger shadows for floating layers, modals, and
tooltips. Use the named spacing, radius, border, focus, elevation, and shadow
tokens rather than selecting a visual value in a feature.

An icon's visual size is not its target size. `ICON_SIZE` provides the drawing
size; `MINIMUM_INTERACTIVE_TARGET` requires 44px pointer targets (32px only for
compact keyboard-oriented controls).

## Iconography and semantic truth

The icon taxonomy is semantic and renderer-independent. It has separate
navigation, action, domain, entity, status, severity, freshness, confidence,
and provenance registries under `packages/brand/src/iconography/`.

Do not use a provider mark, accent color, icon, or animation to blur these
questions together:

| Question | Registry/renderer | Must stay independent from |
| --- | --- | --- |
| What external platform is this? | Provider registry / `ProviderMark` | Health, urgency, action, or entitlement. |
| What entity is this? | Entity taxonomy / `EntityIcon` or `EntityAvatar` | Its provider/source overlay. |
| Is the capability live, gated, stale, partial, or failed? | Status taxonomy / `StatusIcon` and existing capability state UI | Severity. |
| How urgent is it? | Severity taxonomy / `SeverityIcon` | Lifecycle or provider. |
| When was it observed? | Freshness taxonomy / `FreshnessIcon` plus timestamp | Confidence or provenance. |
| How certain is the claim? | Confidence taxonomy / `ConfidenceIndicator` | Source, health, or urgency. |
| Where did it come from? | Provenance taxonomy / `ProvenanceIcon` | Confidence or freshness. |

Preserve current truthful terms such as `credential_required`,
`sandbox_validated`, `partner_live`, `degraded`, and `kill_switch_active`.
Visual migration changes rendering, not operational meaning.

## Provider identity

Every current provider registry entry has a deliberately neutral fallback
rather than an invented or remotely fetched logo. Pair a mark with a text
label in product UI, use the registry's attribution metadata when a provider
identity materially appears, and preserve the server-supplied requested ID.

An unknown provider is not an error and is not an invitation to guess. Resolve
it with `resolveProvider`; render its neutral initials fallback and retain the
incoming ID for diagnostics. Registry presence also does not make a catalog
provider selectable, live, entitled, or compliance-approved.

## Do and don't

| Do | Don't |
| --- | --- |
| Use `AetherLockup`, `KyberLockup`, `OlympusLockup`, or `BrandMark`. | Copy an SVG into a feature, redraw the layers, or recolor a manifest asset. |
| Use `NavigationIcon` with the existing route label/gate. | Replace a route, capability rule, or forbidden-state behavior while changing an icon. |
| Use `ProviderMark` next to text and a separate `StatusIcon`/badge. | Make a provider logo or logo color communicate connection health or severity. |
| Render labels, timestamps, and data attributes in addition to visual cues. | Depend on color, a raw Unicode symbol, or animation as the sole meaning. |
| Use `motionRecipes` and reduced-motion policy. | Add decorative pulse, autoplay layout motion, or motion that conceals loading/error truth. |
| Use a named surface recipe and visible focus state. | Add a local palette, arbitrary glow, or focus-less icon button. |
