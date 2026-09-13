"""Cross-device continuation plane contracts (C1).

Server-owned handoff records linking desktop and mobile state. A continuation
stores *references + a bounded selection + a revision* — never a whole graph or
raw payload. Live exploration context is re-resolved on read. See
docs/source-of-truth/CROSS_DEVICE_CONTINUITY.md and
reports/mobile-productization/decision-log.md (D3, D4).
"""
