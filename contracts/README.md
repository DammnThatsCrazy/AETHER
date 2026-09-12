---
title: Contract Governance
slug: contracts/readme
section: reference
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Contract Governance

Aether contracts are machine-readable schemas that define the shape of data
exchanged between services, SDKs, and infrastructure. Every persistent write,
ingestion payload, and cross-service message must conform to a registered
contract.

## Contract locations

| Directory | Scope |
|---|---|
| `contracts/delivery/` | Delivery infrastructure schemas (release, staging, deployment, telemetry) |
| `packages/shared/contracts/` | Platform registries and schemas (events, consent, graph, intelligence, identity) |

## Versioning policy

See [VERSION_POLICY.md](./VERSION_POLICY.md).

## Validation

```bash
python scripts/validate_contracts.py    # Cross-consistency check
make repo-doctor                        # Full registry validation
```

## Adding a contract

1. Add the schema (`.schema.json`) or registry (`.json`) to the appropriate directory.
2. Register it in `config/impact_graph.json` under the relevant component and contract entry.
3. Run `python scripts/validate_contracts.py` to verify cross-consistency.
4. Run `make repo-doctor` to verify all registry bindings resolve.
