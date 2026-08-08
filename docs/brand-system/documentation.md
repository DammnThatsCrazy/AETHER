---
title: Documentation guidance
status: active
canonical_owner: frontend@aether
---

# Documentation guidance

Docs are a consumer of the brand system, not a separate visual system or asset
store. Prefer source-path links and small runnable API examples over copied
tokens, SVGs, or provider artwork.

- State the hierarchy accurately: Olympus Labs parent, Aether customer product,
  Kyber operator product.
- Use `@olympus/brand` for framework-free metadata examples and `@aether/ui`
  for React examples. Link to the public API barrel, not a feature-local clone.
- Describe unknown providers as neutral fallbacks; never imply a registry entry
  establishes entitlement, integration, operational health, or legal approval.
- Keep generated evidence such as `docs/_generated/providers.json` generated.
  Do not hand-edit it to satisfy a visual need.
- Add a docs UI lockup/theme only through a separately owned `frontend/docs`
  migration that declares the existing shared dependency and imports shared
  styling once. Do not copy the product palette into inline styles.
- Before publishing documentation UI changes, verify typecheck, keyboard focus,
  contrast, narrow-sidebars, and content/asset links.
