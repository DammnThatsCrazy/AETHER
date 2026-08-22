#!/usr/bin/env python3
"""Fail-closed bidirectional reward-rail matrix validator.

Asserts the reward rail surfaces cannot drift:

1. Every rail in ``rails._RAIL_ADAPTERS`` is classified in
   ``rail_matrix.RAIL_MATRIX`` and vice versa (bidirectional).
2. Every deliverable tier (production/sandbox/explicit_beta) whose
   delivery_mode routes through the outbox has a registered sender in
   ``senders.RAIL_SENDERS``; every registered sender maps to a real rail.
3. No ``intentionally_unsupported`` rail declares a sender (it must be
   unconfigurable and undeliverable).
4. The generated ``docs/_generated/reward-rail-matrix.json`` matches the
   source (drift → regenerate).
5. No beta/unsupported rail is classified ``production``.

Exit 0 on agreement; 1 with precise diffs otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
MATRIX_JSON = ROOT / "docs" / "_generated" / "reward-rail-matrix.json"

ERRORS: list[str] = []


def err(m: str) -> None:
    ERRORS.append(m)


def main() -> int:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from services.rewards.rail_matrix import (
        CONFIGURABLE_TIERS,
        RAIL_MATRIX,
        build_rail_matrix,
    )
    from services.rewards.rails import _RAIL_ADAPTERS
    from services.rewards.senders import RAIL_SENDERS

    adapters = set(_RAIL_ADAPTERS)
    matrix = set(RAIL_MATRIX)
    senders = set(RAIL_SENDERS)

    # 1. adapters ↔ matrix
    for r in adapters - matrix:
        err(f"rail {r!r} has an adapter but no rail_matrix classification")
    for r in matrix - adapters:
        err(f"rail {r!r} is classified but has no adapter in _RAIL_ADAPTERS")

    # 2/3. senders ↔ deliverable tiers
    outbox_modes = {"sync_api", "internal_ledger"}
    for name, c in RAIL_MATRIX.items():
        needs_sender = c.tier in CONFIGURABLE_TIERS and c.delivery_mode in outbox_modes
        if needs_sender and name not in senders:
            err(f"rail {name!r} ({c.tier}/{c.delivery_mode}) has no registered outbox sender")
        if c.tier == "intentionally_unsupported" and name in senders:
            err(f"intentionally_unsupported rail {name!r} must NOT declare a sender")
    for s in senders - matrix:
        err(f"sender {s!r} maps to no classified rail")

    # 5. no beta/unsupported classified production
    for name, c in RAIL_MATRIX.items():
        if c.tier == "production" and name in ("loyalty_points", "coupon"):
            err(f"rail {name!r} must not be classified production")

    # 4. generated matrix matches source
    source = build_rail_matrix()
    if not MATRIX_JSON.exists():
        err(f"{MATRIX_JSON.relative_to(ROOT)} missing — run make gen-reward-rail-matrix")
    else:
        generated = json.loads(MATRIX_JSON.read_text(encoding="utf-8"))
        if generated.get("rails") != source["rails"]:
            err("generated reward-rail-matrix.json is stale — regenerate")

    if ERRORS:
        print("reward rail matrix validation FAILED:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print(
        f"reward rail matrix: OK — {len(matrix)} rails classified, "
        f"{len(senders)} outbox senders, bidirectional agreement holds"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
