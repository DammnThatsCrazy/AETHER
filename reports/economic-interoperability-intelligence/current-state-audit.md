# Economic + Interoperability Intelligence — Current-State Audit

**Date**: 2026-07-08
**Branch**: `claude/aether-stablecoin-derivatives-interop-tbywo6` (from `main` @ `4b59221`)
**Scope**: Pre-implementation repository truth for the Stablecoin Intelligence, Derivatives
Intelligence, and Interoperability Intelligence expansion.

---

## Baseline validation (clean branch, before any changes)

| Command | Result |
|---|---|
| `python scripts/bump_version.py --check` | PASS (8.11.0 aligned; 3 pre-existing doc warnings: `docs/AGENT-CONTROLLER.md` no versioned heading, `EXTRACTION_DEFENSE_AUDIT.md` listed-but-missing, `Backend Architecture/README.md` no versioned heading) |
| `python -m pytest tests/ -n auto` | **1772 passed, 1 failed, 3 skipped** |
| `npm run build --workspace=packages/shared && npm test` | PASS (all workspaces) |
| `python scripts/production_status.py` | Overall 4.05/5 — pre-production; deployment/cloud readiness 3/5, scale readiness 3/5 |

**Pre-existing test failure (NOT introduced by this work, not silently fixed):**

```text
FAILED tests/unit/test_agent_web_crawler_wrapper.py::test_top_level_web_crawler_wraps_canonical_worker
```

**Resolution (post-baseline)**: root-caused during final gates to a missing sandbox
dependency — `ModuleNotFoundError: No module named 'bs4'` (beautifulsoup4 was not
installed by the baseline `pip install -e ".[dev,backend]"`). Installing
beautifulsoup4 makes the test pass unchanged; no code fix was needed and none was made.

**Environment note**: pytest requires `httpx2` (starlette 1.3.x test client) and `pytest-asyncio`,
which are not pulled in by `pip install -e ".[dev,backend]"` on a fresh container; a debian-packaged
`PyJWT` also blocks editable install without `--ignore-installed PyJWT`.

---

## What exists (reusable foundations)

### Derivatives (PR1 merged as #395 — contracts only, zero runtime)
- `packages/shared/derivatives.ts` — ~40 enums, ~30 interfaces, 25 entity kinds,
  `DERIVATIVES_ACTOR_EDGE_LAYER_MAP` (30 actor edges H2H/H2A/A2H/A2A) +
  `DERIVATIVES_DOMAIN_EDGE_LAYER_MAP` (23 domain edges, all `DOMAIN_EXCLUDED`),
  `execution_by_aether: false` fail-closed envelope.
- `Backend Architecture/migrations/2026_07_derivatives_foundation.sql` — raw SQL (NOT Alembic),
  11 tables, `NUMERIC(38,18)`, `CHECK (execution_by_aether = FALSE)`,
  `UNIQUE(tenant_id, idempotency_key)`.
- Consent purpose `financial_activity` in `packages/shared/contracts/consent-registry.json`
  (explicit opt-in, 2555d retention, `allowModelTraining: false`).
- Docs: `docs/source-of-truth/DERIVATIVES_*.md` (5) + `docs/derivatives/*.md` (5), all thin stubs.
- **Absent**: backend service, repositories, routes, registered events, graph VertexType/EdgeType
  mirror, silver projector, Profile360 section, Noesis intent, metering dimension, DSR table mapping.

### Stablecoin (no dedicated domain; strong adjacent code)
- `services/x402/`: `StablecoinAsset` model, **real on-chain USDC verification** (Base ERC-20 log +
  Solana SPL via manual JSON-RPC), facilitator registry, settlement FSM.
- `services/web3/registries.py`: `TokenRegistry`, `ChainRegistry`, `ProtocolRegistry`,
  `BridgeRouteRegistry`, `MarketVenueRegistry` (all `BaseRepository`-backed).
- `services/onchain/`: `rpc_gateway.py`, `chain_listener.py` (single-chain RPC observation).
- Graph: `STABLECOIN_ASSET` vertex, `ACCEPTS_ASSET` / `PRICES_IN` edges already exist.
- **Absent**: canonical asset/deployment identity, observation taxonomy, valuation/depeg,
  support assertions, finality/reorg handling, reconciliation, flows, all product surfaces.

