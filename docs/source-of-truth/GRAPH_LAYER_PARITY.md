---
title: Graph Layer Parity Checklist
slug: source-of-truth/graph-layer-parity
section: source-of-truth
visibility: internal
audience: [architect, dev-senior, ai]
status: stable
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/shared/graph/relationship_layers.py
  - packages/shared/graph-contract.ts
  - docs/source-of-truth/GRAPH_CONTRACT.md
canonical_owner: graph@aether
last_synced_commit: fd2288c
---
# Graph Layer Parity Checklist

This document ensures all four relationship layers (H2H, H2A, A2H, A2A) have
complete parity across docs, backend, frontend, tests, and CI gates. Any gap
found here is a blocker for production release.

---

## Layer Parity Matrix

| Layer | Docs | Backend Contract | Frontend TypeScript | Backend Tests | Frontend Tests | CI Gate |
|-------|------|-----------------|--------------------|-----------|--------------|----|
| H2H | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| H2A | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| A2H | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| A2A | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## Backend Parity

### `relationship_layers.py` — all four layers in `RelationshipLayer` enum

```python
class RelationshipLayer(str, Enum):
    H2H = "H2H"
    H2A = "H2A"
    A2H = "A2H"  # Must not be missing
    A2A = "A2A"
```

### `_EDGE_LAYER_MAP` — every registered edge type maps to a layer

All edge types in `EdgeType` must appear in `_EDGE_LAYER_MAP`. Unknown edge
types must not default silently to H2H — they must log a warning and the
unclassified count must be zero in production.

### Graph routes — all four layers in contracts endpoint

`GET /v1/graph/contracts` must return `relationship_layers: ["H2H", "H2A", "A2H", "A2A"]`.

---

## Frontend Parity

### Kyber operator dashboard

All four layer cards must render in the graph health panel:
- H2H card
- H2A card
- A2H card  ← must not be omitted
- A2A card

### Aether tenant dashboard (Profile360)

Layer filter tabs must include all four:
- H2H tab
- H2A tab
- A2H tab  ← must not be omitted
- A2A tab

---

## Documentation Parity

Every doc that mentions relationship layers must list all four. The following
docs are checked by CI:

- `README.md`
- `Backend Architecture/README.md`
- `docs/INTELLIGENCE-GRAPH.md`
- `docs/UNIFIED-ECONOMIC-GRAPH.md`
- `docs/ECONOMIC-OBSERVABILITY.md`
- `docs/KYBER-ECONOMIC-OBSERVABILITY.md`
- `docs/OPERATIONAL-INTELLIGENCE-AUDIT.md`
- `docs/PRODUCTION-READINESS.md`

Forbidden pattern: any doc listing "H2H, H2A, and A2A" without A2H.

---

## CI Gate Requirements

The following checks must pass before merge:

1. `python tests/contracts/test_graph_contract_parity.py` — TypeScript/Python contract parity
2. `python tests/docs/test_graph_layer_docs_parity.py` — no docs omit A2H
3. `python Backend\ Architecture/aether-backend/tests/graph/test_relationship_layer_parity.py` — every edge mapped
4. `make docs-check` — no stale source-linked docs
5. `grep -R "H2H, H2A, and A2A" .` must return zero results

---

## Known Previous Gap (Resolved in v8.9.0)

Prior to v8.9.0, `Backend Architecture/README.md` listed only three layers
(H2H, H2A, A2A) in the Relationship Layers table and description text,
omitting A2H entirely. This was fixed in the v8.9.0 productization pass.

The `operational_intelligence/routes.py` overlay endpoint previously returned
a placeholder summary string ("Overlay scores are placeholder — scoring engines
connect in a future release"). This was replaced with deterministic scoring
from real graph data in v8.9.0.
