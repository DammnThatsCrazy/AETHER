#!/usr/bin/env python3
"""Prepare blind human review packets and assemble reviewed identity labels.

The HMAC key is read from IDENTITY_CALIBRATION_INTAKE_HMAC_KEY by default and
is never written to the packet, join file, output, or logs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.backend.services.identity.calibration_intake import (  # noqa: E402
    assemble_reviewed_labels,
    prepare_review_intake,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="create a blinded annotation packet")
    prepare.add_argument("review_export", type=Path, help="metadata-only JSONL from authorized identity review evidence")
    prepare.add_argument("output_directory", type=Path)
    prepare.add_argument("--hmac-key-env", default="IDENTITY_CALIBRATION_INTAKE_HMAC_KEY")
    assemble = subparsers.add_parser("assemble", help="join completed human annotations to runtime metadata")
    assemble.add_argument("packet", type=Path)
    assemble.add_argument("private_join", type=Path)
    assemble.add_argument("annotations", type=Path)
    assemble.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            key = os.environ.get(args.hmac_key_env)
            if not key:
                parser.error(f"environment variable {args.hmac_key_env} is required")
            result = prepare_review_intake(args.review_export, args.output_directory, hmac_key=key.encode())
        else:
            result = assemble_reviewed_labels(args.packet, args.private_join, args.annotations, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
