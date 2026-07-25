# ============================================================================
# AETHER — Deployment Profile Locals
#
# Derives resource/cost toggles from `var.deployment_profile`. The canonical
# policy DATA lives in config/deployment_profiles.yaml; production-lean's
# cost_policy.required_resources / .forbidden_resources are the source of
# truth. These locals encode that policy at the Terraform layer AND are wired
# into module `count` and module inputs by main.tf, so a production-lean plan
# structurally cannot contain a forbidden resource — it is no longer merely
# documented as excluded.
#
# config/terraform_resource_contracts.yaml maps each canonical policy key to
# the module address and expected cardinality these locals produce, so a plan
# JSON can be checked against the policy without re-deriving it here.
#
# Cost invariant: for production-lean, EVERY forbidden-resource toggle below is
# false. Each one is a closed boolean expression over lean/scale/enterprise/
# staging (or the literal `false`) so that
# scripts/release/check_cost_policy_terraform.py can statically evaluate it.
# ============================================================================

locals {
  lean       = var.deployment_profile == "production-lean"
  scale      = var.deployment_profile == "production-scale"
  enterprise = var.deployment_profile == "enterprise-isolated"
  staging    = var.deployment_profile == "staging"

  # --------------------------------------------------------------------------
  # Forbidden-for-lean toggles (config/deployment_profiles.yaml →
  # production-lean.cost_policy.forbidden_resources)
  # --------------------------------------------------------------------------

  # Heavy managed backends. Only the two uncapped profiles list these under
  # `may_enable`, so only they may provision them.
  enable_elasticache = local.scale || local.enterprise
  enable_msk         = local.scale || local.enterprise
  enable_neptune     = local.scale || local.enterprise

  # ClickHouse is a selector today: production-scale / enterprise-isolated
  # declare `analytics: clickhouse`, but this root provisions no ClickHouse
  # resource yet. The toggle drives local.analytics_backend only.
  enable_clickhouse = local.scale || local.enterprise

  # Dedicated ML serving. Mirrors config/runtime_deployment.yaml `remote_ml`,
  # which is true for exactly production-scale and enterprise-isolated.
  enable_dedicated_ml = local.scale || local.enterprise

  # NAT is "forbidden unless explicit" for lean. This toggle is the PROFILE
  # DEFAULT posture and is false for the cost-capped profiles; an operator opts
  # in explicitly through var.network_egress_mode, which is precisely what
  # "unless explicit" means. The effective topology is local.nat_mode below.
  enable_nat_gateway = local.scale || local.enterprise

  # Frontends are immutable S3 origins fronted by a CDN in every profile —
  # this root runs no ECS-hosted frontend service at any profile, so the exact
  # derivation is `false`, not `scale || enterprise`.
  enable_frontend_ecs = false

  # Observability is CloudWatch-native in every profile. Aether runs no
  # self-managed Prometheus/Grafana servers at any tier.
  enable_prometheus_grafana = false

  # Legacy RDS Postgres. Aurora Serverless v2 is the database of record in all
  # four profiles; RDS is retained in code only as an importable rollback
  # target and is never provisioned by a fresh plan. See DECOMMISSION.md.
  enable_legacy_rds = false

  # --------------------------------------------------------------------------
  # Required-for-lean toggles (…cost_policy.required_resources)
  # --------------------------------------------------------------------------

  # Aurora Serverless v2 is the database of record for every deployable
  # profile — all four declare `database: aurora_postgres`.
  enable_aurora = true

  # Pay-per-use substrate. Held on for every profile: SQS/SNS and the DynamoDB
  # cache table cost effectively nothing at rest, they are the lean required
  # backends, and keeping them provisioned at scale makes a rollback off
  # Kafka/Redis a selector flip rather than a re-provision.
  enable_sqs_sns        = true
  enable_dynamodb_cache = true

  # Graph lives in Aurora Postgres for any profile that has no Neptune cluster.
  enable_postgres_graph = !local.enable_neptune

  # Static SPA origins, read from the canonical runtime matrix rather than
  # re-derived, so a profile that drops static frontends fails the plan test.
  enable_static_frontends = local.runtime_deployment.profiles[var.deployment_profile].static_frontends

  # --------------------------------------------------------------------------
  # Backend selectors — passed explicitly to modules/ecs so the running task
  # never has to infer its backend from whether a host string is empty.
  # --------------------------------------------------------------------------

  graph_backend     = local.enable_neptune ? "neptune" : "postgres"
  cache_backend     = local.enable_elasticache ? "redis" : "dynamodb"
  event_broker      = local.enable_msk ? "kafka" : "sns_sqs"
  analytics_backend = local.enable_clickhouse ? "clickhouse" : "postgres"

  # --------------------------------------------------------------------------
  # Network egress
  #
  # The profile default is the reviewed posture; var.network_egress_mode is the
  # explicit override that the `nat_gateway_unless_explicit` policy requires an
  # operator to set before a cost-capped profile may run a NAT Gateway.
  # profiles/*.tfvars pin the default explicitly so a plan is self-describing.
  # --------------------------------------------------------------------------

  default_network_egress_mode = (
    local.enterprise ? "ha_nat" :
    local.scale ? "single_nat" :
    "public_ip" # staging + production-lean
  )
  network_egress_mode = coalesce(var.network_egress_mode, local.default_network_egress_mode)

  # modules/vpc speaks nat_mode; only the two NAT modes create a gateway.
  nat_mode = (
    local.network_egress_mode == "ha_nat" ? "ha" :
    local.network_egress_mode == "single_nat" ? "single" :
    "none"
  )

  # With no NAT, ECS tasks reach the internet through a public IP on the task
  # ENI; vpc_endpoints/none keep tasks fully private.
  assign_public_ip = local.network_egress_mode == "public_ip"

  # --------------------------------------------------------------------------
  # Runtime topology
  # --------------------------------------------------------------------------

  # Per-role runtime sizing from the canonical deployment matrix, so
  # production-scale / enterprise-isolated actually scale. The api role is
  # excluded: the -backend service is sized by the ecs_backend_* variables.
  runtime_deployment = yamldecode(file("${path.module}/../../../config/runtime_deployment.yaml"))
  runtime_role_settings = {
    for role, cfg in local.runtime_deployment.profiles[var.deployment_profile].roles :
    role => {
      cpu           = cfg.cpu
      memory        = cfg.memory
      desired_count = cfg.desired_count
    } if role != "api"
  }

  # Declared now, consumed by the runtime-topology commit that follows. A
  # profile is `dedicated` when the canonical matrix gives it at least one
  # non-api role of its own, and `consolidated` when every role collapses into
  # the API task. All four deployable profiles are `dedicated` today.
  runtime_execution_mode = length(local.runtime_role_settings) > 0 ? "dedicated" : "consolidated"
}
