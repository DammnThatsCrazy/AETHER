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

  # Provider-credential envelope-encryption CMK. Required in every deployable
  # profile: staging rehearses production and every production profile stores
  # live provider credentials that must be envelope-encrypted under an approved
  # KMS-backed cipher (AwsKmsEnvelopeCredentialCipher). A CMK costs ~$1/month, so
  # like enable_aurora / enable_sqs_sns this is a literal true rather than a
  # scale-gated toggle. There is no ephemeral/demo profile in this root; if one
  # is added it should set this false and skip the module.
  enable_credential_kms = true

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

  # Runtime topology comes from the canonical deployment matrix (schema v2),
  # whose unit is the ECS SERVICE, not the logical role. A consolidated profile
  # packs eight worker roles into one `lean-worker` service; a dedicated profile
  # keeps one service per role. Terraform only needs the service shape — which
  # roles a service hosts is the runtime's concern, resolved in-process by
  # services/runtime/roles.py::roles_in from the AETHER_ROLE token.
  runtime_deployment = yamldecode(file("${path.module}/../../../config/runtime_deployment.yaml"))
  runtime_profile    = local.runtime_deployment.profiles[var.deployment_profile]

  # Staging can be driven to zero desired tasks without changing the topology:
  # an asleep environment owns exactly the same services as an awake one, so
  # waking is an input flip rather than a differently-shaped plan. Profiles that
  # declare no `staging_state` block are always at full capacity.
  staging_state_multiplier = try(
    local.runtime_profile.staging_state.states[var.staging_state].desired_count_multiplier,
    1,
  )

  # WHAT THE MULTIPLIER SCALES, and why each one is load-bearing:
  #
  #   desired_count — the obvious one, and on its own not enough. It is also
  #     only load-bearing because modules/ecs manages it: while
  #     aws_ecs_service.backend carried `ignore_changes = [desired_count]` this
  #     zero never reached an applied api service at all, so an "asleep"
  #     staging environment kept running the api task 24/7 while every plan
  #     said 0. See the lifecycle comment on that resource.
  #   autoscaling min_capacity — the other half, and the one that makes sleep
  #     STICK rather than merely start.
  #     Application Auto Scaling clamps a service up to its floor, so a floor of
  #     1 against a desired count of 0 revives the task within a cooldown and
  #     staging never sleeps at all: the saving evaporates and the "no always-on
  #     staging compute" guarantee becomes false while looking satisfied.
  #   capacity_provider base_count — the guaranteed on-demand floor. Leaving it
  #     at 1 would declare a guaranteed task under a desired count of 0, which
  #     is also what check_delivery_topology.py::capacity_errors rejects as
  #     CAPACITY_BASE_EXCEEDS_DESIRED.
  #
  # max_capacity is deliberately NOT scaled. The ceiling is a static safety
  # bound on the shape, not a statement of current capacity; collapsing it too
  # would make waking a two-attribute change and would erase the reviewed
  # envelope from a sleeping plan. Floor 0 with the declared ceiling is what
  # the staging lifecycle's sleep-plan verification reads back out of
  # reviewed.tfplan.json and compares against this matrix × the multiplier.
  #
  # An awake environment multiplies by 1 and is therefore unchanged.

  # Non-api services become the ecs module's for_each. The service KEY is the
  # AETHER_ROLE token the container boots with, which is why the consolidated
  # service is keyed `lean-worker` and not `workers`. The api service is
  # excluded here: it is served by the -backend service, the one load-bearing
  # naming exception in the matrix.
  runtime_service_settings = {
    for name, cfg in local.runtime_profile.services :
    name => {
      # The logical roles this ONE task hosts. Terraform carries them for a
      # single load-bearing reason: a consolidated task must bind one SQS queue
      # per hosted role, which one SQS_QUEUE_URL cannot express. Everything else
      # about a role (consumer group, DLQ, retry policy, metrics label) is
      # resolved in-process by services/runtime/roles.py::roles_in.
      roles         = cfg.roles
      cpu           = cfg.cpu
      memory        = cfg.memory
      desired_count = cfg.desired_count * local.staging_state_multiplier
      capacity_provider = {
        base       = cfg.capacity_provider.base
        base_count = cfg.capacity_provider.base_count * local.staging_state_multiplier
        surge      = cfg.capacity_provider.surge
      }
      autoscaling = {
        min_capacity     = cfg.autoscaling.min_capacity * local.staging_state_multiplier
        max_capacity     = cfg.autoscaling.max_capacity
        metric           = cfg.autoscaling.metric
        cooldown_seconds = cfg.autoscaling.cooldown_seconds
        # Exactly one threshold is declared per metric (the matrix pairs
        # sqs-queue-depth with queue_depth_target and
        # alb-request-count-per-target with request_count_target). Both keys are
        # projected on every entry, null when absent, so the map stays a single
        # object type instead of a union Terraform cannot unify.
        queue_depth_target   = try(cfg.autoscaling.queue_depth_target, null)
        request_count_target = try(cfg.autoscaling.request_count_target, null)
      }
    } if name != "api"
  }

  # The API service's own baseline, from the same matrix rather than a
  # separate variable, so `production-lean: 1` is expressed in exactly one
  # place and staging_state drives the API to zero along with the workers.
  api_service       = local.runtime_profile.services["api"]
  api_desired_count = local.api_service.desired_count * local.staging_state_multiplier
  api_min_capacity  = local.api_service.autoscaling.min_capacity * local.staging_state_multiplier
  api_max_capacity  = local.api_service.autoscaling.max_capacity
  api_cpu           = local.api_service.cpu
  api_memory        = local.api_service.memory

  # The api service's capacity providers come from the matrix too, which is a
  # correctness fix and not only a tidy-up: this root previously passed
  # `use_fargate_spot = true`, running the PUBLIC API at a 4:1 Spot:on-demand
  # ratio. The v2 matrix pins api to `{base: FARGATE, surge: FARGATE}` and
  # check_delivery_topology.py::SPOT_FORBIDDEN_ROLES forbids Spot on api and
  # outbox-relay outright, so the declared policy and the plan now agree.
  api_capacity_provider = {
    base       = local.api_service.capacity_provider.base
    base_count = local.api_service.capacity_provider.base_count * local.staging_state_multiplier
    surge      = local.api_service.capacity_provider.surge
  }

  # Declared by the matrix, not inferred from how many services happen to
  # exist — inferring it would report `dedicated` for any profile that simply
  # had more than one service, which is exactly what a consolidated profile has.
  runtime_execution_mode = local.runtime_profile.execution_mode
}
