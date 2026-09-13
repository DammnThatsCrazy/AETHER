---
title: Capability Manifest
slug: source-of-truth/capability_manifest
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Capability Manifest (`/v1/config`)

Every SDK calls `GET {endpoint}/v1/config?apiKey=...` once at init. The
response is a **capability manifest** defined in
`packages/shared/capabilities.ts`:

```ts
interface CapabilityManifest {
  schemaVersion: string;
  activeFamilies: EventFamily[];           // which event families are accepted
  supportedPurposes: ConsentPurpose[];     // which consent purposes backend knows
  activeRails: Rail[];                     // payment rails the commerce plane accepts
  supportedVMs: VMType[];                  // wallet VM families turned on
  layers: {
    agent: boolean;     // IG_AGENT_LAYER (L2)
    commerce: boolean;  // IG_COMMERCE_LAYER (L3a)
    x402: boolean;      // IG_X402_LAYER (L3b)
    onchain: boolean;   // IG_ONCHAIN_LAYER (L0)
    trust_scoring?: boolean;
  };
  featureFlags?: { key: string; enabled: boolean; value?: unknown }[];
}
```

## Intended use

- SDKs can short-circuit emitters for disabled layers (optional optimization).
- Host app can query the manifest to know which UI surfaces to render
  (e.g., only show x402 approval prompts when `layers.x402` is true).
- Backend can gate new event families behind the manifest without bumping
  the SDK.

## Runtime behavior today

The web SDK fetches `/v1/config` in `fetchConfig()` and uses it to load
funnel definitions + feature flags. The layer/rail/VM fields are not yet
read by the client — they are **documented as contract** so backend teams
can start populating them. SDK-side gating will be added as Tier B work.

## Source of truth

- `packages/shared/capabilities.ts` — TypeScript contract
- `Backend Architecture/aether-backend/config/settings.py` — backend
  feature flags that feed `layers.*`
- Backend handler for `GET /v1/config` owns the response shape.
