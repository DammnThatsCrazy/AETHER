<!-- DO NOT EDIT — generated from the IRRL registries -->
<!-- Run: python scripts/generate_contracts.py -->

# AETHER Rights Authority (contract v1.0.0)

## Actions

| Action | Label | Envelope required | Source grant required |
|---|---|---:|---:|
| `ingest` | Ingest | no | yes |
| `store` | Store | yes | yes |
| `read` | Read | yes | no |
| `graph_mutate` | Mutate graph | yes | no |
| `derive` | Derive | yes | no |
| `train` | Train | yes | yes |
| `evaluate` | Evaluate | yes | yes |
| `aggregate` | Aggregate | yes | yes |
| `disclose` | Disclose | yes | no |
| `export` | Export | yes | no |
| `retain` | Retain | yes | no |
| `delete` | Delete | yes | no |
| `operate_kyber` | Operate Kyber | yes | no |

## Registered transforms

| Transform | Output class | Evidence | Approval |
|---|---|---|---:|
| `feature_extraction` | `aether_computational_artifact` | `lineage` | no |
| `embedding` | `aether_computational_artifact` | `lineage`, `retention` | no |
| `model_evaluation` | `aether_computational_artifact` | `lineage`, `training_rights` | yes |
| `model_training` | `aether_computational_artifact` | `lineage`, `training_rights`, `revocation_strategy` | yes |
| `aggregation` | `tenant_confidential_intelligence` | `lineage`, `aggregate_threshold` | no |
| `deidentification` | `olympus_generalized_intelligence` | `lineage`, `privacy_test`, `reidentification_test`, `aggregate_threshold` | yes |
| `promote_to_olympus_generalized_graph` | `olympus_generalized_intelligence` | `lineage`, `privacy_test`, `reidentification_test`, `aggregate_threshold`, `release_proof` | yes |
| `export` | `tenant_confidential_intelligence` | `lineage`, `recipient` | no |
| `recomputation` | `aether_computational_artifact` | `lineage`, `revocation_strategy` | no |
| `deletion` | `retained_compliance_record` | `lineage`, `deletion_receipt` | no |

## Profiles and activation states

Profiles: `legacy_restricted`, `secure_tenant`, `collaborative_learning`, `strategic_data_exchange`.

Activation states: `rights_pending`, `rights_review`, `rights_active`, `rights_restricted`, `rights_revoked`.
