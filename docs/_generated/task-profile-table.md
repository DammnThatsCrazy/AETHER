<!-- DO NOT EDIT — generated from packages/shared/contracts/task-profile-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Task Profile Registry

Contract version: `1.0.0`

Canonical task-profile registry binding a model role, routing policy, guardrails, output kind, and latency/cost bounds to named harness tasks.

| Profile | Version | Role | Routing | Output kind | Guardrails | Evidence | Max tokens | Timeout (ms) | Retries | Purpose |
|---|---|---|---|---|---|---|---|---|---|---|
| `noesis_query_planning` | 1 | planning | auto | query_plan | `read_only`, `tenant_scope`, `allowlist_plan`, `no_write_keywords`, `no_injection` | no | 512 | 5000 | 1 | Deterministic, allowlisted text-to-query planning for the Noesis read-only runtime. |
| `grounded_answer_synthesis` | 1 | synthesis | auto | grounded_answer | `read_only`, `tenant_scope`, `evidence_required`, `redaction`, `no_injection` | yes | 1024 | 10000 | 1 | Grounded, evidence-cited answer synthesis over Aether-retrieved context. |
| `entity_classification` | 1 | classification | explicit | classification | `tenant_scope`, `no_injection` | no | 256 | 5000 | 1 | Structured classification of an entity or input against a tenant-policy-driven taxonomy. |
| `evidence_summarization` | 1 | summarization | auto | structured_json | `read_only`, `tenant_scope`, `redaction`, `freshness_bounded` | yes | 768 | 8000 | 1 | Compact summarization of a bounded Aether evidence set with source references preserved. |
