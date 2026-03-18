"""
Aether Security — Extraction Defense Admin CLI

Command-line tool for operational management of the model extraction
defense system. Provides:

  - Watermark verification against suspect models
  - Risk score inspection per client
  - Canary trigger history
  - Defense metrics snapshot
  - Canary re-generation

Usage:
    python -m security.model_extraction_defense.admin_cli verify-watermark \\
        --secret-key <key> --suspect-outputs outputs.json

    python -m security.model_extraction_defense.admin_cli metrics

    python -m security.model_extraction_defense.admin_cli risk-scores

    python -m security.model_extraction_defense.admin_cli canary-triggers

    python -m security.model_extraction_defense.admin_cli generate-canaries \\
        --seed <seed> --n-features 20 --output canaries.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

import numpy as np


def cmd_verify_watermark(args: argparse.Namespace) -> None:
    """Verify watermark presence in suspect model outputs."""
    from .watermark import ModelWatermark
    from .config import WatermarkConfig

    config = WatermarkConfig(
        secret_key=args.secret_key,
        bias_strength=args.bias_strength,
    )
    wm = ModelWatermark(config)

    # Load suspect outputs + fingerprints from JSON
    with open(args.suspect_outputs) as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("ERROR: Expected a JSON array of objects with 'output' and 'features'")
        sys.exit(1)

    outputs = []
    fingerprints = []
    for entry in data:
        output = np.array(entry["output"], dtype=float)
        fp = ModelWatermark.fingerprint_features(entry["features"])
        outputs.append(output)
        fingerprints.append(fp)

    score = wm.verify(outputs, fingerprints)
    is_wm = wm.is_watermarked(outputs, fingerprints)

    print(f"Samples analyzed:       {len(outputs)}")
    print(f"Watermark confidence:   {score:.4f}")
    print(f"Verification threshold: {config.verification_threshold}")
    print(f"Watermark detected:     {'YES' if is_wm else 'NO'}")

    if is_wm:
        print("\nCONCLUSION: The suspect model outputs contain the Aether watermark.")
        print("This indicates the model was likely extracted from Aether predictions.")
    else:
        print("\nCONCLUSION: No watermark detected at the current threshold.")
        print("The model may not have been extracted, or the attacker applied")
        print("post-processing that degraded the watermark signal.")


def cmd_generate_canaries(args: argparse.Namespace) -> None:
    """Generate canary inputs and save to JSON."""
    from .canary_detector import CanaryInputDetector
    from .config import CanaryConfig

    config = CanaryConfig(
        secret_seed=args.seed,
        num_canaries=args.num_canaries,
    )
    detector = CanaryInputDetector(config)
    detector.generate_canaries(args.n_features)

    canaries = []
    for idx, vec in enumerate(detector._canaries):
        canaries.append({
            "canary_id": idx,
            "vector": vec.tolist(),
            "strategy": ["sparse", "extreme", "patterned"][idx % 3],
        })

    output_path = args.output or "canaries.json"
    with open(output_path, "w") as f:
        json.dump(canaries, f, indent=2)

    print(f"Generated {len(canaries)} canary inputs ({args.n_features}D)")
    print(f"Saved to: {output_path}")


def cmd_metrics(args: argparse.Namespace) -> None:
    """Print defense metrics snapshot (requires running defense layer)."""
    print("Metrics snapshot requires a running ExtractionDefenseLayer instance.")
    print("Use the following code in your application:")
    print()
    print("    from security.model_extraction_defense import ExtractionDefenseLayer")
    print("    defense = ExtractionDefenseLayer.from_env()")
    print("    print(json.dumps(defense.get_metrics_snapshot(), indent=2))")
    print()
    print("Or add a /v1/defense/metrics endpoint to your API.")


def cmd_risk_scores(args: argparse.Namespace) -> None:
    """Print current risk scores (requires running defense layer)."""
    print("Risk scores require a running ExtractionDefenseLayer instance.")
    print("Use the following code in your application:")
    print()
    print("    scores = defense.get_all_risk_scores()")
    print("    for key, score in sorted(scores.items(), key=lambda x: -x[1]):")
    print("        print(f'{key[:12]:15s} {score:.4f}')")


def cmd_canary_triggers(args: argparse.Namespace) -> None:
    """Print canary trigger history (requires running defense layer)."""
    print("Canary triggers require a running ExtractionDefenseLayer instance.")
    print("Use the following code in your application:")
    print()
    print("    triggers = defense.get_canary_triggers()")
    print("    for t in triggers:")
    print("        print(f'{t.timestamp} key={t.api_key} id={t.canary_id}')")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="extraction-defense",
        description="Aether Model Extraction Defense — Admin CLI",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # verify-watermark
    p_verify = sub.add_parser(
        "verify-watermark",
        help="Verify watermark in suspect model outputs",
    )
    p_verify.add_argument(
        "--secret-key", required=True,
        help="Watermark secret key (must match production value)",
    )
    p_verify.add_argument(
        "--suspect-outputs", required=True,
        help="Path to JSON file with suspect outputs (array of {output, features})",
    )
    p_verify.add_argument(
        "--bias-strength", type=float, default=0.015,
        help="Watermark bias strength (default: 0.015)",
    )

    # generate-canaries
    p_canary = sub.add_parser(
        "generate-canaries",
        help="Generate canary inputs and save to JSON",
    )
    p_canary.add_argument(
        "--seed", required=True,
        help="Secret seed for canary generation",
    )
    p_canary.add_argument(
        "--n-features", type=int, required=True,
        help="Number of features in the input space",
    )
    p_canary.add_argument(
        "--num-canaries", type=int, default=50,
        help="Number of canary inputs to generate (default: 50)",
    )
    p_canary.add_argument(
        "--output", default=None,
        help="Output JSON path (default: canaries.json)",
    )

    # metrics / risk-scores / canary-triggers
    sub.add_parser("metrics", help="Print defense metrics snapshot")
    sub.add_parser("risk-scores", help="Print current client risk scores")
    sub.add_parser("canary-triggers", help="Print canary trigger history")

    args = parser.parse_args()

    commands = {
        "verify-watermark": cmd_verify_watermark,
        "generate-canaries": cmd_generate_canaries,
        "metrics": cmd_metrics,
        "risk-scores": cmd_risk_scores,
        "canary-triggers": cmd_canary_triggers,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
