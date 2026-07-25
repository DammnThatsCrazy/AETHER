# Provider-mocked profile plan used by the GitHub PR matrix.
#
# This exercises the real root module and provider schemas without contacting
# tenant infrastructure. Environment-authoritative plans remain a separate,
# credential-gated workflow job.
#
# One run block per deployable profile, each pinning its own variables, so a
# single `terraform test` covers all four with no -var-file. The capacity
# scalars mirror profiles/<profile>.tfvars and are set here explicitly because
# the CI job auto-loads exactly one profile's tfvars — without pinning them,
# three of the four run blocks would silently plan against the wrong capacity.
#
# `network_egress_mode` is deliberately set to null in every run block so the
# profile derivation in profiles.tf is what is under test, not the tfvars value.
#
# Every assertion below must be able to fail. Cardinality assertions read the
# planned module graph (`length(module.x)`), not the locals that produced it,
# so a local that stops being wired into `count` is caught rather than passed.

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-1a", "us-east-1b", "us-east-1c"]
    }
  }

  # The generated placeholder for a policy document's `json` is not valid JSON,
  # and the IAM/S3/SQS/KMS schemas validate it. A minimal empty policy is the
  # smallest value that parses.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  # Several resources validate the shape of the caller identity / region before
  # the API is ever reached, so the generated placeholders must look real.
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "111122223333"
      arn        = "arn:aws:iam::111122223333:role/terraform-ci"
      user_id    = "AIDACKCEVSQ6C2EXAMPLE"
    }
  }

  mock_data "aws_region" {
    defaults = {
      name = "us-east-1"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition  = "aws"
      dns_suffix = "amazonaws.com"
    }
  }
}

mock_provider "random" {}
mock_provider "auth0" {}
mock_provider "archive" {}

# Root variables that have no default. Provider-mocked configuration plans
# never touch infrastructure, so syntactically valid placeholders are correct
# here; real plans always receive the release-manifest digests and the tenant
# ACM/Auth0 values. Declaring them in the test file keeps `terraform test`
# runnable on its own, with no -var-file and no CI-generated tfvars.
variables {
  backend_image_digest           = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
  ml_image_digest                = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
  acm_certificate_arn            = "arn:aws:acm:us-east-1:111122223333:certificate/00000000-0000-0000-0000-000000000000"
  domain_name                    = "api.ci.aether.invalid"
  alert_email                    = "terraform-ci@aether.invalid"
  auth0_domain                   = "ci.aether.invalid"
  auth0_management_client_id     = "terraform-ci"
  auth0_management_client_secret = "not-a-production-secret"
  aether_app_url                 = "https://app.ci.aether.invalid"
  kyber_app_url                  = "https://kyber.ci.aether.invalid"
}

# ---------------------------------------------------------------------------
# staging — release rehearsal. Cost-capped: same forbidden set as lean.
# ---------------------------------------------------------------------------

