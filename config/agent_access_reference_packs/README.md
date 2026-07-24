# Agent Access Reference Packs

Curated, versioned descriptions of agent-access providers, expressed entirely in
the vocabulary that
`Backend Architecture/aether-backend/services/agentic_observability/provider_framework.py`
already defines. One YAML file per pack.

A pack is **read-only configuration**. It authorizes nothing, calls nothing, and
mutates nothing. It says: *this is the provider, this is what an observation of it
looks like, and these are the scopes a grant is approved to hold.*

| File | `provider_id` | Status |
|---|---|---|
| `x_reference.yaml` | `x_reference` | `reference` — grounded in `XReferenceAdapter` |
| `mcp_generic.yaml` | `mcp` | `reference` — grounded in AETHER's MCP observation vocabulary |
| `example_provider.yaml` | `example_provider` | `example` — **fictional template, not a real provider** |

## What consumes these

`reference_packs.approved_scope_baselines_for(provider_id)` returns
`{grant_id: [scope, ...]}` — the exact shape
`provider_framework.compute_permission_findings()` takes as its
`approved_scope_baselines` argument. Keys are
`AuthorizationGrantRecord.grant_id`; the function reports every grant scope
outside its baseline as an `unexpected_new_scope` finding.

```python
from services.agent_access_intelligence.reference_packs import approved_scope_baselines_for
from services.agentic_observability.provider_framework import compute_permission_findings

findings = compute_permission_findings(
    tenant_id, grants, actions,
    approved_scope_baselines=approved_scope_baselines_for("x_reference"),
)
```

## The two ways a pack can be wrong, and why they are not symmetric

- **Too-broad baseline** — a scope that should have been flagged is now inside the
  approved list, so `compute_permission_findings` stays quiet. A *false all-clear*.
- **Missing baseline** — the grant lookup defaults to `[]` and every observed scope
  is reported for review. Noisy, but it points at a human.

Everything about how these packs are written follows from that asymmetry:

1. **No fabricated third-party specifics.** A pack with `pack_status: reference`
   must list `grounded_in` — the repo files each claim is copied from — and the
   validator rejects it otherwise. Neither shipped reference pack asserts any
   provider's OAuth scope vocabulary, because nothing in this repository
   establishes one; both declare `baseline_status: none_asserted` and ship an empty
   `approved_scope_baselines`. An invented scope list that *looked* authoritative
   would be indistinguishable from a real one at the point where it silences a
   finding.
2. **Empty must be declared.** `approved_scope_baselines: {}` is only valid
   alongside `baseline_status: none_asserted`. A truncated or half-written pack
   cannot pass itself off as a deliberate no-baseline posture.
3. **A malformed pack raises; it is never skipped.** Skipping would silently
   degrade that provider to the empty-baseline case, and the caller would never
   learn its pack had gone missing.

`example_provider.yaml` is the one place a non-empty baseline appears, so the shape
is documented by example. Its `provider_id` matches no adapter, and
`approved_scope_baselines_for()` matches `provider_id` exactly, so its fictional
scopes can never reach a real provider.

## Pack schema (v1)

Required in every pack:

| Field | Meaning |
|---|---|
| `schema_version` | `1` |
| `pack_id` | unique; **must equal the filename stem** |
| `pack_version` | pack revision, e.g. `1.0.0` |
| `pack_status` | `reference` \| `example` |
| `provider_id` | provider identity, as used by `ProviderMetadata.provider_id` |
| `display_name` | human label |
| `capability_kind_defaults` | `default:` plus optional `by_object_type:`; every value is a `CapabilityKind` (`mcp_tool`, `provider_action`, `account`, `resource`, `unknown`) |
| `naming_hints` | mapping of hint name → list of observation field names carrying server/tool identity |
| `baseline_status` | `asserted` \| `none_asserted` |
| `approved_scope_baselines` | `{grant_id: [scope, ...]}`, passed verbatim to `compute_permission_findings` |

Required for `pack_status: reference`: `grounded_in` — a non-empty list of repo
paths/symbols backing the pack's claims.

Optional: `canonical_source`, `description`, `read_only`, `webhook_supported`,
`supported_operations`, `observation_hints`.

## Adding a pack

1. Copy `example_provider.yaml`. Name the file after its `pack_id`.
2. Fill in only what you can point at. Set `pack_status: reference` and list every
   grounding file in `grounded_in`. If you cannot ground it, it does not ship.
3. `python scripts/validate_reference_packs.py` (read-only; exits non-zero listing
   every violation).
4. `python -m pytest tests/unit/capability_catalog/test_reference_packs.py -q`

The schema is defined once, in
`services/agent_access_intelligence/reference_packs.py::pack_violations`, and the
validator imports it — the gate and the runtime loader cannot drift apart.