### Interoperability (greenfield)
- Only registry/classifier scaffolding: `BridgeRouteRegistry`, bridge tx classification by function
  selector (`web3/classifier.py`), bridge protocol seeds (stargate/across/wormhole/layerzero),
  `flow_trace` `cross_chain` flow type, graph `BRIDGES` edge.
- **Absent**: everything else (no message model, lifecycle, providers, correlation, security
  snapshots, routes, events, consent purpose).

### Platform integration points (all verified working)
- Event registry codegen: `packages/shared/contracts/event-registry.json` →
  `scripts/generate_contracts.py` → `events.ts` / `consent.ts` / `generated_registry.py` / doc tables.
- Feature flags: frozen dataclasses in `config/settings.py`; conditional router mounts in `main.py`.
- Silver dispatcher/projectors, `GoldRepository.materialize`, Profile360 sub-resource envelope,
  Noesis capability registry, OODA suggestion adapters, metering `MeteringEventType` +
  `validate_meter_names.py`, notification/webhook machinery, Kyber admin router pattern.

---

## Known defects found during audit (root-cause fixes in scope)

1. `Backend Architecture/aether-backend/shared/privacy/consent_enforcement.py` hardcodes a stale
   `CONSENT_PURPOSES` set that is missing `financial_activity` (added in PR1). Consumed by
   `services/capabilities/routes.py`. Fix: derive from the consent registry.
2. Derivatives PR1 migration bypassed Alembic (raw SQL in a separate dir). Fix: idempotent
   Alembic adoption revision so migrations have a single owner.
3. `shared/privacy/retention.py` `_DSR_SCOPE_TO_SILVER_TABLE` lacks mappings for the
   `derivatives_facts` DSR scope token that `financial_activity` already declares.

---

## Gap matrix (summary)

| Capability | Current state | Target state | Priority |
|---|---|---|---|
| Stablecoin canonical identity | x402 `StablecoinAsset` (per-network, x402-scoped) | `stablecoin_assets` + `stablecoin_deployments` registries + TS/Pydantic contracts | P0 |
| Stablecoin observation/finality/reconciliation | none | observation intake + finality checkpoints + reorg corrections + reconciliation records | P0 |
| Derivatives runtime | contracts + DDL only | typed repos, registries, FSMs, adapter framework + simulator + conformance, streams, reconciliation, P&L | P0 |
| Interop canonical domain | none | protocol-neutral message/path/gateway/application/intent/asset-leg/security model + lifecycle FSM | P0 |
| LayerZero V2 adapter | none | fixture-proven decode (PacketSent/Verified/Delivered), GUID correlation, checkpoints, reorg; CREDENTIAL_GATED for live scan | P0 |
| Other interop providers | none | honest SCAFFOLDED/CREDENTIAL_GATED scaffolds (wormhole, axelar, ccip, hyperlane, ibc, debridge) | P1 |
| Events/consent | `financial_activity` only | +108 events (stablecoin 31 / derivatives 40 / interop 37), +2 purposes | P0 |
| Graph | derivatives TS maps unmirrored | backend VertexType/EdgeType + layer maps + TS A2H parity | P0 |
| Silver/Gold/Profile360 | none for these domains | 3 projectors + 3 gold DDL modules + 3 Profile360 sub-resources | P0 |
| APIs + flags + permissions + metering | none | `/v1/stablecoins|derivatives|interoperability` + kyber admin routers, default-off flags, 18 permissions, 8 meters | P0 |
| Frontends | none | Aether overview+detail per domain; Kyber ops page per domain | P1 |
| Docs/ADRs/runbooks/artifacts | derivatives stubs only | full source-of-truth sets + 22 productization artifacts + ADRs + runbooks | P1 |

## External blockers (cannot be resolved in this environment)

- No live RPC endpoints / provider credentials → LayerZero live scanning, Chainlink price feeds,
  and venue adapters remain `CREDENTIAL_GATED`; six interop providers remain `SCAFFOLDED`.
- No Kafka / ClickHouse / Neptune infrastructure in CI → event-bus and graph run in their
  in-memory local modes; gold DDL ships as schema modules; staging soak deferred.
- No staging environment access → staging validation documented as a release blocker, not claimed.
