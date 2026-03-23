# Production Readiness Review v8.3.1

## Current Release Gate

Aether may be called production-ready only when all of the following are true in the deployed environment:

- durable API-key validation is configured via `AETHER_AUTH_DB_PATH`
- the event bus is configured via `AETHER_EVENT_BUS_DB_PATH`
- non-local cache traffic uses Redis via `REDIS_URL` or `REDIS_HOST`
- graph persistence is configured via `AETHER_GRAPH_DB_PATH`
- oracle signing keys and contract identifiers are configured explicitly
- non-local ML serving has real model artifacts present
- guardrail audit and spend ledgers are configured via `AETHER_GUARDRAILS_DB_PATH`
- the validation commands listed below pass on the release commit

## Implemented Production Contracts

### Auth
- API keys are validated against a durable SQLite registry rather than hardcoded test keys.
- Non-local environments must set `AETHER_AUTH_DB_PATH`; startup and validation fail if the durable auth store is not configured.
- Keys support revocation, expiry, tenant mapping, tier metadata, and permissions.

### Eventing
- The shared producer and consumer use a durable SQLite event bus rather than in-process lists.
- Events persist with `pending`, `processing`, `processed`, and `dead_letter` states.
- Non-local environments must set `AETHER_EVENT_BUS_DB_PATH`.

### Cache
- Non-local cache usage requires Redis.
- Local development may use a durable SQLite cache, but production-like environments fail fast when Redis is not configured.

### Graph
- The shared graph client persists vertices and edges in SQLite rather than in-memory adjacency lists.
- Non-local environments must set `AETHER_GRAPH_DB_PATH`.

### Oracle proofs
- Oracle proof generation and verification use real secp256k1 signing and verification via `cryptography`.
- Verification checks the message hash, the signature, and the derived signer identity.
- Non-local environments must set `ORACLE_SIGNER_KEY`, `ORACLE_INTERNAL_KEY`, and `REWARD_CONTRACT_ADDRESS`.

### ML serving
- Non-local serving refuses to start without real model artifacts.
- Stub models are only available for explicit local/test execution.

### Agent guardrails
- Audit logs and spend tracking persist durably in SQLite instead of process memory.
- Non-local environments must set `AETHER_GUARDRAILS_DB_PATH`.

## Release Validation Commands

Run these before shipping:

```bash
pytest tests/unit/test_prod_backends.py tests/unit/test_ml_model_artifact_enforcement.py -q
pytest tests/unit/test_backend_inmemory_guards.py tests/unit/test_oracle_routes_config.py -q
pytest 'ML Models/aether-ml/tests/unit/test_serving.py' -q
python scripts/sync_docs.py
python scripts/validate_docs.py
```

## Readiness Claim Policy

Do not claim "production ready", "all stubs replaced", or ">90% complete" unless:

1. all required environment variables above are configured in the target environment,
2. model artifacts exist in the deployed ML models directory,
3. the validation commands above are green on the release SHA, and
4. no remaining release notes or docs contradict the runtime behavior.
