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

  # required_resources: explicit_runtime_role_services — one dedicated service
  # per non-api role in config/runtime_deployment.yaml, never collapsed.
  assert {
    condition = alltrue([
      length(module.ecs.runtime_service_names) == length(local.runtime_role_settings),
      length(local.runtime_role_settings) >= 8,
      !contains(keys(local.runtime_role_settings), "api"),
      local.runtime_execution_mode == "dedicated",
      module.ecs.backend_service_desired_count > 0,
    ])
    error_message = "The production-lean plan does not provision one dedicated ECS service per non-api runtime role."
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
}
