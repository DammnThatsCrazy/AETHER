---
title: Provider Certification
slug: architecture/provider-certification
section: architecture
visibility: I
audience: [dev-senior, ops, architect]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/integration_contracts/certification.py
  - Backend Architecture/aether-backend/shared/certification/readiness.py
  - Backend Architecture/aether-backend/services/provider_runtime/
  - Backend Architecture/aether-backend/services/providers/routes.py
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
last_synced_commit: "5722d269"
---

# Provider Certification

Certification is the honesty harness of the Universal Provider Runtime (UPR).
A plugin is only as strong as its certification: a `CertificationReport` with a
failing check blocks the provider. This spec documents the harness, its checks,
and how to read its output.

## 1. Entry point

```python
certify_provider(plugin, *, environment="local") -> CertificationReport
```

- Runs against one plugin (one capability) in one environment.
- Returns a `CertificationReport`
  (`shared/integration_contracts/certification.py`): `schema_version`,
  `generated_at`, `identity` (`family.product.capability`), plugin version,
  declared manifest readiness, the environment, and one `CertificationCheck`
  per check (name / passed / detail). `passed` is the conjunction of all
  checks.

Readiness tokens mirror `CredentialReadiness` value-for-value
(`shared/certification/readiness.py`), so a readiness token travels losslessly
between the certification surface and the credential platform.

## 2. The checks

| # | Check | What it verifies |
|---|---|---|
| 1 | **Identity wellformed** | `identity().key` is a valid `family.product.capability` and equals `manifest().identity_key` (`plugin_identity_key`) |
| 2 | **Manifest honest** | `validate_manifest(manifest)` passes (§32) |
| 3 | **Capability honest** | the capability-honesty gate: every manifest claim maps to a real adapter (`CapabilitySet`) — see [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md#12-capability-honesty-gate-capability_violations) |
| 4 | **Credential schema honest** | `credential_schema` fields are wellformed `CredentialFieldSpec`s; no secret values present |
| 5 | **Webhook scheme honest** | when `webhooks.supported`, `verification_scheme` is non-empty AND the webhook adapter actually implements `verify()`; the scheme must be satisfiable under the fail-closed gateway — e.g. `shopify_hmac` requires a `webhook_secret` credential, or the gateway would deny every delivery |
| 6 | **Normalizer roundtrip** | `normalizer().normalize(...)` is deterministic: normalizing a fixture twice yields identical events; `dropped` is populated, never silent |
| 7 | **Auth contract no-secret** | the auth adapter resolves credentials only via `credential_service` refs; no secret material in the plugin or report |
| 8 | **Pull contract** | `pull().fetch(...)` returns an `AdapterResult[ReadBatch]` with `has_more ⇒ next_cursor` |
| 9 | **Outputs claimed** | every `data_outputs` entry the manifest claims is actually produced by the pipeline for the fixture |
| 10 | **Readiness not overclaimed** | the manifest's declared readiness level is supported by the evidence (e.g. `replay_validated` ⇒ replay fixtures exist and pass; `sandbox_validated` ⇒ sandbox evidence exists) |

## 3. "Never upgrades readiness"

Certification **verifies, it does not promote.** The report reflects the
declared `ManifestReadiness`; it never raises a plugin's level on its own.
Promotion is an operator decision made after certification passes at the
current level and the evidence (replay → sandbox → production) is supplied.

## 4. How a dishonest plugin fails

A plugin fails closed with **every violation collected**, never a partial
pass. Examples:

- Manifest claims `webhooks.supported=True` with no `verification_scheme` →
  `validate_manifest` violation (check 2).
- Manifest claims `oauth2` but the auth adapter accessor returns `None` →
  capability-honesty violation (check 3).
- Manifest declares `level=4` (`sandbox_validated`) but the fixtures only pass
  replay → readiness-overclaim violation (check 10).
- A normalizer silently drops a record type it cannot translate →
  normalizer-roundtrip violation (check 6).
- A secret appears in a manifest, a report, or the plugin package →
  auth/no-secret violation (check 7).

## 5. Where certification is invoked

- **Admin certify route** — `POST /v1/admin/kyber/provider-connections/certify`
  (`services/provider_runtime/routes.py`) certifies a registered plugin by
  identity in a chosen environment and returns the `CertificationReport`. The
  admin router mounts only when `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED` is set
  (in addition to `AETHER_PROVIDER_RUNTIME_ENABLED`).
- **At registration** — `ProviderRegistry.register` / `register_provider` runs
  the honesty-gated subset (identity, manifest, capability via
  `assert_plugin_honest`) when a plugin is registered, so a dishonest plugin
  never enters the registry at all.
- **In CI** — plugin fixtures are certified as part of the provider package's
  test suite.

## 6. Interpreting a report

| Level | Meaning |
|---|---|
| 3 | **Replay-validated** — verified against replay fixtures; no live credentials required |
| 4 | **Sandbox-validated** — verified against a provider sandbox |
| 5 | **Production (partner_live)** — verified against production-grade evidence |

A report with `passed=True` at level 3 means: "this plugin is honest and
deterministic as far as its fixtures show; it may be enabled in the
environments its manifest declares." Promotion to a higher level requires new
evidence and a new certification run — never a re-label.

## Related docs

- [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md)
- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md)
- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
