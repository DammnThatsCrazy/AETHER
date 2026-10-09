---
title: Provider Manifest Spec
slug: architecture/provider-manifest-spec
section: architecture
visibility: I
audience: [dev-senior, architect]
status: stable
since_version: "0.1.0"
source_files:
  - services/backend/shared/integration_contracts/manifest.py
  - services/backend/shared/integration_contracts/streams.py
  - services/backend/shared/integration_contracts/catalog.py
  - services/backend/shared/integration_contracts/identity.py
  - services/backend/shared/certification/readiness.py
canonical_owner: platform@aether
estimated_read_minutes: 13
toc_depth: 3
source_hashes:
  "services/backend/shared/certification/readiness.py": "sha256:4f49477dd17b2652c27ca458b9d0c7fe8ca242defa7d1d6d5e837b50050846a2"
  "services/backend/shared/integration_contracts/catalog.py": "sha256:895abcded4185c421d1e84cb3e711b5c88abd963daf3260373c0f54a50c4a03c"
  "services/backend/shared/integration_contracts/identity.py": "sha256:8264880ababfa1eb2c6be6cbc099478d3e140e7caf1afcb52b664921b6b2871b"
  "services/backend/shared/integration_contracts/manifest.py": "sha256:88f1a5c8f3a8fa5d6b0e53d9277c26dab7e6ef1681caa4ef1a52085e9e038658"
  "services/backend/shared/integration_contracts/streams.py": "sha256:b3258eda634a1fab93ea43b924f0261447cae7fa63bd8c3bedfad79b0db5d676"
---

# Provider Manifest Spec

The `ProviderManifest`
(`services/backend/shared/integration_contracts/manifest.py`)
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
| `credential_waiting` | ≤2 | Credential or external evidence pending; no replay/sandbox claim |
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
| `credential_profiles` | Optional mode-selected alternative secret shapes; every mode is declared and complete |
| `oauth` | `OAuthSpec` — `pkce`, `scopes`, `refresh_supported` |

`CredentialFieldSpec` fields: `name`, `type` (`string`/`secret`/`oauth_token`/
`json`/`number`/`boolean`/`url`), `required`, `secret`. **A manifest never
carries a credential value.**

An optional `CredentialProfileSpec` names a non-secret enumerated config
`mode_field`, one `mode_value`, and the secret fields required in that mode.
The manifest validator requires one profile for every allowed mode value and
rejects an optional secret that belongs to no profile. The certification
harness checks those structural claims. The selected adapter still validates
the actual supplied credentials and fails closed when its mode's required
secret is absent.

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
`cursor` is **mandatory for legacy capability-level incremental sync** (§32).
When `streams` is non-empty, each incremental stream declares its own
`cursor_scheme` instead.

### Explicit stream declarations

`streams: list[StreamDescriptor]` is an additive, versioned inventory within
one provider capability. Existing v1 plugins leave it empty and retain their
capability-level behavior. A descriptor (`schema_version="1"`) names a stable
`stream_id`, `object_kind`, `domain_pack`, `output_contract`,
`source_authority_class`, `data_classification`, acquisition modes, required
OAuth scopes, optional cursor scheme and webhook topics, and backfill and
incremental flags. Its output must appear in the parent manifest's
`data_outputs`.

Registration validates unique stream IDs/topics, cursor and webhook claims,
OAuth scope coverage, aggregate sync/webhook flags, and whether the plugin
exposes the adapters it declares. `ProviderRegistry.streams_for(identity_key)`
returns the validated declarations. A descriptor is **capability metadata**;
it does not certify per-stream execution, replay, or provider API behavior.

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
| 5 | **Capability-level `sync.incremental=True` requires `sync.cursor` when `streams` is empty.** With explicit streams, every incremental stream requires `cursor_scheme`. |
| 6 | Explicit streams require unique IDs and unambiguous webhook topics; each mode, required scope, output, and aggregate sync/webhook flag must match the parent manifest. |

