# ============================================================================
# AETHER — Deployment Profile Locals
#
# Derives resource/cost toggles from `var.deployment_profile`, which is one of
# two values: `staging` or `production`. The canonical policy DATA lives in
# config/deployment_profiles.yaml; production's cost_policy.required_resources
# and .forbidden_resources are the source of truth. These locals encode that
# policy at the Terraform layer AND are wired into module `count` and module
# inputs by main.tf, so a production plan structurally cannot contain a
# forbidden resource — it is not merely documented as excluded.
#
# config/terraform_resource_contracts.yaml maps each canonical policy key to
# the module address and expected cardinality these locals produce, so a plan
# JSON can be checked against the policy without re-deriving it here.
#
# HOW PRODUCTION GROWS. Production is sized by capacity inputs, not by a profile
# switch: ECS task counts and sizes in config/runtime_deployment.yaml and the
# Aurora capacity range in profiles/production.tfvars. A heavy backend (Redis,
# Kafka, Neptune, ClickHouse, a dedicated ML service, a NAT gateway) is added
# only when a measured bottleneck justifies it, as a reviewed change that flips
# its toggle below together with the matching cost policy and budget. The
# modules under modules/ stay in the repository for that day.
#
# Cost invariant: for production, EVERY forbidden-resource toggle below is false.
# Each is the literal `false` (or a closed boolean expression over the profile
# locals) so scripts/release/check_cost_policy_terraform.py can statically
# evaluate it.
# ============================================================================

