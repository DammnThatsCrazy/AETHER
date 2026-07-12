"""Model-governance policy resolution.

Resolves, for a canonical model id, the consent purposes that gate its serving
and the purposes its training data is allowed to be drawn from. The canonical
source is the ML registry's governance metadata
(``ML Models/aether-ml/common/model_registry.ModelEntry``); this module reads it
through a lazy import and falls back to a conservative static mapping when the ML
package is not importable (mirrors ``services/ml_serving/routes._resolve_canonical``).

Fail-closed: an unresolved sensitive model defaults to requiring consent and to
being enforced.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

# Conservative fallback: model category → the consent purpose whose grant a
# subject must hold for that model's inference. Used only when the ML registry
# is not importable in this process.
_CATEGORY_SERVING_PURPOSE: dict[str, str] = {
    "behavioral_analytics": "analytics",
    "identity": "analytics",
    "journey": "analytics",
    "marketing_attribution": "marketing",
    "attribution": "marketing",
    "commerce": "commerce",
    "web3_security": "web3",
    "security": "analytics",
}

# Models that always fail closed if the registry is unavailable (sensitive).
_FALLBACK_FAIL_CLOSED = frozenset({"bytecode_risk", "trust_score", "identity_resolution"})


def _entry(model_id: str):
    try:
        from common.model_registry import get_model
        return get_model(model_id)
    except Exception:  # pragma: no cover - registry ships with the repo in prod
        return None


@lru_cache(maxsize=256)
def serving_required_purposes(model_id: str) -> tuple[str, ...]:
    """Consent purpose(s) a subject must have granted for this model's inference."""
    entry = _entry(model_id)
    if entry is not None:
        # Governance metadata may scope serving to explicit purposes; otherwise
        # fall back to the model's category mapping.
        allowed = getattr(entry, "allowed_training_purposes", None) or []
        category = getattr(entry, "category", "") or ""
        mapped = _CATEGORY_SERVING_PURPOSE.get(category)
        # Prefer an explicit governance purpose scope when present.
        if allowed:
            return tuple(dict.fromkeys(allowed))
        if mapped:
            return (mapped,)
        return ()
    mapped = _CATEGORY_SERVING_PURPOSE.get(model_id, None)
    return (mapped,) if mapped else ()


@lru_cache(maxsize=256)
def allowed_training_purposes(model_id: str) -> tuple[str, ...]:
    """Purposes this model's training data may legitimately be drawn from.

    Empty tuple means "unspecified" — the training gate then falls back to the
    consent-registry-wide ``allowModelTraining`` rule per record.
    """
    entry = _entry(model_id)
    if entry is not None:
        return tuple(getattr(entry, "allowed_training_purposes", None) or [])
    return ()


@lru_cache(maxsize=256)
def is_fail_closed(model_id: str) -> bool:
    """Whether inference for this model must be enforced (deny on missing consent)."""
    entry = _entry(model_id)
    if entry is not None:
        return bool(getattr(entry, "fail_closed_required", False))
    return model_id in _FALLBACK_FAIL_CLOSED


def inference_enforcement(model_id: str, *, override: Optional[bool] = None) -> bool:
    """Resolve whether the inference gate blocks (vs. records evidence only).

    Precedence:
      1. explicit ``override`` argument (tests / callers),
      2. ``ML_INFERENCE_POLICY_ENFORCE=true`` process env (operator switch),
      3. the model's registry ``fail_closed_required`` flag.

    Default is evidence-only so enabling the gate never breaks live inference
    before consent plumbing is wired end-to-end; sensitive models still fail
    closed via (3).
    """
    if override is not None:
        return override
    if os.getenv("ML_INFERENCE_POLICY_ENFORCE", "false").lower() in ("true", "1"):
        return True
    return is_fail_closed(model_id)
