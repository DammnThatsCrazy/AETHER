---
title: Olympus Labs + Aether Public Content
slug: public
section: home
visibility: P
audience: [exec, buyer, dev-junior, dev-senior]
status: stable
since_version: "8.12.0"
estimated_read_minutes: 3
toc_depth: 3
canonical_owner: strategy@olympus
---
# Olympus Labs + Aether Public Content
This is the outward-facing narrative and publication package for the Olympus
Labs and Aether websites, public documentation, developer entry points, and
proof surfaces.
The story begins with **connections** and ends with **relationships and the
perspectives they create**. SDKs, connectors, campaigns, communications,
social systems, commerce systems, imports, APIs, and webhooks are means of
connecting evidence. They are not the product's identity by themselves.
## Publication lanes
- [Olympus Labs](/doc/company/manifesto) — company thesis, principles, research direction, and contact path.
- [Aether](/doc/product/manifesto) — product manifesto and connection-to-perspective story.
- [Connections](/doc/product/connections) — the suite of ways Aether receives evidence.
- [How Aether works](/doc/product/how-it-works) — the closed relationship loop.
- [Security and trust](/doc/product/security-and-trust) — evidence, consent, scope, and governance.
- [Developers](/doc/developers) — public developer and integration entry point.
- [Stories and proof](/doc/stories) — evidence policy and case-study structure.
- [Glossary](/doc/glossary/aether) — shared public vocabulary.
## Public site routes
The repository also contains the deployable marketing shell in
`frontend/marketing/`. It builds two static targets from one governed content
system:
- `build:olympus` → `https://www.olympuslabsml.com` — company, research, resources, and contact.
- `build:aether` → `https://aether.olympuslabsml.com` — product, connections, perspectives, trust, pricing, developers, stories, and pilot/proof CTAs.
The product site links to `https://docs.olympuslabsml.com` for the full developer
journey and to `https://app.olympuslabsml.com` for the authenticated tenant app.
The page-filling marketing copy is maintained separately from the shell in
`frontend/marketing/content/`. That package contains the full route copy,
SEO metadata, section text, proof language, CTA library, footer microcopy, and
legal publication boundaries.
## Editorial rule
Every public claim must identify its evidence state and deployment conditions.
The public narrative may be ambitious, but it must not describe a connector,
SDK, campaign, communication channel, or agent capability as universally live
when the current readiness evidence does not support that claim.
