# Provider-mocked plan proving the provider-credential envelope-encryption CMK
# (module.kms_credentials) is planned for every deployable profile.
#
# Mirrors tests/profile_plan.tftest.hcl: the real root module and provider
# schemas are exercised with no AWS credentials and no -var-file. Every run
# block is `command = plan`, sets network_egress_mode = null so the profile
# derivation is what runs, and pins the same capacity scalars the CI job would
# auto-load from profiles/<profile>.tfvars.
#
# Cardinality assertions read the planned module graph
# (length(module.kms_credentials)), not the local that produced it, so a toggle
# that stops driving the module's count is caught rather than passed. The alias
# name is a configuration value (not a computed attribute), so it is known at
# plan and asserts that the module named the key per convention.

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-1a", "us-east-1b", "us-east-1c"]
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

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
# staging — release rehearsal. Credential encryption is required here too.
# ---------------------------------------------------------------------------

run "staging_credential_kms_planned" {
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
    condition = alltrue([
      local.enable_credential_kms,
      length(module.kms_credentials) == 1,
      module.kms_credentials[0].alias_name == "alias/aether-staging-provider-credentials",
    ])
    error_message = "The staging plan does not provision the provider-credential envelope-encryption CMK."
  }
}

# ---------------------------------------------------------------------------
# production-lean — founding-tenant target and cost-policy subject. A CMK is
# cheap and explicitly allowed; it must be present here.
# ---------------------------------------------------------------------------

run "production_lean_credential_kms_planned" {
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
      local.enable_credential_kms,
      length(module.kms_credentials) == 1,
      module.kms_credentials[0].alias_name == "alias/aether-production-provider-credentials",
    ])
    error_message = "The production-lean plan does not provision the provider-credential envelope-encryption CMK."
  }
}

# ---------------------------------------------------------------------------
# production-scale
# ---------------------------------------------------------------------------

run "production_scale_credential_kms_planned" {
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
      local.enable_credential_kms,
      length(module.kms_credentials) == 1,
      module.kms_credentials[0].alias_name == "alias/aether-production-provider-credentials",
    ])
    error_message = "The production-scale plan does not provision the provider-credential envelope-encryption CMK."
  }
}

# ---------------------------------------------------------------------------
# enterprise-isolated
# ---------------------------------------------------------------------------

run "enterprise_isolated_credential_kms_planned" {
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
      local.enable_credential_kms,
      length(module.kms_credentials) == 1,
      module.kms_credentials[0].alias_name == "alias/aether-production-provider-credentials",
    ])
    error_message = "The enterprise-isolated plan does not provision the provider-credential envelope-encryption CMK."
  }
}
