# Aether Development

Full local setup is in [`docs/operations/DEVELOPMENT.md`](docs/operations/DEVELOPMENT.md); quick start is in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Commands

| Command | Purpose |
|---|---|
| `make repo-doctor` | Full consistency check, no mutations |
| `make repo-doctor-fix` | Regenerate generated docs and sync, then validate |
| `make docs-check` | Docs-focused validation |
| `make docs-generate-changed` | Refresh `source_hashes` for reviewed source-linked docs |
| `make verification-disposition BASE=origin/main EXECUTE=1` | Normal PR authority |
| `make ci-check` | Broad repository evidence (trusted-main, nightly, release) |
| `python scripts/bump_version.py --check` | Version alignment |
| `python scripts/validate_contracts.py` | Contract consistency |
| `python scripts/validate_sdk_parity.py` | SDK parity |

See [`AGENTS.md`](AGENTS.md) for when each gate runs and which one is the merge authority.

## Source-of-truth updates

A change to product behavior, contracts, SDKs, connectors, graph projections, 360 surfaces, release state, or deployment must update the matching document under [`docs/reference/source-of-truth/`](docs/reference/source-of-truth/).