run "staging_profile_plan" {
  command = plan

  variables {
    deployment_profile  = "staging"
    environment         = "staging"
    network_egress_mode = null
    aurora_min_acu      = 0
    aurora_max_acu      = 2
    log_retention_days  = 3
  }

  assert {
    condition = contains(
      ["staging", "production-lean", "production-scale", "enterprise-isolated"],
      var.deployment_profile,
    )
    error_message = "The selected deployment profile is not deployable."
  }

  # Reviewed capacity profile, fused with the egress posture profiles.tf must
  # derive for a cost-capped profile that pins no explicit override.
  assert {
    condition = alltrue([
      var.aurora_min_acu == 0,
      var.aurora_max_acu == 2,
      var.log_retention_days == 3,
      local.network_egress_mode == "public_ip",
      local.nat_mode == "none",
      local.assign_public_ip,
    ])
    error_message = "staging no longer matches the reviewed capacity/egress profile in profiles/staging.tfvars."
  }

  assert {
    condition = alltrue([
      length(module.msk) == 0,
      length(module.elasticache) == 0,
      length(module.neptune) == 0,
      length(module.rds) == 0,
    ])
    error_message = "The staging plan provisions a cost-capped data store it must not."
  }

  assert {
    condition = alltrue([
      length(module.vpc.nat_gateway_ids) == 0,
      length(module.vpc.nat_eip_ids) == 0,
      module.vpc.nat_mode == "none",
    ])
    error_message = "The staging plan provisions NAT egress."
  }

  assert {
    condition = alltrue([
      length(module.ecs.dedicated_ml_service_arns) == 0,
      length(module.ecs.dedicated_ml_target_group_arns) == 0,
      length(module.alb.ml_target_group_arns) == 0,
      module.alb.ml_target_group_arn == "",
      module.ecs.ml_service_name == "",
    ])
    error_message = "The staging plan provisions the dedicated ML service or its ALB target group."
  }

  # The normalized locals must collapse to "" — not to null — when the backing
  # module is absent, or a null flows into a string module input unnoticed.
  assert {
    condition = alltrue([
      local.redis_host == "",
      local.redis_auth_secret_arn == "",
      local.kafka_bootstrap_servers == "",
      local.neptune_endpoint == "",
    ])
    error_message = "A normalized data-store local is not the empty string with its module absent."
  }

  assert {
    condition = (
      local.graph_backend == "postgres" &&
      local.cache_backend == "dynamodb" &&
      local.event_broker == "sns_sqs" &&
      local.analytics_backend == "postgres"
    )
    error_message = "The staging backend selectors no longer match the deployment policy."
  }

  # Staging rehearses production-lean's packing, so it must show the same
  # consolidated shape: ONE non-api runtime service, keyed by the execution
  # group token the container boots as AETHER_ROLE.
  assert {
    condition = alltrue([
      length(module.ecs.runtime_service_names) == length(local.runtime_service_settings),
      length(local.runtime_service_settings) == 1,
      join(",", keys(local.runtime_service_settings)) == "lean-worker",
      contains(module.ecs.runtime_service_names, "AETHER-staging-lean-worker"),
      local.runtime_execution_mode == "consolidated",
    ])
    error_message = "The staging plan does not provision exactly one consolidated lean-worker service."
  }

  # Awake is the declared default, so nothing is scaled to zero here. This is
  # the counterpart of the asleep run below: without it, a multiplier stuck at
  # 0 would satisfy the sleep assertions and never be noticed.
  assert {
    condition = alltrue([
      var.staging_state == "awake",
      local.staging_state_multiplier == 1,
      module.ecs.backend_service_desired_count == 1,
      module.ecs.runtime_service_desired_counts["lean-worker"] == 1,
      module.ecs.backend_autoscaling_bounds.max == 2,
    ])
    error_message = "An awake staging plan no longer runs the reviewed baseline capacity."
  }
}

# ---------------------------------------------------------------------------
# staging, asleep — the same topology at zero capacity.
#
# The point of the lifecycle state is that sleeping is a capacity change and
# not a shape change: the plan must own exactly the same services and the same
# roles as the awake run above, with every count at zero.
# ---------------------------------------------------------------------------

run "staging_asleep_profile_plan" {
  command = plan

  variables {
    deployment_profile  = "staging"
    environment         = "staging"
    staging_state       = "asleep"
    network_egress_mode = null
    aurora_min_acu      = 0
    aurora_max_acu      = 2
    log_retention_days  = 3
  }

  assert {
    condition = alltrue([
      local.staging_state_multiplier == 0,
      module.ecs.backend_service_desired_count == 0,
      module.ecs.runtime_service_desired_counts["lean-worker"] == 0,
    ])
    error_message = "An asleep staging plan still runs tasks."
  }

  # The floor is what makes sleep stick. Application Auto Scaling clamps a
  # service UP to min_capacity, so a floor left at 1 revives the task within a
  # cooldown and the environment never sleeps — while a plan that only zeroed
  # desired_count would look entirely correct. It matters most for the api
  # service, whose desired_count is ignore_changes'd and therefore reaches an
  # applied workspace through nothing but this envelope.
  assert {
    condition = alltrue([
      module.ecs.backend_autoscaling_bounds.min == 0,
      local.runtime_service_settings["lean-worker"].autoscaling.min_capacity == 0,
    ])
    error_message = "An asleep staging plan leaves an autoscaling floor above zero, so Application Auto Scaling revives the service and staging never sleeps."
  }

  # Only the floor collapses. max_capacity is a static bound on the shape, not
  # a statement of current capacity, so it must survive sleeping untouched —
  # otherwise waking becomes a two-attribute change and a sleeping plan no
  # longer records the reviewed envelope. Both ceilings are the awake values.
  assert {
    condition = alltrue([
      module.ecs.backend_autoscaling_bounds.max == 2,
      local.runtime_service_settings["lean-worker"].autoscaling.max_capacity == 2,
    ])
    error_message = "An asleep staging plan also collapsed the autoscaling ceiling; only the floor should."
  }

  # Sleeping must not change the topology, only its capacity: the same one
  # service, hosting the same eight roles, with the same queue bindings.
  assert {
    condition = alltrue([
      join(",", keys(local.runtime_service_settings)) == "lean-worker",
      length(local.runtime_service_settings["lean-worker"].roles) == 8,
      length(module.ecs.runtime_service_queue_roles["lean-worker"]) == 4,
    ])
    error_message = "An asleep staging plan owns a different topology from an awake one."
  }
}