The structure (`ProviderManifest`) and the honesty gate are kept apart so a
test can build a structurally-valid-but-dishonest manifest and assert the gate
rejects it. Construction only enforces types and simple field bounds.

## 12. Capability-honesty gate (`capability_violations`)

Beyond the manifest, the **capability-honesty gate** (`capability_violations`
in `services/backend/services/provider_runtime/validation.py`) cross-checks every manifest
claim against the plugin's actual adapter surface (`CapabilitySet`) in **both
directions**:

| Direction | Rule |
|---|---|
| Overclaim | manifest claims ⇒ a non-`None` adapter must exist: `authentication.type != "none"` ⇒ `auth()`; `webhooks.supported` ⇒ `webhook()`; legacy `sync.incremental` ⇒ `pull()` and `sync.cursor`; `accounts.discovery_supported` ⇒ `account()`; `sync.reconciliation` ⇒ `reconciliation()`. Explicit stream `pull`/`report`/`stream` modes require their corresponding adapters. |
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

The reference plugin (`services/backend/services/providers/shopify/plugin.py`) declares:

```python
ProviderManifest(
    provider_family="shopify",
    product_id="admin",
    capability_id="orders_read",
    display_name="Shopify Orders",
    category="commerce",
    readiness=ManifestReadiness(
        state=CredentialReadiness.CREDENTIAL_WAITING, level=2
    ),
    availability=Availability(
        tenant_self_service=False,
        environments=EnvironmentAvailability(),
    ),
    authentication=Authentication(
        type="api_key",
        credential_schema=[
            CredentialFieldSpec(name="api_key", type="secret", required=False, secret=True),
            CredentialFieldSpec(name="password", type="secret", required=False, secret=True),
            CredentialFieldSpec(name="shop_domain", type="string", required=False, secret=False),
            CredentialFieldSpec(name="shop_access_token", type="secret", required=False, secret=True),
            CredentialFieldSpec(name="webhook_secret", type="secret", required=False, secret=True),
        ],
        credential_profiles=[
            CredentialProfileSpec(name="rest_basic", mode_field="orders_api", mode_value="rest", required_fields=["api_key", "password"]),
            CredentialProfileSpec(name="rest_hmac_webhooks", mode_field="orders_api", mode_value="rest_webhook", required_fields=["api_key", "password", "webhook_secret"]),
            CredentialProfileSpec(name="graphql_token", mode_field="orders_api", mode_value="graphql", required_fields=["shop_access_token"]),
        ],
    ),
    webhooks=Webhooks(supported=True, registration_supported=False, verification_scheme="shopify_hmac"),
    sync=Sync(initial_backfill=True, incremental=True, reconciliation=False, cursor="updated_at"),
    data_outputs=["bronze.provider_events"],
    product_destinations=[],
)
```

The excerpt shows the current structural claims; the actual manifest also
declares the stream and configuration fields. REST Basic, REST plus signed
webhooks, and GraphQL token credentials are alternatives selected by
`orders_api`. `webhook_secret` is optional in the base schema and required by
the `rest_webhook` profile only. GraphQL also requires an explicit
`source_account_realm` at runtime. The capability remains
`credential_waiting` at level 2 and unavailable in every environment until
provider replay and sandbox evidence is recorded. Registration checks that
the declared auth, account, pull, webhook, and normalizer adapters exist;
offline certification does not promote availability.

## Related docs

- [PROVIDER-PLUGIN-SPEC](PROVIDER-PLUGIN-SPEC.md)
- [PROVIDER-CERTIFICATION](PROVIDER-CERTIFICATION.md)
- [UNIVERSAL-PROVIDER-RUNTIME](UNIVERSAL-PROVIDER-RUNTIME.md)
- [ADR-009: Universal Provider Runtime](decisions/ADR-009-universal-provider-runtime.md)
