"""Model-harness generated-contract domain.

Owns the generated Python twins of the model-harness platform registries:
``generated_model_registry`` (canonical LLM catalog — providers, capability
flags, cost, aliases) and ``generated_task_profiles`` (task execution policy —
model role, routing, guardrails, latency/cost bounds). Both are derived from
``packages/shared/contracts/model-registry.json`` and
``packages/shared/contracts/task-profile-registry.json`` via
``scripts/generate_platform_contracts.py``; their TS twins live in
``packages/shared/model-registry.ts`` and ``packages/shared/task-profile.ts``.
"""
