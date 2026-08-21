# @olympus/brand

The source of truth for what the Olympus Labs, Aether, and Kyber brand system
**is**. It is intentionally a small TypeScript metadata package, not a React
component library and not a second UI kit.

`@aether/ui` is the rendering layer. It should consume these manifests,
semantic icon descriptors, provider metadata, and tokens to render accessible
SVG/React primitives in Aether, Kyber, documentation, and demo surfaces.

## Contract

- `identity` contains references to existing official SVG assets. It does not
  copy, redraw, recolor, or otherwise manufacture logo geometry.
- `providers` contains canonical provider IDs, aliases, categories, attribution
  guidance, and conservative fallbacks. It intentionally ships **no**
  third-party logo geometry or remote image URLs. Add a third-party mark only
  after it is legally reviewed and committed as a local asset.
- `iconography` is a renderer-independent semantic mapping. The string values
  are approved icon names, not raw Unicode/ASCII glyphs or SVG paths.
- `tokens`, `motion`, `surfaces`, and `responsive` normalize the established
  warm/stone Aether language, Geist typography, and current reduced-motion
  behavior. They do not introduce a new palette or a feature-local theme.

## Typical use

```ts
import {
  ICON_SIZE,
  lockupVariantFor,
  navigationDestinations,
  resolveEntityIdentity,
  resolveProvider,
  statusIcons,
} from '@olympus/brand';

const provider = resolveProvider('generic_webhook');
// known true; provider.identity is the neutral Webhook presentation.

const aetherShellLockup = lockupVariantFor('aether', 96);
const graphNode = resolveEntityIdentity('wallet');
const aetherNav = navigationDestinations['aether-graph'];
const status = statusIcons.credential_required;
const iconPixels = ICON_SIZE[aetherNav.icon === 'network' ? 'md' : 'sm'];
```

## Rules for consumers

1. Resolve a server-provided provider ID with `resolveProvider`; never derive a
   brand color or fetch a remote logo from the ID.
2. Provider identity explains the external platform. Render status, severity,
   confidence, freshness, provenance, and remediation with their separate
   registries and visible text equivalents.
3. Use an icon descriptor as decorative only when adjacent text already names
   it. An icon-only interactive control needs an accessible name and must meet
   the interactive target rules.
4. Use `motionDuration` and `REDUCED_MOTION` with every new transition. Do not
   use motion recipes to conceal loading/error truth.
5. For a new provider/entity/navigation destination, update the appropriate
   registry and its unit test before adding a renderer or route consumer.

## Local verification

```sh
npm run typecheck --workspace=@olympus/brand
npm run test --workspace=@olympus/brand
```

The package has no runtime dependencies and no React import.
