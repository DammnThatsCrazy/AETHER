"""Product-intelligence shared contracts.

Owns the canonical interaction vocabulary (``generated_vocabulary`` — the
Python twin of ``packages/shared/contracts/interaction-vocabulary.json``) and
the hand-authored :class:`~shared.product.models.InteractionPayload`.
Custom interaction types use ``<namespace>.<name>`` with a registered
namespace; unregistered custom types stay in Bronze and are never promoted to
stable Gold. TS twin: ``packages/shared/interaction-contract.ts``.
"""
