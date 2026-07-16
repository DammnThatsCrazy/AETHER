# Provider-mocked profile plan used by the GitHub PR matrix.
#
# This exercises the real root module and provider schemas without contacting
# tenant infrastructure. Environment-authoritative plans remain a separate,
# credential-gated workflow job.

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-1a", "us-east-1b", "us-east-1c"]
    }
  }
}

mock_provider "random" {}
mock_provider "auth0" {}
mock_provider "archive" {}

run "profile_configuration_plan" {
  command = plan

  assert {
    condition = contains(
      ["staging", "production-lean", "production-scale", "enterprise-isolated"],
      var.deployment_profile,
    )
    error_message = "The selected deployment profile is not deployable."
  }

  assert {
    condition = var.deployment_profile != "staging" || (
      var.enable_nat_gateway_ha == false &&
      var.aurora_min_acu == 0 &&
      var.aurora_max_acu == 2 &&
      var.log_retention_days == 3
    )
    error_message = "The staging tfvars no longer match the reviewed capacity profile."
  }

  assert {
    condition = var.deployment_profile != "production-lean" || (
      var.enable_nat_gateway_ha == false &&
      var.aurora_min_acu == 0.5 &&
      var.aurora_max_acu == 4 &&
      var.log_retention_days == 3 &&
      alltrue([
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
    )
    error_message = "The production-lean tfvars or forbidden-resource toggles changed."
  }

  assert {
    condition = var.deployment_profile != "production-scale" || (
      var.enable_nat_gateway_ha == true &&
      var.aurora_min_acu == 1 &&
      var.aurora_max_acu == 8 &&
      var.log_retention_days == 7
    )
    error_message = "The production-scale tfvars no longer match the reviewed capacity profile."
  }

  assert {
    condition = var.deployment_profile != "enterprise-isolated" || (
      var.enable_nat_gateway_ha == true &&
      var.aurora_min_acu == 2 &&
      var.aurora_max_acu == 16 &&
      var.db_multi_az == true &&
      var.log_retention_days == 30
    )
    error_message = "The enterprise-isolated tfvars no longer match the reviewed capacity profile."
  }

  assert {
    condition = contains(["production-scale", "enterprise-isolated"], var.deployment_profile) ? (
      local.graph_backend == "neptune" &&
      local.cache_backend == "redis" &&
      local.event_broker == "kafka"
      ) : (
      local.graph_backend == "postgres" &&
      local.cache_backend == "dynamodb" &&
      local.event_broker == "sns_sqs"
    )
    error_message = "The profile backend selectors no longer match the deployment policy."
  }
}