# ---------------------------------------------------------------------------
# production-lean — the founding-tenant target and the cost-policy subject.
# ---------------------------------------------------------------------------

run "production_lean_profile_plan" {
  command = plan

  variables {
    deployment_profile  = "production-lean"
    environment         = "production"
    network_egress_mode = null
    aurora_min_acu      = 0.5
    aurora_max_acu      = 4
    log_retention_days  = 3
  }

  assert {
    condition = alltrue([
      var.aurora_min_acu == 0.5,
      var.aurora_max_acu == 4,
      var.log_retention_days == 3,
      local.network_egress_mode == "public_ip",
      local.nat_mode == "none",
      local.assign_public_ip,
    ])
    error_message = "production-lean no longer matches the reviewed capacity/egress profile in profiles/production-lean.tfvars."
  }

  # Every forbidden-resource toggle false by derivation. Retained from the
  # original test as the static counterpart of the cardinality checks below —
  # this catches a bad derivation, those catch a toggle that is not wired.
  assert {
    condition = alltrue([
      !local.enable_elasticache,
      !local.enable_msk,
      !local.enable_neptune,
      !local.enable_clickhouse,
      !local.enable_dedicated_ml,
      !local.enable_nat_gateway,
      !local.enable_frontend_ecs,
      !local.enable_prometheus_grafana,
      !local.enable_legacy_rds,
    ])
    error_message = "A production-lean forbidden-resource toggle is no longer false."
  }

  # forbidden_resources: msk, elasticache, neptune, legacy_rds.
  assert {
    condition = alltrue([
      length(module.msk) == 0,
      length(module.elasticache) == 0,
      length(module.neptune) == 0,
      length(module.rds) == 0,
    ])
    error_message = "The production-lean plan provisions a forbidden data store."
  }

  # forbidden_resources: nat_gateway_unless_explicit.
  assert {
    condition = alltrue([
      length(module.vpc.nat_gateway_ids) == 0,
      length(module.vpc.nat_eip_ids) == 0,
      module.vpc.nat_mode == "none",
    ])
    error_message = "The production-lean plan provisions a NAT Gateway without an explicit network_egress_mode override."
  }

  # forbidden_resources: dedicated_ml_service (required_resources: inline_ml).
  assert {
    condition = alltrue([
      length(module.ecs.dedicated_ml_service_arns) == 0,
      length(module.ecs.dedicated_ml_target_group_arns) == 0,
      length(module.alb.ml_target_group_arns) == 0,
      module.alb.ml_target_group_arn == "",
      module.alb.ml_tg_arn_suffix == "",
      module.ecs.ml_service_name == "",
    ])
    error_message = "The production-lean plan provisions the dedicated ML service or its ALB target group instead of running inference inline."
  }

  # required_resources: aurora_serverless_v2, postgres_graph.
  assert {
    condition = alltrue([
      local.enable_aurora,
      local.enable_postgres_graph,
      module.aurora.db_name == var.db_name,
      local.graph_backend == "postgres",
    ])
    error_message = "The production-lean plan does not provision Aurora Serverless v2 as the database and graph of record."
  }

  # required_resources: sqs_sns, dynamodb.
  assert {
    condition = alltrue([
      length(module.sqs.role_queue_urls) > 0,
      length(module.sqs.role_queue_arns) == length(module.sqs.role_queue_urls),
      module.dynamodb_cache.table_name != "",
      local.sqs_queue_name == "AETHER-production-events",
      local.sqs_dlq_name == "AETHER-production-events-dlq",
      local.event_broker == "sns_sqs",
      local.cache_backend == "dynamodb",
    ])
    error_message = "The production-lean plan does not provision the SNS/SQS broker and DynamoDB cache it requires."
  }

  # required_resources: alb. The DNS name is only known after apply, so the
  # plan-time proof is the configuration-derived name of the load balancer and
  # of the backend target group every service registers with.
  assert {
    condition = alltrue([
      module.alb.alb_name == "aether-production-alb",
      module.alb.backend_target_group_name == "aether-production-backend",
    ])
    error_message = "The production-lean plan does not provision the ALB and its backend target group."
  }

  # required_resources: cloudfront_s3_frontends — two origins, each with a
  # public-access block, encryption config and an SSM pointer.
  assert {
    condition = alltrue([
      local.enable_static_frontends,
      length(aws_s3_bucket.static_frontend) == 2,
      length(aws_s3_bucket_public_access_block.static_frontend) == 2,
      length(aws_s3_bucket_server_side_encryption_configuration.static_frontend) == 2,
      length(aws_ssm_parameter.static_frontend_bucket) == 2,
    ])
    error_message = "The production-lean plan does not provision both static SPA origins and their SSM pointers."
  }

  # required_resources: explicit_runtime_role_services — one ECS service per
  # entry of the profile's `services:` map. production-lean is
  # execution_mode: consolidated, so that is exactly ONE non-api service, the
  # `lean-worker` execution group: eight roles in one task, not eight tasks.
  # The invariant is ownership (asserted below and enforced across the whole
  # matrix by check_delivery_topology.py), not one-service-per-role.
  assert {
    condition = alltrue([
      length(module.ecs.runtime_service_names) == length(local.runtime_service_settings),
      length(local.runtime_service_settings) == 1,
      join(",", keys(local.runtime_service_settings)) == "lean-worker",
      contains(module.ecs.runtime_service_names, "AETHER-production-lean-worker"),
      !contains(keys(local.runtime_service_settings), "api"),
      local.runtime_execution_mode == "consolidated",
      module.ecs.backend_service_desired_count > 0,
    ])
    error_message = "The production-lean plan does not provision exactly one consolidated lean-worker service plus the api-serving backend service."
  }

  # The consolidation-critical property: the single lean-worker task hosts all
  # eight worker roles and is handed one queue binding per role that owns a
  # queue. `queue_roles` are the literal keys of that task's
  # SQS_ROLE_QUEUE_URLS object, so a regression to a single SQS_QUEUE_URL —
  # seven roles silently consuming nothing — fails here rather than in
  # production. Four, not eight: modules/sqs provisions a dedicated queue for
  # the four roles in its consumer_role_queues map, and the rest fall back to
  # the shared events queue through SQS_QUEUE_URL by design.
  assert {
    condition = alltrue([
      length(local.runtime_service_settings["lean-worker"].roles) == 8,
      contains(local.runtime_service_settings["lean-worker"].roles, "outbox-relay"),
      contains(local.runtime_service_settings["lean-worker"].roles, "semantic-worker"),
      join(",", module.ecs.runtime_service_queue_roles["lean-worker"]) == "graph-writer,identity-worker,measurement-worker,stream-worker",
    ])
    error_message = "The lean-worker task does not bind one queue per hosted role; a consolidated task with one queue URL leaves seven roles consuming nothing."
  }

  # No Spot anywhere in a consolidated profile: the one worker task hosts
  # outbox-relay, so its surge capacity carries the at-least-once delivery
  # path, and the api service is never interruptible in any profile.
  assert {
    condition = alltrue([
      join(",", module.ecs.runtime_service_capacity_providers["lean-worker"]) == "FARGATE",
      join(",", module.ecs.backend_capacity_providers) == "FARGATE",
    ])
    error_message = "The production-lean plan puts the public API or the outbox-relay-hosting worker on FARGATE_SPOT."
  }

  # The api service's sizing and envelope come from the runtime matrix, not
  # from a variable default that can drift away from it.
  assert {
    condition = alltrue([
      module.ecs.backend_service_desired_count == 1,
      module.ecs.backend_autoscaling_bounds.min == 1,
      module.ecs.backend_autoscaling_bounds.max == 4,
      local.api_cpu == 1024,
      local.api_memory == 2048,
    ])
    error_message = "The production-lean api service no longer matches the reviewed baseline in config/runtime_deployment.yaml."
  }

  assert {
    condition = alltrue([
      local.redis_host == "",
      local.redis_auth_secret_arn == "",
      local.kafka_bootstrap_servers == "",
      local.neptune_endpoint == "",
      local.legacy_rds_endpoint == "",
      local.elasticache_replication_group_id == "",
      local.msk_cluster_name == "",
      local.neptune_cluster_id == "",
    ])
    error_message = "A normalized data-store local is not the empty string with its module absent."
  }
}

