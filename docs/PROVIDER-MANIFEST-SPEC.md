---
title: Provider Manifest Spec
slug: architecture/provider-manifest-spec
section: architecture
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/integration_contracts/manifest.py
  - Backend Architecture/aether-backend/shared/integration_contracts/catalog.py
  - Backend Architecture/aether-backend/shared/integration_contracts/identity.py
  - Backend Architecture/aether-backend/shared/certification/readiness.py
canonical_owner: platform@aether
estimated_read_minutes: 13
toc_depth: 3
last_synced_commit: "c6aa7606"
---

# Provider Manifest Spec

The `ProviderManifest`
(`Backend Architecture/aether-backend/shared/integration_contracts/manifest.py`)
is the single, typed source of truth for what a provider capability **is** and
**needs**. It describes credential **shape** (`CredentialFieldSpec`) — never
credential values. This spec is the field-by-field reference and the honesty
invariants (§32) that keep a manifest from claiming more than its evidence
supports.

## 1. Identity

| Field | Type | Meaning |
|---|---|---|
| `provider_family` | `str` | Provider family (e.g. `shopify`) |
| `product_id` | `str` | Product within the family (e.g. `admin`) |
| `capability_id` | `str` | One capability of the product (e.g. `orders_read`) |
| `display_name` | `str` | Human label |
| `category` | `str` | Free string; a `ConnectorCategory` value where one fits |
| `identity_key` | property | `f"{provider_family}.{product_id}.{capability_id}"` |

