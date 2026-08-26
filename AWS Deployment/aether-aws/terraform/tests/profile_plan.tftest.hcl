# Provider-mocked profile plan used by the GitHub PR matrix.
#
# This exercises the real root module and provider schemas without contacting
# tenant infrastructure. Environment-authoritative plans remain a separate,
# credential-gated workflow job.
#
# One run block per deployable profile, each pinning its own variables, so a
# single `terraform test` covers all six (four cloud + demo/preview) with no
# -var-file. The capacity scalars mirror profiles/<profile>.tfvars and are set
# here explicitly because the CI job auto-loads exactly one profile's tfvars —
# without pinning them, five of the six run blocks would silently plan against
# the wrong capacity.
#
# `network_egress_mode` is deliberately set to null in every run block so the
# profile derivation in profiles.tf is what is under test, not the tfvars value.
#
# Every assertion below must be able to fail. Cardinality assertions read the
# planned module graph (`length(module.x)`), not the locals that produced it,
# so a local that stops being wired into `count` is caught rather than passed.
#
# WHAT THIS FILE DOES NOT PROVE — stated because it used to claim otherwise.
# A run block's `variables {}` are inputs, so asserting `var.aurora_max_acu == 4`
# inside the block that sets `aurora_max_acu = 4` cannot fail, and the error
# message that used to blame `profiles/<profile>.tfvars` was false: `terraform
# test` reads no tfvars file at all, so editing one changes nothing here. Those
# clauses are gone. What survives is what a plan can actually decide: values
# derived from config/runtime_deployment.yaml (which profiles.tf really does
# read), the profile derivations in profiles.tf, and the shape of the planned
# module graph. Verifying the CONTENT of profiles/*.tfvars needs a checker that
# parses those files; it does not belong to, and cannot live in, a mocked plan.

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

  # ARNs generated for computed attributes are random 8-character strings, and
  # the provider schema validates any attribute that must be an ARN before the
  # API is reached. Plan-only runs never notice, but the `command = apply` run
  # at the bottom of this file does, so every ARN one resource here consumes
  # from another is given a syntactically real placeholder. These are shapes,
  # not identities: several resources of the same type share one value, which
  # is harmless because nothing asserts on an ARN.
  mock_resource "aws_kms_key" {
    defaults = {
      arn = "arn:aws:kms:us-east-1:111122223333:key/00000000-0000-0000-0000-000000000000"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::111122223333:role/aether-ci-mock"
    }
  }

  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:us-east-1:111122223333:aether-ci-mock"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-east-1:111122223333:log-group:/aether/ci-mock"
    }
  }

  mock_resource "aws_lb" {
    defaults = {
      arn = "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/app/aether-ci-mock/0000000000000000"
    }
  }

  mock_resource "aws_lb_target_group" {
    defaults = {
      arn = "arn:aws:elasticloadbalancing:us-east-1:111122223333:targetgroup/aether-ci-mock/0000000000000000"
    }
  }

  mock_resource "aws_lambda_function" {
    defaults = {
      arn = "arn:aws:lambda:us-east-1:111122223333:function:aether-ci-mock"
    }
  }

  mock_resource "aws_cloudwatch_event_rule" {
    defaults = {
      arn = "arn:aws:events:us-east-1:111122223333:rule/aether-ci-mock"
    }
  }

  # manage_master_user_password puts the generated credential in a nested
  # computed block, and modules/aurora reads master_user_secret[0].secret_arn.
  # A generated mock leaves that list empty, so the element is declared here.
  mock_resource "aws_rds_cluster" {
    defaults = {
      master_user_secret = [{
        kms_key_id    = "arn:aws:kms:us-east-1:111122223333:key/00000000-0000-0000-0000-000000000000"
        secret_arn    = "arn:aws:secretsmanager:us-east-1:111122223333:secret:aether-ci-mock-000000"
        secret_status = "active"
      }]
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
  backend_image_digest = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
  ml_image_digest      = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
  acm_certificate_arn  = "arn:aws:acm:us-east-1:111122223333:certificate/00000000-0000-0000-0000-000000000000"
  domain_name          = "api.ci.aether.invalid"
  alert_email          = "terraform-ci@aether.invalid"
  aether_app_url       = "https://app.ci.aether.invalid"
  kyber_app_url        = "https://kyber.ci.aether.invalid"
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

  # The egress posture profiles.tf must derive for a cost-capped profile that
  # pins no explicit override. (var.deployment_profile's own membership in the
  # deployable set is enforced by its validation block in variables.tf, not by
  # re-asserting an input against itself here.)
  assert {
    condition = alltrue([
      local.network_egress_mode == "public_ip",
      local.nat_mode == "none",
      local.assign_public_ip,
    ])
    error_message = "staging no longer derives the cost-capped egress posture (public_ip / no NAT) from profiles.tf."
  }

  # TASK PLACEMENT — the first-apply blocker this pins.
  #
  # public_ip mode provisions no NAT Gateway, so aws_route.private_nat has
  # count 0 and the private route tables carry no 0.0.0.0/0 route whatsoever.
  # A task ENI placed there cannot reach ECR, Secrets Manager or CloudWatch —
  # assign_public_ip does not help, because egress follows the SUBNET's route
  # table — so the very first apply ends in CannotPullContainerError and a
  # circuit-breaker rollback. Tasks must therefore be in the public tier, which
  # has the IGW default route.
  #
  # The assertion reads module.ecs's own placement keys, i.e. the map the three
  # network_configuration blocks index, not the root local that produced it.
  # Subnet IDs are unknown until apply and can pin nothing; the "<tier>/<az>"
  # keys are configuration-derived and known at plan.
  assert {
    condition = alltrue([
      join(",", module.ecs.task_subnet_keys) ==
      "public/us-east-1a,public/us-east-1b,public/us-east-1c",
      !module.vpc.private_subnets_have_internet_route,
      local.ecs_task_subnet_tier == "public",
    ])
    error_message = "staging places ECS tasks somewhere other than the public subnets while running no NAT Gateway; those tasks have no route to ECR and the first apply cannot reach steady state."
  }

  # The security invariant that must hold BECAUSE of the placement above: a
  # public IP on the task ENI must buy egress and nothing else. The ECS
  # security group admits 8000/8080 from the ALB security group only, and no
  # CIDR ingress of any kind.
  assert {
    condition = alltrue([
      join(",", sort([for rule in module.vpc.ecs_sg_ingress : tostring(rule.port)])) == "8000,8080",
      alltrue([for rule in module.vpc.ecs_sg_ingress : length(rule.cidr_blocks) == 0]),
      alltrue([for rule in module.vpc.ecs_sg_ingress : rule.from_alb]),
    ])
    error_message = "The ECS task security group admits a CIDR or a port the ALB does not front; with tasks on public IPs that publishes an application port to the internet."
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

  # required_resources: credential_kms — the provider-credential envelope-
  # encryption CMK is provisioned in every cloud profile. A staging plan that
  # dropped it would run the AwsKmsEnvelopeCredentialCipher with no key.
  assert {
    condition     = length(module.kms_credentials) == 1
    error_message = "The staging plan does not provision the provider-credential envelope-encryption CMK."
  }

  assert {
    condition = alltrue([
      length(module.vpc.nat_gateway_ids) == 0,
      length(module.vpc.nat_eip_ids) == 0,
      module.vpc.nat_mode == "none",
    ])
    error_message = "The staging plan provisions NAT egress."
  }

  # The staging target group keeps its deterministic import identity and must
  # replace in place; the module exposes the literal lifecycle choice so this
  # profile contract cannot silently regress to same-name create-before-destroy.
  assert {
    condition     = module.alb.backend_target_group_replacement_strategy == "destroy-before-create"
    error_message = "The staging plan does not use the collision-safe target-group replacement strategy."
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
# demo — ephemeral-class. Temporary live demo with a seeded backend tenant.
# Cost-capped and TTL-cleanup-required: same forbidden set and egress posture
# as staging, in the same consolidated lean-worker shape.
# ---------------------------------------------------------------------------

run "demo_profile_plan" {
  command = plan

  variables {
    deployment_profile  = "demo"
    environment         = "staging"
    network_egress_mode = null
    aurora_min_acu      = 0
    aurora_max_acu      = 2
    log_retention_days  = 3
  }

  # The egress posture profiles.tf must derive for a cost-capped profile that
  # pins no explicit override. (var.deployment_profile's own membership in the
  # deployable set is enforced by its validation block in variables.tf, not by
  # re-asserting an input against itself here.)
  assert {
    condition = alltrue([
      local.network_egress_mode == "public_ip",
      local.nat_mode == "none",
      local.assign_public_ip,
    ])
    error_message = "demo no longer derives the cost-capped egress posture (public_ip / no NAT) from profiles.tf."
  }

  # TASK PLACEMENT — the first-apply blocker this pins.
  #
  # public_ip mode provisions no NAT Gateway, so aws_route.private_nat has
  # count 0 and the private route tables carry no 0.0.0.0/0 route whatsoever.
  # A task ENI placed there cannot reach ECR, Secrets Manager or CloudWatch —
  # assign_public_ip does not help, because egress follows the SUBNET's route
  # table — so the very first apply ends in CannotPullContainerError and a
  # circuit-breaker rollback. Tasks must therefore be in the public tier, which
  # has the IGW default route.
  #
  # The assertion reads module.ecs's own placement keys, i.e. the map the three
  # network_configuration blocks index, not the root local that produced it.
  # Subnet IDs are unknown until apply and can pin nothing; the "<tier>/<az>"
  # keys are configuration-derived and known at plan.
  assert {
    condition = alltrue([
      join(",", module.ecs.task_subnet_keys) ==
      "public/us-east-1a,public/us-east-1b,public/us-east-1c",
      !module.vpc.private_subnets_have_internet_route,
      local.ecs_task_subnet_tier == "public",
    ])
    error_message = "demo places ECS tasks somewhere other than the public subnets while running no NAT Gateway; those tasks have no route to ECR and the first apply cannot reach steady state."
  }

  # The security invariant that must hold BECAUSE of the placement above: a
  # public IP on the task ENI must buy egress and nothing else. The ECS
  # security group admits 8000/8080 from the ALB security group only, and no
  # CIDR ingress of any kind.
  assert {
    condition = alltrue([
      join(",", sort([for rule in module.vpc.ecs_sg_ingress : tostring(rule.port)])) == "8000,8080",
      alltrue([for rule in module.vpc.ecs_sg_ingress : length(rule.cidr_blocks) == 0]),
      alltrue([for rule in module.vpc.ecs_sg_ingress : rule.from_alb]),
    ])
    error_message = "The ECS task security group admits a CIDR or a port the ALB does not front; with tasks on public IPs that publishes an application port to the internet."
  }

  assert {
    condition = alltrue([
      length(module.msk) == 0,
      length(module.elasticache) == 0,
      length(module.neptune) == 0,
      length(module.rds) == 0,
    ])
    error_message = "The demo plan provisions a cost-capped data store it must not."
  }

  # required_resources: credential_kms — the provider-credential envelope-
  # encryption CMK is provisioned in every cloud profile. A demo plan that
  # dropped it would run the AwsKmsEnvelopeCredentialCipher with no key.
  assert {
    condition     = length(module.kms_credentials) == 1
    error_message = "The demo plan does not provision the provider-credential envelope-encryption CMK."
  }

  assert {
    condition = alltrue([
      length(module.vpc.nat_gateway_ids) == 0,
      length(module.vpc.nat_eip_ids) == 0,
      module.vpc.nat_mode == "none",
    ])
    error_message = "The demo plan provisions NAT egress."
  }

  assert {
    condition = alltrue([
      length(module.ecs.dedicated_ml_service_arns) == 0,
      length(module.ecs.dedicated_ml_target_group_arns) == 0,
      length(module.alb.ml_target_group_arns) == 0,
      module.alb.ml_target_group_arn == "",
      module.ecs.ml_service_name == "",
    ])
    error_message = "The demo plan provisions the dedicated ML service or its ALB target group."
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
    error_message = "The demo backend selectors no longer match the deployment policy."
  }

  # Demo is an ephemeral-class profile and is expected to run the same
  # consolidated shape as staging: ONE non-api runtime service, keyed by the
  # execution group token the container boots as AETHER_ROLE.
  assert {
    condition = alltrue([
      length(module.ecs.runtime_service_names) == length(local.runtime_service_settings),
      length(local.runtime_service_settings) == 1,
      join(",", keys(local.runtime_service_settings)) == "lean-worker",
      contains(module.ecs.runtime_service_names, "AETHER-staging-lean-worker"),
      local.runtime_execution_mode == "consolidated",
    ])
    error_message = "The demo plan does not provision exactly one consolidated lean-worker service."
  }

  # Ephemeral-class plans are not scaled to zero by default; the reviewed
  # baseline must still run.
  assert {
    condition = alltrue([
      var.staging_state == "awake",
      local.staging_state_multiplier == 1,
      module.ecs.backend_service_desired_count == 1,
      module.ecs.runtime_service_desired_counts["lean-worker"] == 1,
      module.ecs.backend_autoscaling_bounds.max == 2,
    ])
    error_message = "A demo plan no longer runs the reviewed baseline capacity."
  }
}

# ---------------------------------------------------------------------------
# preview — ephemeral-class. PR-specific live environment, only when explicitly
# requested. Cost-capped, auto-expire, no dedicated VPC/ALB/Aurora/Neptune:
# same forbidden set and egress posture as staging, in the same consolidated
# lean-worker shape.
# ---------------------------------------------------------------------------

run "preview_profile_plan" {
  command = plan

  variables {
    deployment_profile  = "preview"
    environment         = "staging"
    network_egress_mode = null
    aurora_min_acu      = 0
    aurora_max_acu      = 2
    log_retention_days  = 3
  }

  # The egress posture profiles.tf must derive for a cost-capped profile that
  # pins no explicit override. (var.deployment_profile's own membership in the
  # deployable set is enforced by its validation block in variables.tf, not by
  # re-asserting an input against itself here.)
  assert {
    condition = alltrue([
      local.network_egress_mode == "public_ip",
      local.nat_mode == "none",
      local.assign_public_ip,
    ])
    error_message = "preview no longer derives the cost-capped egress posture (public_ip / no NAT) from profiles.tf."
  }

  # TASK PLACEMENT — the first-apply blocker this pins.
  #
  # public_ip mode provisions no NAT Gateway, so aws_route.private_nat has
  # count 0 and the private route tables carry no 0.0.0.0/0 route whatsoever.
  # A task ENI placed there cannot reach ECR, Secrets Manager or CloudWatch —
  # assign_public_ip does not help, because egress follows the SUBNET's route
  # table — so the very first apply ends in CannotPullContainerError and a
  # circuit-breaker rollback. Tasks must therefore be in the public tier, which
  # has the IGW default route.
  #
  # The assertion reads module.ecs's own placement keys, i.e. the map the three
  # network_configuration blocks index, not the root local that produced it.
  # Subnet IDs are unknown until apply and can pin nothing; the "<tier>/<az>"
  # keys are configuration-derived and known at plan.
  assert {
    condition = alltrue([
      join(",", module.ecs.task_subnet_keys) ==
      "public/us-east-1a,public/us-east-1b,public/us-east-1c",
      !module.vpc.private_subnets_have_internet_route,
      local.ecs_task_subnet_tier == "public",
    ])
    error_message = "preview places ECS tasks somewhere other than the public subnets while running no NAT Gateway; those tasks have no route to ECR and the first apply cannot reach steady state."
  }

  # The security invariant that must hold BECAUSE of the placement above: a
  # public IP on the task ENI must buy egress and nothing else. The ECS
  # security group admits 8000/8080 from the ALB security group only, and no
  # CIDR ingress of any kind.
  assert {
    condition = alltrue([
      join(",", sort([for rule in module.vpc.ecs_sg_ingress : tostring(rule.port)])) == "8000,8080",
      alltrue([for rule in module.vpc.ecs_sg_ingress : length(rule.cidr_blocks) == 0]),
      alltrue([for rule in module.vpc.ecs_sg_ingress : rule.from_alb]),
    ])
    error_message = "The ECS task security group admits a CIDR or a port the ALB does not front; with tasks on public IPs that publishes an application port to the internet."
  }

  assert {
    condition = alltrue([
      length(module.msk) == 0,
      length(module.elasticache) == 0,
      length(module.neptune) == 0,
      length(module.rds) == 0,
    ])
    error_message = "The preview plan provisions a cost-capped data store it must not."
  }

  # required_resources: credential_kms — the provider-credential envelope-
  # encryption CMK is provisioned in every cloud profile. A preview plan that
  # dropped it would run the AwsKmsEnvelopeCredentialCipher with no key.
  assert {
    condition     = length(module.kms_credentials) == 1
    error_message = "The preview plan does not provision the provider-credential envelope-encryption CMK."
  }

  assert {
    condition = alltrue([
      length(module.vpc.nat_gateway_ids) == 0,
      length(module.vpc.nat_eip_ids) == 0,
      module.vpc.nat_mode == "none",
    ])
    error_message = "The preview plan provisions NAT egress."
  }

  assert {
    condition = alltrue([
      length(module.ecs.dedicated_ml_service_arns) == 0,
      length(module.ecs.dedicated_ml_target_group_arns) == 0,
      length(module.alb.ml_target_group_arns) == 0,
      module.alb.ml_target_group_arn == "",
      module.ecs.ml_service_name == "",
    ])
    error_message = "The preview plan provisions the dedicated ML service or its ALB target group."
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
    error_message = "The preview backend selectors no longer match the deployment policy."
  }

  # Preview is an ephemeral-class profile and is expected to run the same
  # consolidated shape as staging: ONE non-api runtime service, keyed by the
  # execution group token the container boots as AETHER_ROLE.
  assert {
    condition = alltrue([
      length(module.ecs.runtime_service_names) == length(local.runtime_service_settings),
      length(local.runtime_service_settings) == 1,
      join(",", keys(local.runtime_service_settings)) == "lean-worker",
      contains(module.ecs.runtime_service_names, "AETHER-staging-lean-worker"),
      local.runtime_execution_mode == "consolidated",
    ])
    error_message = "The preview plan does not provision exactly one consolidated lean-worker service."
  }

  # Ephemeral-class plans are not scaled to zero by default; the reviewed
  # baseline must still run.
  assert {
    condition = alltrue([
      var.staging_state == "awake",
      local.staging_state_multiplier == 1,
      module.ecs.backend_service_desired_count == 1,
      module.ecs.runtime_service_desired_counts["lean-worker"] == 1,
      module.ecs.backend_autoscaling_bounds.max == 2,
    ])
    error_message = "A preview plan no longer runs the reviewed baseline capacity."
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
      local.network_egress_mode == "public_ip",
      local.nat_mode == "none",
      local.assign_public_ip,
    ])
    error_message = "production-lean no longer derives the cost-capped egress posture (public_ip / no NAT) from profiles.tf."
  }

  # Task placement, same reasoning as the staging run: no NAT means the private
  # route tables have no default route at all, so the public tier is the only
  # one a task can pull an image from.
  assert {
    condition = alltrue([
      join(",", module.ecs.task_subnet_keys) ==
      "public/us-east-1a,public/us-east-1b,public/us-east-1c",
      !module.vpc.private_subnets_have_internet_route,
      local.ecs_task_subnet_tier == "public",
    ])
    error_message = "production-lean places ECS tasks somewhere other than the public subnets while running no NAT Gateway; those tasks have no route to ECR and the first apply cannot reach steady state."
  }

  assert {
    condition = alltrue([
      join(",", sort([for rule in module.vpc.ecs_sg_ingress : tostring(rule.port)])) == "8000,8080",
      alltrue([for rule in module.vpc.ecs_sg_ingress : length(rule.cidr_blocks) == 0]),
      alltrue([for rule in module.vpc.ecs_sg_ingress : rule.from_alb]),
    ])
    error_message = "The ECS task security group admits a CIDR or a port the ALB does not front; with tasks on public IPs that publishes an application port to the internet."
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

  # required_resources: credential_kms — the provider-credential envelope-
  # encryption CMK is provisioned in every cloud profile. A lean plan that
  # dropped it would run the AwsKmsEnvelopeCredentialCipher with no key.
  assert {
    condition     = length(module.kms_credentials) == 1
    error_message = "The production-lean plan does not provision the provider-credential envelope-encryption CMK."
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
      module.alb.backend_target_group_replacement_strategy == "create-before-destroy",
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

  # DEAD-LETTER BINDING. modules/sqs has always created one DLQ per consumer
  # role — they are the redrive targets of the role queues — but never
  # published them, so no task was told where to put a poison message. The
  # runtime's fallback was to re-publish it onto the queue it had just been
  # read from, where it was re-received, matched no handler and was deleted:
  # total silent loss. Every role that owns a queue must therefore also be
  # handed that queue's DLQ, and the two sets must be identical — a role with a
  # queue and no dead-letter destination is the exact configuration that loses
  # events.
  assert {
    condition = alltrue([
      join(",", module.ecs.runtime_service_dlq_roles["lean-worker"]) ==
      join(",", module.ecs.runtime_service_queue_roles["lean-worker"]),
      join(",", module.ecs.runtime_service_dlq_roles["lean-worker"]) ==
      "graph-writer,identity-worker,measurement-worker,stream-worker",
    ])
    error_message = "The lean-worker task is handed a role queue with no matching dead-letter queue; a poison message on that role has nowhere to go."
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
      local.network_egress_mode == "single_nat",
      local.nat_mode == "single",
      !local.assign_public_ip,
    ])
    error_message = "production-scale no longer derives the single-NAT egress posture from profiles.tf."
  }

  # The mirror image of the cost-capped placement: this profile pays for a NAT
  # Gateway, so the private route tables really do carry a default route and
  # tasks stay private with no public IP. A regression that moved every profile
  # to the public tier fails here.
  assert {
    condition = alltrue([
      join(",", module.ecs.task_subnet_keys) ==
      "private/us-east-1a,private/us-east-1b,private/us-east-1c",
      module.vpc.private_subnets_have_internet_route,
      local.ecs_task_subnet_tier == "private",
    ])
    error_message = "production-scale no longer keeps ECS tasks in the private subnets behind its NAT Gateway."
  }

  assert {
    condition = alltrue([
      length(module.msk) == 1,
      length(module.elasticache) == 1,
      length(module.neptune) == 1,
      length(module.kms_credentials) == 1,
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

  # Same dead-letter invariant on the dedicated shape: exactly the role the
  # service is named after, and nothing for a service that owns no queue.
  assert {
    condition = alltrue([
      join(",", module.ecs.runtime_service_dlq_roles["stream-worker"]) == "stream-worker",
      length(module.ecs.runtime_service_dlq_roles["maintenance"]) == 0,
    ])
    error_message = "A dedicated production-scale service is not bound to its own dead-letter queue."
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
      local.network_egress_mode == "ha_nat",
      local.nat_mode == "ha",
      !local.assign_public_ip,
    ])
    error_message = "enterprise-isolated no longer derives the HA-NAT egress posture from profiles.tf."
  }

  assert {
    condition = alltrue([
      join(",", module.ecs.task_subnet_keys) ==
      "private/us-east-1a,private/us-east-1b,private/us-east-1c",
      module.vpc.private_subnets_have_internet_route,
      local.ecs_task_subnet_tier == "private",
    ])
    error_message = "enterprise-isolated no longer keeps ECS tasks in the private subnets behind its per-AZ NAT Gateways."
  }

  assert {
    condition = alltrue([
      length(module.msk) == 1,
      length(module.elasticache) == 1,
      length(module.neptune) == 1,
      length(module.rds) == 0,
      length(module.kms_credentials) == 1,
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

# ---------------------------------------------------------------------------
# staging sleep against an APPLIED environment.
#
# Everything above plans against empty state, so every ECS service is a CREATE
# and `desired_count` is always whatever the configuration says. That is why
# the asleep run near the top of this file passed for months while
# `staging_state = "asleep"` did not actually stop the API: the backend service
# carried `lifecycle { ignore_changes = [desired_count] }`, which suppresses
# the attribute only AFTER create — precisely the case a create-only plan can
# never exercise.
#
# These two runs close that hole. The first APPLIES the awake shape (mocked, so
# no infrastructure is touched) and leaves state behind; the second plans the
# asleep shape against that state, which is an UPDATE. With desired_count
# ignored the planned value is the prior 1 and this fails; with it managed the
# plan really does say 0.
#
# They are last in the file on purpose: run blocks share one state, so an apply
# placed earlier would turn every later plan into a diff against staging.
# ---------------------------------------------------------------------------

run "staging_awake_applied" {
  command = apply

  # This apply run materialises the awake staging shape to verify the ECS
  # baseline (the staging_sleep_plan_against_applied run plans against it). The
  # credential-envelope CMK (modules/kms_credentials) is deliberately left OUT:
  # it carries lifecycle.prevent_destroy = true, and terraform test tears every
  # run-created resource down after the file — a prevent_destroy resource makes
  # that teardown fail ("Instance cannot be destroyed") even though the suite
  # reports all passes, and no terraform version lets override_resource or a
  # variable relax it. The apply run's assertions are ECS-only, and the six plan
  # runs below all assert length(module.kms_credentials) == 1, so CMK coverage
  # is unchanged. The production guard in modules/kms_credentials/main.tf stays
  # prevent_destroy = true — a real plan that would retire the CMK still fails
  # closed.
  variables {
    deployment_profile    = "staging"
    environment           = "staging"
    staging_state         = "awake"
    network_egress_mode   = null
    aurora_min_acu        = 0
    aurora_max_acu        = 2
    log_retention_days    = 3
    enable_credential_kms = false
  }

  # The baseline this sleeps FROM. Without it a multiplier stuck at 0 would
  # satisfy the sleep assertions below without ever having run anything.
  assert {
    condition = alltrue([
      module.ecs.backend_service_desired_count == 1,
      module.ecs.runtime_service_desired_counts["lean-worker"] == 1,
      module.ecs.backend_autoscaling_bounds.min == 1,
    ])
    error_message = "The applied awake staging environment is not at its reviewed baseline capacity."
  }
}

run "staging_sleep_plan_against_applied" {
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

  # desired_count must be a MANAGED attribute of the applied api service. This
  # is the clause an `ignore_changes = [desired_count]` regression fails, and
  # it is also exactly what .github/workflows/staging-lifecycle.yml reads out
  # of planned_values before it will apply a sleep.
  assert {
    condition     = module.ecs.backend_service_desired_count == 0
    error_message = "The asleep plan leaves the applied api service above zero tasks: desired_count is not reaching the service, so staging never sleeps and the api task runs 24/7."
  }

  # The workers must reach zero the same way, and the floor must collapse or
  # Application Auto Scaling clamps everything back up within a cooldown.
  assert {
    condition = alltrue([
      module.ecs.runtime_service_desired_counts["lean-worker"] == 0,
      module.ecs.backend_autoscaling_bounds.min == 0,
      local.runtime_service_settings["lean-worker"].autoscaling.min_capacity == 0,
    ])
    error_message = "The asleep plan leaves a worker running or an autoscaling floor above zero."
  }

  # Sleeping is a capacity change, not a shape change: the applied topology is
  # untouched and the reviewed ceiling still records the envelope to wake into.
  assert {
    condition = alltrue([
      join(",", keys(local.runtime_service_settings)) == "lean-worker",
      module.ecs.backend_autoscaling_bounds.max == 2,
      join(",", module.ecs.task_subnet_keys) ==
      "public/us-east-1a,public/us-east-1b,public/us-east-1c",
    ])
    error_message = "Sleeping staging changed its topology instead of only its capacity."
  }
}

# ---------------------------------------------------------------------------
# vpc_endpoints is a declared-but-unimplemented egress mode and must fail closed.
#
# modules/vpc_endpoints exists but the root never instantiates it, and the mode
# provisions no NAT and assigns no public IP. Left permissive it would place ECS
# tasks in private subnets with no route anywhere — ECR pulls fail with
# CannotPullContainerError and the deployment circuit-breaker rolls back. That is
# the exact defect the egress work was written to fix, so selecting the mode is a
# plan-time error rather than a silent degradation to `none`.
#
# This run block is the regression guard: delete the validation in variables.tf
# and this fails. Remove it only when the module is genuinely wired and priced.
# ---------------------------------------------------------------------------
run "vpc_endpoints_egress_mode_is_rejected" {
  command = plan

  variables {
    deployment_profile  = "production-lean"
    environment         = "production"
    network_egress_mode = "vpc_endpoints"
    aurora_min_acu      = 0.5
    aurora_max_acu      = 4
    log_retention_days  = 3
  }

  expect_failures = [var.network_egress_mode]
}
