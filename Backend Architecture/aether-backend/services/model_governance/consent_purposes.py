"""Runtime reader for the model-training semantics of the consent registry.

`packages/shared/contracts/consent-registry.json` is the single source of truth
for the 11 canonical consent purposes. Each purpose carries model-governance
flags this module surfaces to the training/inference gates:

  - ``allowModelTraining``      — may data collected under this purpose ever feed
                                  model training at all?
  - ``modelTrainingPermission`` — when present (e.g. ``separate_opt_in_required``)
                                  a *separate* training opt-in is required even if
                                  the purpose is otherwise granted.

This mirrors ``services/policy/signal_use_matrix.py``: a thin, cached JSON reader
so the gates never hardcode purpose semantics that could drift from the contract.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# services/model_governance/ -> aether-backend -> "Backend Architecture" -> repo root
_REGISTRY_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages" / "shared" / "contracts" / "consent-registry.json"
)


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        return {p["key"]: p for p in data.get("purposes", [])}
    except Exception:  # pragma: no cover - contract ships with the repo
        return {}


def known_purpose(purpose_key: str) -> bool:
    return purpose_key in _index()


def all_purposes() -> frozenset[str]:
    return frozenset(_index().keys())


def model_training_allowed(purpose_key: str) -> bool:
    """True if data collected under this purpose may feed model training.

    Fails closed: an unknown purpose is never trainable.
    """
    entry = _index().get(purpose_key)
    if entry is None:
        return False
    return bool(entry.get("allowModelTraining", False))


def requires_separate_training_opt_in(purpose_key: str) -> bool:
    """True if this purpose needs a *separate* model-training opt-in.

    Financial/economic/interop purposes carry
    ``modelTrainingPermission == "separate_opt_in_required"`` — being granted the
    purpose is not sufficient to also train on the data.
    """
    entry = _index().get(purpose_key)
    if entry is None:
        return False
    return entry.get("modelTrainingPermission") == "separate_opt_in_required"


def trainable_purposes() -> frozenset[str]:
    """Purposes whose data may feed training without a separate opt-in."""
    return frozenset(
        key for key in _index()
        if model_training_allowed(key) and not requires_separate_training_opt_in(key)
    )