`identity_key` is the canonical `family.product.capability` form and MUST equal
`identity().key` (`plugin_identity_key` asserts this). See
[PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md#1-the-plugin-contract).

## 2. Readiness

`ManifestReadiness` = a **state token** (reused `CredentialReadiness`
vocabulary) plus a coarse 1–5 level:

| State token | Level | Meaning |
|---|---|---|
| `scaffolded` | 1 | Descriptor only |
| `disabled` / `degraded` | ≤2 | Off-ramp states, visible nowhere |
| `replay_validated` | 3 | Verified against replay fixtures, no live creds |
| `credential_waiting` | — | Replay-validated material awaiting real credentials |
| `sandbox_validated` | 4 | Verified in a sandbox environment |
| `partner_live` | 5 | Production |

Certification **never upgrades readiness** — it verifies what the manifest
declares and fails the plugin when the evidence is weaker (see
[PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md)).

## 3. Availability

- `Availability` = `tenant_self_service`, `kyber_managed`, `olympus_system`,
  and `environments` (`EnvironmentAvailability`: `local`, `integration`,
  `staging`, `production`).
- A capability is reachable **only** where `environments` says it is.
- The environment gates feed the §32 invariants below (visible ⇒ level ≥ 3,
  staging ⇒ level ≥ 4).

## 4. Authentication

| Field | Meaning |
|---|---|
| `type` | `oauth2` / `api_key` / `composite` / `webhook_only` / `none` |
| `credential_schema` | List of `CredentialFieldSpec` — field **shape**, never values |
| `oauth` | `OAuthSpec` — `pkce`, `scopes`, `refresh_supported` |

`CredentialFieldSpec` fields: `name`, `type` (`string`/`secret`/`oauth_token`/
`json`/`number`/`boolean`/`url`), `required`, `secret`. **A manifest never
carries a credential value.**

## 5. Configuration

`Configuration.fields` — list of `ConfigFieldSpec` (`string`/`number`/
`boolean`/`json`/`url`/`enum`) for non-secret operator configuration.

## 6. Accounts

`Accounts` = `discovery_supported`, `selection_required`. Declares whether the
capability can discover accounts and whether account selection is required.

## 7. Webhooks

`Webhooks` = `supported`, `registration_supported`, `verification_scheme`.
`verification_scheme` is **mandatory whenever `supported` is true** (§32).

## 8. Sync

`Sync` = `initial_backfill`, `incremental`, `reconciliation`, and `cursor`
(the field/strategy an incremental sync advances, e.g. `"updated_at"`).
`cursor` is **mandatory whenever `incremental` is true** (§32).

## 9. Data outputs & destinations

- `data_outputs: list[str]` — required-but-may-be-empty: what the capability
  writes (e.g. `bronze.connector_events`). Forcing an explicit value is itself
  an honesty invariant — every manifest declares its outputs.
- `product_destinations: list[str]` — required-but-may-be-empty: where the
  data can go (e.g. an advertising product).

## 10. Deployment

`Deployment` = `required_environment`, `required_secrets`,
`required_public_urls`, `provider_registration_steps` — typed deployment
requirements, validated against the declared readiness/availability.

## 11. §32 honesty invariants (`validate_manifest`)

`validate_manifest(m) -> ProviderManifest` enforces the manifest-level rules
and raises `ManifestValidationError` collecting **every** violation. The rules,
verbatim:

| # | Rule |
|---|---|
| 1 | A capability enabled in **any** environment is at least replay-validated material: **visible-in-environment requires `level >= 3`**. |
| 2 | **`staging=True` requires `level >= 4`** (sandbox-validated is a higher bar than mere visibility). |
| 3 | **`authentication.type == "oauth2"` requires non-empty `oauth.scopes`** — a manifest cannot request OAuth without declaring the scopes it will request. |
| 4 | **`webhooks.supported=True` requires a non-empty `verification_scheme`** — a supported webhook must declare how inbound calls are verified. |
| 5 | **`sync.incremental=True` requires a non-empty `sync.cursor`** — an incremental sync must declare the cursor it advances. |

The structure (`ProviderManifest`) and the honesty gate are kept apart so a
test can build a structurally-valid-but-dishonest manifest and assert the gate
rejects it. Construction only enforces types and simple field bounds.

## 12. Capability-honesty gate (`capability_violations`)

Beyond the manifest, the **capability-honesty gate** (`capability_violations`
in `services/provider_runtime/validation.py`) cross-checks every manifest
claim against the plugin's actual adapter surface (`CapabilitySet`) in **both
directions**:

| Direction | Rule |
|---|---|
| Overclaim | manifest claims ⇒ a non-`None` adapter must exist: `authentication.type != "none"` ⇒ `auth()`; `webhooks.supported` ⇒ `webhook()`; `sync.incremental` ⇒ `pull()` **and** a `sync.cursor`; `accounts.discovery_supported` ⇒ `account()`; `sync.reconciliation` ⇒ `reconciliation()` |
| Underclaim | an adapter accessor returns non-`None` ⇒ the manifest must claim that capability |

The gate also folds in the manifest-level invariants (`validate_manifest`) and
the identity cross-check (`plugin_identity_key`), and runs at **registration
and certification** (`assert_plugin_honest` on every registration) — a plugin
can neither claim a capability its adapters do not provide nor hide one it
does (ADR-009 D3).

## 13. Examples

### 13.1 Legacy byte-identical case

The catalog (`shared/integration_contracts/catalog.py`) derives one manifest
per existing connector from its `ConnectorDescriptor`:

- `provider_family = connector_type`, `product_id = "ingestion"`,
  `capability_id = "connector"` — the identity `(type, "ingestion",
  "connector")` is **byte-identical** to the `LegacyConnectorPlugin`'s
  identity, so plugin and catalog cannot drift.
- Readiness is projected conservatively from `implementation_status`; a
  connector is visible in `local`/`integration` only at `level >= 3`, and
  `staging`/`production` stay `False` today (which keeps the derived manifests
  honest under §32 rules 1–2).
- Authentication is mapped by evidence: genuine OAuth **with real scopes** →
  `oauth2`; a webhook-only ingest connector → `webhook_only`; a secret-bearing
  connector → `api_key`; otherwise `none`. The `_OAUTH_SCOPES` map is the only
  way to turn a connector into real `oauth2` — nothing emits empty-scope OAuth.

### 13.2 Shopify native manifest

The reference plugin (`services/providers/shopify/plugin.py`) declares:

```python
ProviderManifest(
    provider_family="shopify",
    product_id="admin",
    capability_id="orders_read",
    display_name="Shopify Orders",
    category="commerce",
    readiness=ManifestReadiness(
        state=CredentialReadiness.CREDENTIAL_WAITING, level=3
    ),
    availability=Availability(
        tenant_self_service=False,
        environments=EnvironmentAvailability(
            local=True, integration=True, staging=False, production=False
        ),
    ),
    authentication=Authentication(
        type="api_key",
        credential_schema=[
            CredentialFieldSpec(name="api_key", type="secret", required=True, secret=True),
            CredentialFieldSpec(name="password", type="secret", required=True, secret=True),
            CredentialFieldSpec(name="shop_domain", type="string", required=True, secret=False),
            CredentialFieldSpec(name="shop_access_token", type="secret", required=False, secret=True),
            # Webhook HMAC secret for X-Shopify-Hmac-SHA256 verification. Required
            # to make the declared shopify_hmac scheme verifiable — the gateway is
            # fail-closed and would deny every delivery without it.
            CredentialFieldSpec(name="webhook_secret", type="secret", required=True, secret=True),
        ],
    ),
    webhooks=Webhooks(supported=True, registration_supported=False, verification_scheme="shopify_hmac"),
    sync=Sync(initial_backfill=True, incremental=True, reconciliation=False, cursor="updated_at"),
    data_outputs=["bronze.provider_events"],
    product_destinations=[],
)
```

Observe the honesty in practice: `api_key` (not `oauth2` — no real scopes are
declared, so no `oauth2` claim), visible in `local`/`integration` only
(§32 rule 1: level ≥ 3 holds; rule 2 not triggered because `staging=False`),
`webhooks.supported` with a concrete `verification_scheme="shopify_hmac"` and
a matching `webhook_secret` credential (rule 4 — the gateway is fail-closed
and would deny every delivery without it), and `sync.incremental` with
`cursor="updated_at"` (rule 5). Every capability claim maps to a real adapter
(`auth`, `account`, `pull`, `webhook`, `normalizer`), so the
capability-honesty gate passes at registration and certification.

## Related docs

- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md)
- [PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md)
- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
