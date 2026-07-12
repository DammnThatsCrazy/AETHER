# ============================================================================
# AETHER — Deployment Profile Locals
#
# Derives resource/cost toggles from `var.deployment_profile`. The canonical
# policy DATA lives in config/deployment_profiles.yaml; production-lean's
# cost_policy.forbidden_resources is the source of truth. These locals encode
# that policy at the Terraform layer so a static gate can assert a lean plan
# never enables a forbidden resource.
#
# Cost invariant: for production-lean, EVERY enable_* toggle below is false.
# Each is derived as `local.scale || local.enterprise` (false when lean) or is
# the literal `false`. scripts/release/check_cost_policy_terraform.py statically
# verifies this derivation against the YAML forbidden list.
# ============================================================================

locals {
  lean       = var.deployment_profile == "production-lean"
  scale      = var.deployment_profile == "production-scale"
  enterprise = var.deployment_profile == "enterprise-isolated"
  staging    = var.deployment_profile == "staging"

  # Cost-gated resource toggles. production-lean => every one below is false.
  enable_elasticache        = local.scale || local.enterprise
  enable_msk                = local.scale || local.enterprise
  enable_neptune            = local.scale || local.enterprise
  enable_clickhouse         = local.scale || local.enterprise
  enable_dedicated_ml       = local.scale || local.enterprise
  enable_nat_gateway        = local.scale || local.enterprise
  enable_frontend_ecs       = local.scale || local.enterprise
  enable_prometheus_grafana = local.scale || local.enterprise
  enable_legacy_rds         = false

  # Backend selectors derived from the profile (documentation-level today;
  # runtime wiring tracked separately). Mirrors config/deployment_profiles.yaml.
  graph_backend = local.enable_neptune ? "neptune" : "postgres"
  cache_backend = local.enable_elasticache ? "redis" : "dynamodb"
  event_broker  = local.enable_msk ? "kafka" : "sns_sqs"
}

# ----------------------------------------------------------------------------
# TODO(FT-9-TERRAFORM-PROFILES): wire these locals into module `count`/config
# once the flat root is refactored so module outputs are consumed conditionally.
# Today main.tf references msk/elasticache/neptune/aurora module OUTPUTS directly
# (e.g. module.msk.bootstrap_brokers_tls, module.elasticache.primary_endpoint,
# module.neptune.cluster_endpoint) inside the ecs/monitoring modules, so adding
# `count` to those modules would convert them to lists and break every reference
# — i.e. break `terraform validate`. Until that refactor lands, the enforceable
# guarantee is scripts/release/check_cost_policy_terraform.py, which statically
# asserts these locals are false-by-derivation for production-lean.
# ----------------------------------------------------------------------------
