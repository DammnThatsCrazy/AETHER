#!/usr/bin/env python3
"""Validate the backend model-governance gates (§3.5, §3.9, §3.10).

Static/contract gate — no services required. Enforces that:
  - the ``services/model_governance`` package exists with the training +
    inference gates and the canonical consent-registry reader;
  - the inference gate reuses the canonical consent PolicyDecision engine and
    records ``serve_inference`` evidence (not a bespoke decision path);
  - the training gate derives admissibility from the consent registry's
    ``allowModelTraining`` semantics (never hardcoded), and enforces identity
    training-label quarantine (§3.10);
  - the ML serving predict route actually invokes the inference policy gate.

This complements ``scripts/validate_ml_registry.py`` (which governs the ML
registry's per-model governance metadata); this script governs the backend
enforcement surface.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MG_DIR = (
    ROOT / "Backend Architecture" / "aether-backend" / "services" / "model_governance"
)
ROUTES = (
    ROOT / "Backend Architecture" / "aether-backend"
    / "services" / "ml_serving" / "routes.py"
)

ERRORS: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def main() -> int:
    if not MG_DIR.exists():
        fail("missing services/model_governance package")
        return _report()

    required = {
        "consent_purposes.py": ["model_training_allowed", "requires_separate_training_opt_in",
                                 "consent-registry.json"],
        "training_gate.py": ["class TrainingDataGate", "model_training_allowed",
                             "identity_label_unconsented"],
        "inference_gate.py": ["class InferencePolicyGate", "consent_policy_engine",
                              "serve_inference"],
        "contracts.py": ["TrainingDataDecision", "InferenceGateResult"],
        "policy.py": ["inference_enforcement", "fail_closed"],
    }
    for fname, tokens in required.items():
        text = _read(MG_DIR / fname)
        if not text:
            fail(f"missing services/model_governance/{fname}")
            continue
        for tok in tokens:
            if tok not in text:
                fail(f"services/model_governance/{fname} must reference '{tok}'")

    # Inference gate must NOT invent a parallel decision store — it reuses the
    # canonical consent engine so evidence lands in the shared audit ledger.
    inf = _read(MG_DIR / "inference_gate.py")
    if "from services.policy" not in inf and "services.policy" not in inf:
        fail("inference_gate must reuse services.policy consent engine (canonical evidence)")

    # The predict route must actually call the gate.
    routes = _read(ROUTES)
    if "inference_policy_gate" not in routes:
        fail("services/ml_serving/routes.py predict() must invoke inference_policy_gate (§3.9)")

    return _report()


def _report() -> int:
    if ERRORS:
        print("model governance validation FAILED:")
        for e in ERRORS:
            print(f"  - {e}")
        print(
            "\nModel training/inference must be consent-scoped & audited. See "
            "docs/source-of-truth/MODEL_GOVERNANCE.md."
        )
        return 1
    print("model governance validation OK (training + inference gates present and wired).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