# ---------------------------------------------------------------------------
# production-scale — heavy backends on, single shared NAT.
# ---------------------------------------------------------------------------

run "production_scale_profile_plan" {
  command = plan

  variables {
    deployment_profile  = "production-scale"
    environment         = "production"
    network_egress_mode = null
    aurora_min_acu      = 1
    aurora_max_acu      = 8
    log_retention_days  = 7
  }

  assert {
    condition = alltrue([
      var.aurora_min_acu == 1,
      var.aurora_max_acu == 8,
      var.log_retention_days == 7,
      local.network_egress_mode == "single_nat",
      local.nat_mode == "single",
      !local.assign_public_ip,
    ])
    error_message = "production-scale no longer matches the reviewed capacity/egress profile in profiles/production-scale.tfvars."
  }

  assert {
    condition = alltrue([
      length(module.msk) == 1,
      length(module.elasticache) == 1,
      length(module.neptune) == 1,
    ])
    error_message = "The production-scale plan does not provision the heavy backends its profile enables."
  }

  # Legacy RDS is superseded at every profile, not merely at the lean one.
  assert {
    condition     = length(module.rds) == 0
    error_message = "The production-scale plan provisions legacy RDS alongside Aurora."
  }

  assert {
    condition = alltrue([
      length(module.vpc.nat_gateway_ids) == 1,
      length(module.vpc.nat_eip_ids) == 1,
      module.vpc.nat_mode == "single",
    ])
    error_message = "The production-scale plan does not provision exactly one shared NAT Gateway."
  }

  # module.ecs.dedicated_ml_target_group_arns is deliberately absent here: its
  # length depends on comparing the target group ARN to "", and that ARN is
  # only known after apply, so the list length is unknown at plan on profiles
  # that DO create it. The ALB-side list is count-derived and knowable, and
  # covers the same fact. The ECS-side list is still asserted empty on the two
  # cost-capped profiles, where it is known.
  assert {
    condition = alltrue([
      length(module.ecs.dedicated_ml_service_arns) == 1,
      length(module.alb.ml_target_group_arns) == 1,
      module.ecs.ml_service_name != "",
    ])
    error_message = "The production-scale plan does not provision the dedicated ML service and its ALB target group."
  }

  # Alarm dimensions for the heavy stores. These are reproduced in the root
  # rather than read back from the modules (a computed attribute would make the
  # alarm `count` unplannable), so they have to be asserted against the exact
  # identifiers the modules configure — a drifted reconstruction is a silently
  # dead alarm, not a plan error.
  assert {
    condition = alltrue([
      local.elasticache_replication_group_id == "aether-production-redis",
      local.msk_cluster_name == "aether-production-kafka",
      local.neptune_cluster_id == "aether-production-neptune",
    ])
    error_message = "A CloudWatch alarm dimension no longer matches the identifier its module configures."
  }

  assert {
    condition = (
      local.graph_backend == "neptune" &&
      local.cache_backend == "redis" &&
      local.event_broker == "kafka" &&
      local.analytics_backend == "clickhouse"
    )
    error_message = "The production-scale backend selectors no longer match the deployment policy."
  }

  # dedicated, not consolidated: eight non-api services, one per worker role,
  # each hosting exactly the role it is named after. This is the assertion that
  # stops the lean packing being applied to a profile that pays for isolation.
  assert {
    condition = alltrue([
      length(module.ecs.runtime_service_names) == length(local.runtime_service_settings),
      length(local.runtime_service_settings) == 8,
      local.runtime_execution_mode == "dedicated",
      !contains(keys(local.runtime_service_settings), "lean-worker"),
      alltrue([
        for key, cfg in local.runtime_service_settings : join(",", cfg.roles) == key
      ]),
    ])
    error_message = "The production-scale plan does not provision one dedicated ECS service per worker role."
  }

  # Spot policy, per the matrix: backlog-draining workers surge onto Spot,
  # while the public API and the at-least-once delivery path never do.
  assert {
    condition = alltrue([
      contains(module.ecs.runtime_service_capacity_providers["stream-worker"], "FARGATE_SPOT"),
      join(",", module.ecs.runtime_service_capacity_providers["outbox-relay"]) == "FARGATE",
      join(",", module.ecs.backend_capacity_providers) == "FARGATE",
    ])
    error_message = "The production-scale capacity providers no longer match the matrix Spot policy (never api, never outbox-relay)."
  }

  # A dedicated consumer service binds exactly its own queue; a dedicated
  # non-consumer service binds none and falls back to SQS_QUEUE_URL.
  assert {
    condition = alltrue([
      join(",", module.ecs.runtime_service_queue_roles["stream-worker"]) == "stream-worker",
      length(module.ecs.runtime_service_queue_roles["maintenance"]) == 0,
      module.ecs.backend_service_desired_count == 3,
      module.ecs.backend_autoscaling_bounds.max == 12,
    ])
    error_message = "The production-scale plan does not bind each dedicated service to its own role queue at the reviewed api capacity."
  }
}

