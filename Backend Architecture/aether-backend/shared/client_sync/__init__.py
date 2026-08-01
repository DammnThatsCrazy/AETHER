"""Client-sync feed contracts (C1).

A durable append-only change log projected onto a gapless per-scope cursor.
`GET /v1/client-sync?cursor=` emits the ten change types below carrying ids +
revisions only — never the resource body, so the graph is never replicated; the
client re-fetches through its normal scoped endpoints. See
docs/source-of-truth/CROSS_DEVICE_CONTINUITY.md and decision-log D5.
"""
