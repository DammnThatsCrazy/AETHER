---
title: Provider Certification
slug: architecture/provider-certification
section: architecture
visibility: I
audience: [dev-senior, ops, architect]
status: stable
since_version: "0.1.0"
source_files:
  - services/backend/shared/integration_contracts/certification.py
  - services/backend/shared/certification/readiness.py
  - services/backend/services/provider_runtime/
  - services/backend/services/providers/routes.py
canonical_owner: platform@aether
estimated_read_minutes: 10
toc_depth: 3
source_hashes:
  "services/backend/services/provider_runtime/": "sha256:654c952f050f9122a6ed5323cc74c5ba84436344c3f4c812b5d1ade715ad0f17"
  "services/backend/services/providers/routes.py": "sha256:604d8af79653b6472262c42da610787ca6328aadef8c356d6635f56092c6ec39"
  "services/backend/shared/certification/readiness.py": "sha256:4f49477dd17b2652c27ca458b9d0c7fe8ca242defa7d1d6d5e837b50050846a2"
  "services/backend/shared/integration_contracts/certification.py": "sha256:2969b5f1176212f462882a7361fcdeebdaf13a390148eba0626c459451fdf101"
---

# Provider Certification

Certification is the honesty harness of the Universal Provider Runtime (UPR).
A failed `CertificationReport` marks that report as not passed; it does not by
itself disable a plugin or block runtime operations. Registration separately
rejects identity, manifest, and capability-honesty violations, while
environment availability and readiness remain manifest/evidence declarations
and tenant data rights are a separate raw-data admission gate. This
spec documents the harness, its checks, and how to read its output.

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
| 4 | **Credential schema honest** | credential fields are named, optional secrets belong to complete mode-selected profiles, and every declared mode has a satisfiable required-secret set; no secret values are stored in the manifest |
| 5 | **Webhook scheme honest** | when `webhooks.supported`, `verification_scheme` is non-empty and the webhook adapter accessor returns an adapter |
| 6 | **Normalizer roundtrip** | the normalizer returns a `NormalizationResult` for one opaque probe without raising |
| 7 | **Auth contract** | a present auth adapter returns `AdapterResult` for a no-credential probe without raising |
| 8 | **Pull contract** | a present pull adapter returns `AdapterResult` for a no-credential probe without raising |
| 9 | **Outputs claimed** | output and destination names, if declared, are non-empty strings without surrounding/control whitespace |
| 10 | **Readiness not overclaimed** | the manifest's level does not exceed its readiness state's fixed ceiling; the harness does not inspect live sandbox evidence |

The manifest and capability checks validate explicit stream declarations
against aggregate sync/webhook claims and present pull/report/stream adapters.
This is structural honesty only. The harness does not run every declared
stream, verify cursor durability, replay a fixture corpus, inspect a provider
sandbox, or prove graph/source-authority behavior. Those require separate
evidence before changing environment availability or readiness.

## 3. "Never upgrades readiness"

Certification **verifies, it does not promote.** The report reflects the
declared `ManifestReadiness`; it never raises a plugin's level on its own.
Promotion is an operator decision made after certification passes at the
current level and the evidence (replay → sandbox → production) is supplied.
Certification checks technical capability and fixture behavior; it does not
grant a source license or commercial-use right.

Certification is provider-level evidence; it does not grant a tenant permission
to retain a connected account's data. Every connection/account raw write still
passes the canonical tenant rights gate, which requires an active
`tenant_byod_data` grant for `provider-account:{connection_id}:{account_id}`.
The runtime checks that grant before writing raw Bronze or retaining a webhook
body. Tenant-use permissions default to false and must be granted explicitly.
The canonical grant service persists grants and lifecycle events through its
migration-owned repository; staging and production admission additionally
requires the database and schema to be available. Missing, ambiguous, revoked,
expired, or cross-tenant grants fail closed. Certification must not be used to
infer tenant consent, storage rights, graph authority, or production readiness.

## 4. How a dishonest plugin fails

A plugin fails closed with **every violation collected**, never a partial
pass. Examples:

- Manifest claims `webhooks.supported=True` with no `verification_scheme` →
  `validate_manifest` violation (check 2).
- Manifest claims `oauth2` but the auth adapter accessor returns `None` →
  capability-honesty violation (check 3).
- Manifest declares `credential_waiting` at level 3 → state-ceiling violation
  (check 10). The harness does not independently inspect sandbox fixtures.
- A normalizer raises on the opaque probe → normalizer-roundtrip violation
  (check 6). Other dropped-record behavior needs fixture tests.
- An optional secret is not covered by a complete profile for every allowed
  mode, or a profile requires an undeclared/non-secret field →
  credential-schema violation (check 4). Secret values in logs or code require
  separate review.

## 5. Where certification is invoked

- **Admin certify route** — `POST /v1/admin/kyber/provider-connections/certify`
  (`services/backend/services/provider_runtime/routes.py`) certifies a registered plugin in
  the `local` environment and returns the `CertificationReport`; this route does
  not currently accept an environment override. The admin router mounts only
  when `KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED` is set (in addition to
  `AETHER_PROVIDER_RUNTIME_ENABLED`).
- **At runtime registry registration** — `ProviderRegistry.register` runs the
  identity, manifest, and capability honesty checks through
  `assert_plugin_honest`, so a dishonest plugin never enters the runtime
  registry. The module-level `register_provider` helper checks/canonicalizes
  identity and duplicate keys, then places the plugin in the in-repo discovery
  store; full honesty validation occurs when `ProviderRegistry.load_all()`
  registers it.
- **In CI** — plugin fixtures are certified as part of the provider package's
  test suite.

## 6. Interpreting a report

| Level | Meaning |
|---|---|
| 3 | **Replay-validated** — verified against replay fixtures; no live credentials required |
| 4 | **Sandbox-validated** — verified against a provider sandbox |
| 5 | **Production (partner_live)** — verified against production-grade evidence |

A report with `passed=True` at level 3 means the structural checks passed and
the manifest claimed a level compatible with its state token. It does not by
itself prove replay or sandbox behavior. Promotion to a higher level requires
the appropriate external evidence and a new certification run.

## Related docs

- [PROVIDER-MANIFEST-SPEC](PROVIDER-MANIFEST-SPEC.md)
- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md)
- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
