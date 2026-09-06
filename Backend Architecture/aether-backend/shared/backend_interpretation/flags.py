"""WS-D flag reads.

Function-local ``get_settings()`` reads: this cross-cutting package is imported
by Silver projectors, graph promotion and ingestion workers, and a module-level
settings import from here would drag the full settings graph into every one of
those surfaces. The seven WS-D flags all live on
``Settings.backend_interpretation`` (a frozen
:class:`config.settings.BackendInterpretationConfig`); the block is described
in ``docs/architecture/BACKEND_INTERPRETATION_WS_D.md``.

The mapping (settings attr name -> env var -> blueprint item):

* ``relationship_fact_enabled``    ``AETHER_BACKEND_RELATIONSHIP_FACT_ENABLED``     item 1 (typed RelationshipFact + evidence_refs)
* ``episode_engine_enabled``       ``AETHER_BACKEND_EPISODE_ENGINE_ENABLED``        item 2 (episode engine)
* ``outcome_truth_store_enabled``  ``AETHER_OUTCOME_TRUTH_STORE_ENABLED``           item 3 (durable outcome truth store)
* ``evidence_dedupe_enabled``      ``AETHER_EVIDENCE_DEDUPE_ENABLED``               item 4 (Section-25 dedupe)
* ``silver_temporal_envelope_enabled`` ``AETHER_SILVER_TEMPORAL_ENVELOPE_ENABLED``  item 5 (temporal envelope reaches Silver)
* ``correlation_first_class_enabled``  ``AETHER_CORRELATION_FIRST_CLASS_ENABLED``   item 6 (correlation first-class)
* ``silver_exact_money_enabled``   ``AETHER_SILVER_EXACT_MONEY_ENABLED``            item 7 (Silver exact-decimal money)

Derived-truth governance (item 8) intentionally rides the pre-existing
``AETHER_MUTATION_GATEWAY_MODE`` (off|shadow|enforce) rather than a new flag.
"""

from __future__ import annotations

from typing import Callable

# Attribute name on Settings.backend_interpretation for each WS-D item.
_FLAG_ATTRS: tuple[str, ...] = (
    "relationship_fact_enabled",
    "episode_engine_enabled",
    "outcome_truth_store_enabled",
    "evidence_dedupe_enabled",
    "silver_temporal_envelope_enabled",
    "correlation_first_class_enabled",
    "silver_exact_money_enabled",
)


def backend_interpretation_enabled(attr: str) -> bool:
    """Read one WS-D flag by ``Settings.backend_interpretation`` attribute name.

    Unknown attribute names resolve to ``False`` (fail-safe): a typo can never
    enable a behavior-changing mechanism.
    """
    if attr not in _FLAG_ATTRS:
        return False
    try:
        from config.settings import get_settings

        return bool(getattr(get_settings().backend_interpretation, attr, False))
    except Exception:  # noqa: BLE001 - import-defensive: never crash a caller
        return False


def relationship_fact_enabled() -> bool:
    return backend_interpretation_enabled("relationship_fact_enabled")


def episode_engine_enabled() -> bool:
    return backend_interpretation_enabled("episode_engine_enabled")


def outcome_truth_store_enabled() -> bool:
    return backend_interpretation_enabled("outcome_truth_store_enabled")


def evidence_dedupe_enabled() -> bool:
    return backend_interpretation_enabled("evidence_dedupe_enabled")


def silver_temporal_envelope_enabled() -> bool:
    return backend_interpretation_enabled("silver_temporal_envelope_enabled")


def correlation_first_class_enabled() -> bool:
    return backend_interpretation_enabled("correlation_first_class_enabled")


def silver_exact_money_enabled() -> bool:
    return backend_interpretation_enabled("silver_exact_money_enabled")


def mutation_gateway_mode() -> str:
    """Return the effective derived-truth mutation-gateway mode (off default).

    Reuses ``AETHER_MUTATION_GATEWAY_MODE`` (off|shadow|enforce) so WS-D item 8
    rides the existing governance knob instead of introducing a parallel one.
    """
    try:
        from config.settings import get_settings

        return str(getattr(get_settings(), "mutation_gateway_mode", "off") or "off")
    except Exception:  # noqa: BLE001
        return "off"


__all__ = [
    "backend_interpretation_enabled",
    "relationship_fact_enabled",
    "episode_engine_enabled",
    "outcome_truth_store_enabled",
    "evidence_dedupe_enabled",
    "silver_temporal_envelope_enabled",
    "correlation_first_class_enabled",
    "silver_exact_money_enabled",
    "mutation_gateway_mode",
]
