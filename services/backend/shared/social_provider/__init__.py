"""UPR Social provider capability vocabulary domain.

Owns the generated Python twin of the M1 social-provider capability vocabulary:
``generated_social_provider_capability_vocabulary`` (canonical UPR social
provider capability surface — the capability grammar ``family.product.capability``,
the capabilities / acquisition classes / lifecycle states /
empty-success-forbidden states lists, the example identities, and the prose
rules). It is derived from
``packages/shared/contracts/social-provider-capability-vocabulary.json`` via
``scripts/generate_platform_contracts.py``; its TS twin lives in
``packages/shared/social-provider-capability-vocabulary.ts``.

Consumed at registry-register time by the social-scoped honesty gate
``services.provider_runtime.social_capability.social_capability_violations``
(only for plugins whose ``ProviderIdentity.product == "social"``), which turns
this vocabulary into a runtime-enforced canonical surface.
"""