locals {
  production = var.deployment_profile == "production"
  staging    = var.deployment_profile == "staging"

  # --------------------------------------------------------------------------
  # Forbidden toggles (config/deployment_profiles.yaml → production
  # .cost_policy.forbidden_resources)
  # --------------------------------------------------------------------------

  # Heavy managed backends. Neither profile provisions them.
  enable_elasticache = false
  enable_msk         = false
  enable_neptune     = false

  # ClickHouse is a selector today: this root provisions no ClickHouse
  # resource. The toggle drives local.analytics_backend only.
  enable_clickhouse = false

  # Dedicated ML serving. Mirrors config/runtime_deployment.yaml `remote_ml`,
  # which is false for both profiles: the semantic classifier runs inline.
  enable_dedicated_ml = false

  # NAT is "forbidden unless explicit". This toggle is the PROFILE DEFAULT
  # posture and is false; an operator opts in explicitly through
  # var.network_egress_mode, which is precisely what "unless explicit" means.
  # The effective topology is local.nat_mode below.
  enable_nat_gateway = false

  # Frontends are immutable S3 origins fronted by a CDN in every profile —
  # this root runs no ECS-hosted frontend service, so the exact derivation is
  # `false`.
  enable_frontend_ecs = false

  # Observability is CloudWatch-native in every profile. Aether runs no
  # self-managed Prometheus/Grafana servers.
  enable_prometheus_grafana = false

  # Legacy RDS Postgres. Aurora Serverless v2 is the database of record in both
  # profiles; RDS is retained in code only as an importable rollback target and
  # is never provisioned by a fresh plan. See DECOMMISSION.md.
  enable_legacy_rds = false

  # --------------------------------------------------------------------------
  # Required toggles (…cost_policy.required_resources)
  # --------------------------------------------------------------------------

  # Aurora Serverless v2 is the database of record for every deployable
  # profile.  skip_aurora lets a free-tier account bypass Aurora provisioning
  # (the API parameter WithExpressConfiguration forces Internet Access Gateway,
  # incompatible with the VPC topology) while still validating the rest of the
  # stack.
  enable_aurora = !var.skip_aurora

  # Pay-per-use substrate. SQS/SNS and the DynamoDB cache table cost
  # effectively nothing at rest and are the required backends.
  enable_sqs_sns        = true
  enable_dynamodb_cache = true

  # Graph lives in Aurora Postgres for any profile that has no Neptune cluster.
  enable_postgres_graph = !local.enable_neptune

  # Provider-credential CMK creation is driven by the root
  # `enable_credential_kms` variable (default true), not a local — the tftest
  # apply run passes false so its throwaway apply can tear down cleanly while
  # the plan runs keep asserting the key is present.

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
  # operator to set before a profile may run a NAT Gateway. profiles/*.tfvars
  # pin the default explicitly so a plan is self-describing.
  # --------------------------------------------------------------------------

  default_network_egress_mode = "public_ip" # staging + production
  network_egress_mode         = coalesce(var.network_egress_mode, local.default_network_egress_mode)

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
  # services/api/workers/runtime/roles.py::roles_in from the AETHER_ROLE token.
  runtime_deployment = yamldecode(file("${path.module}/../../../config/runtime_deployment.yaml"))
  runtime_profile    = local.runtime_deployment.profiles[var.deployment_profile]

  # Staging can be driven to zero desired tasks without changing the topology:
  # an asleep environment owns the same services as an awake one, but both
  # autoscaling bounds are zero so demand policies cannot wake it. Waking
  # restores the matrix's awake capacity envelope from the same input. Profiles
  # without a `staging_state` block are always at full capacity.
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
  #   autoscaling min_capacity — prevents a non-zero floor from reviving a task
  #     after desired_count reaches 0.
  #   autoscaling max_capacity — the hard sleep guard. With a non-zero ceiling,
  #     queue-depth or request metrics can scale a service back out while it is
  #     meant to be asleep. Both bounds must therefore be zero until the
  #     reviewed wake plan restores the declared ceiling.
  #   capacity_provider base_count — only for the full lane. Pilot staging
  #     pins this strategy at base 0 for both lifecycle states. The pilot
  #     topology uses one FARGATE provider at weight 100, so desired_count is
  #     the sole task-capacity control. Scaling base_count between awake/asleep
  #     changes aws_ecs_service.capacity_provider_strategy, which Terraform's
  #     AWS provider treats as replacement-only; the former multiplier caused
  #     both ECS services to be replaced on every wake and sleep.
  #
  # The declared max_capacity is the awake surge envelope. Multiplying it by
  # the lifecycle state keeps Terraform, the scaling policies and the sleep
  # verifier aligned: awake uses the matrix ceiling; asleep is pinned to 0..0.
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
      # resolved in-process by services/api/workers/runtime/roles.py::roles_in.
      roles         = cfg.roles
      cpu           = cfg.cpu
      memory        = cfg.memory
      desired_count = cfg.desired_count * local.staging_state_multiplier
      capacity_provider = {
        base       = cfg.capacity_provider.base
        base_count = var.deployment_lane == "pilot" ? 0 : cfg.capacity_provider.base_count * local.staging_state_multiplier
        surge      = cfg.capacity_provider.surge
      }
      autoscaling = {
        min_capacity     = cfg.autoscaling.min_capacity * local.staging_state_multiplier
        max_capacity     = cfg.autoscaling.max_capacity * local.staging_state_multiplier
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
  # separate variable, so `production: 1` is expressed in exactly one
  # place and staging_state drives the API to zero along with the workers.
  api_service       = local.runtime_profile.services["api"]
  api_desired_count = local.api_service.desired_count * local.staging_state_multiplier
  api_min_capacity  = local.api_service.autoscaling.min_capacity * local.staging_state_multiplier
  api_max_capacity  = local.api_service.autoscaling.max_capacity * local.staging_state_multiplier
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
    base_count = var.deployment_lane == "pilot" ? 0 : local.api_service.capacity_provider.base_count * local.staging_state_multiplier
    surge      = local.api_service.capacity_provider.surge
  }

  # Declared by the matrix, not inferred from how many services happen to
  # exist — inferring it would report `dedicated` for any profile that simply
  # had more than one service, which is exactly what a consolidated profile has.
  runtime_execution_mode = local.runtime_profile.execution_mode
}
