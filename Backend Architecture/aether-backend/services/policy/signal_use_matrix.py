"""Runtime reader for the canonical signal-use matrix.

`packages/shared/contracts/signal-use-matrix.json` maps each signal to its exact
required consent purpose(s) and allowed uses. Until now it was a build-time
contract only (validated by scripts/validate_signal_use_matrix.py); the consent
PolicyDecision engine is its first runtime consumer.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# services/policy/ -> aether-backend -> "Backend Architecture" -> <repo root>
_MATRIX_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages" / "shared" / "contracts" / "signal-use-matrix.json"
)


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    try:
        data = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))
        return {s["signal_type"]: s for s in data.get("signals", [])}
    except Exception:  # pragma: no cover - contract ships with the repo
        return {}


def known_signal(signal_type: str) -> bool:
    return signal_type in _index()


def required_purposes(signal_type: str) -> list[str]:
    return list(_index().get(signal_type, {}).get("required_purposes", []))


def explicit_opt_in_required(signal_type: str) -> bool:
    return bool(_index().get(signal_type, {}).get("explicit_opt_in_required", False))


def allows(signal_type: str, flag: str) -> bool:
    """Whether the signal permits a use flag, e.g. allow_identity_linking."""
    return bool(_index().get(signal_type, {}).get(flag, False))