# ---------------------------------------------------------------------------
# enterprise-isolated — heavy backends on, NAT per AZ.
# ---------------------------------------------------------------------------

run "enterprise_isolated_profile_plan" {
  command = plan

  variables {
    deployment_profile  = "enterprise-isolated"
    environment         = "production"
    network_egress_mode = null
    aurora_min_acu      = 2
    aurora_max_acu      = 16
    db_multi_az         = true
    log_retention_days  = 30
  }

  assert {
    condition = alltrue([
      var.aurora_min_acu == 2,
      var.aurora_max_acu == 16,
      var.db_multi_az == true,
      var.log_retention_days == 30,
      local.network_egress_mode == "ha_nat",
      local.nat_mode == "ha",
      !local.assign_public_ip,
    ])
    error_message = "enterprise-isolated no longer matches the reviewed capacity/egress profile in profiles/enterprise-isolated.tfvars."
  }

  assert {
    condition = alltrue([
      length(module.msk) == 1,
      length(module.elasticache) == 1,
      length(module.neptune) == 1,
      length(module.rds) == 0,
    ])
    error_message = "The enterprise-isolated plan does not provision the heavy backends its profile enables."
  }

  # One NAT Gateway and one EIP per AZ — three AZs come from the mocked
  # aws_availability_zones data source.
  assert {
    condition = alltrue([
      length(module.vpc.nat_gateway_ids) == 3,
      length(module.vpc.nat_eip_ids) == 3,
      module.vpc.nat_mode == "ha",
    ])
    error_message = "The enterprise-isolated plan does not provision one NAT Gateway per AZ."
  }

  # module.ecs.dedicated_ml_target_group_arns is deliberately absent here: its
  # length depends on comparing the target group ARN to "", and that ARN is
  # only known after apply, so the list length is unknown at plan on profiles
  # that DO create it. The ALB-side list is count-derived and knowable, and
  # covers the same fact. The ECS-side list is still asserted empty on the two
  # cost-capped profiles, where it is known.
  assert {
    condition = alltrue([
      length(module.ecs.dedicated_ml_service_arns) == 1,
      length(module.alb.ml_target_group_arns) == 1,
      module.ecs.ml_service_name != "",
    ])
    error_message = "The enterprise-isolated plan does not provision the dedicated ML service and its ALB target group."
  }

  assert {
    condition = (
      local.graph_backend == "neptune" &&
      local.cache_backend == "redis" &&
      local.event_broker == "kafka" &&
      local.analytics_backend == "clickhouse"
    )
    error_message = "The enterprise-isolated backend selectors no longer match the deployment policy."
  }

  assert {
    condition = alltrue([
      length(module.ecs.runtime_service_names) == length(local.runtime_service_settings),
      length(local.runtime_service_settings) == 8,
      local.runtime_execution_mode == "dedicated",
      !contains(keys(local.runtime_service_settings), "lean-worker"),
    ])
    error_message = "The enterprise-isolated plan does not provision one dedicated ECS service per worker role."
  }

  # The one deliberate difference from production-scale: NO Spot anywhere. A
  # single-tenant isolation contract prices predictable capacity above the
  # discount, so even the surge tail of an interruption-tolerant worker stays
  # on-demand. Asserted on the service the scale profile DOES put on Spot, so
  # this cannot pass by accident.
  assert {
    condition = alltrue([
      join(",", module.ecs.runtime_service_capacity_providers["stream-worker"]) == "FARGATE",
      join(",", module.ecs.runtime_service_capacity_providers["materializer"]) == "FARGATE",
      join(",", module.ecs.backend_capacity_providers) == "FARGATE",
    ])
    error_message = "The enterprise-isolated plan places a service on FARGATE_SPOT; this profile pays for non-interruptible capacity at every tier."
  }
}
