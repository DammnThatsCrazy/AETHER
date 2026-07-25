# ============================================================================
# AETHER — Root Module Variables
# ============================================================================

variable "deployment_profile" {
  type        = string
  description = "Aether deployment profile driving cost/resource toggles (see config/deployment_profiles.yaml)."
  default     = "production-lean"

  validation {
    condition     = contains(["staging", "production-lean", "production-scale", "enterprise-isolated"], var.deployment_profile)
    error_message = "Invalid Aether deployment profile."
  }
}

# No default: every plan must pin the exact digest approved by the release
# manifest. terraform-promote.yml passes these as explicit -var inputs.
variable "backend_image_digest" {
  type        = string
  description = "Immutable backend image digest selected by the release manifest"
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.backend_image_digest))
    error_message = "backend_image_digest must be an immutable sha256 digest."
  }
}

variable "ml_image_digest" {
  type        = string
  description = "Immutable optional ML serving image digest selected by the release manifest"
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.ml_image_digest))
    error_message = "ml_image_digest must be an immutable sha256 digest."
  }
}

variable "environment" {
  type        = string
  description = "Deployment environment (production, staging, dev)"
  default     = "production"

  validation {
    condition     = contains(["production", "staging", "dev"], var.environment)
    error_message = "environment must be one of: production, staging, dev."
  }
}

# The staging wake/sleep switch. Deliberately a root variable rather than a
# tfvars constant: the whole point is that an operator or a schedule flips it
# between applies without editing reviewed configuration.
variable "staging_state" {
  type        = string
  description = <<-EOT
    Lifecycle state for a profile that declares one, resolved against
    `profiles.<profile>.staging_state.states` in
    config/runtime_deployment.yaml. `asleep` multiplies every declared
    desired_count and autoscaling bound by zero, so a sleeping environment owns
    exactly the same services and the same roles as an awake one and wakes by
    flipping this single input rather than by planning a differently-shaped
    topology. Profiles that declare no `staging_state` block (today: everything
    except staging) ignore it entirely — the multiplier falls back to 1.
  EOT
  default     = "awake"

  validation {
    # The two states config/runtime_deployment.yaml declares. Restricting them
    # here fails on a typo at plan time; without it `try(...)` in profiles.tf
    # would silently fall back to the multiplier 1 and an operator who typed
    # "sleep" would be told the environment is asleep while it kept running.
    condition     = contains(["awake", "asleep"], var.staging_state)
    error_message = "staging_state must be one of: awake, asleep."
  }
}

variable "aws_region" {
  type        = string
  description = "AWS region to deploy resources into"
  default     = "us-east-1"
}

variable "project" {
  type        = string
  description = "Project name used for resource naming and tagging"
  default     = "AETHER"
}

# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC"
  default     = "10.0.0.0/16"
}

# Replaces the former enable_nat_gateway_ha bool, which could only choose
# between one NAT and three and had no way to express "no NAT at all" — the
# posture every cost-capped profile actually wants.
variable "network_egress_mode" {
  type        = string
  description = <<-EOT
    Outbound egress topology for ECS tasks. null = use the deployment profile
    default (staging and production-lean: public_ip; production-scale:
    single_nat; enterprise-isolated: ha_nat). Setting this to a NAT mode on a
    cost-capped profile is the explicit opt-in that the
    `nat_gateway_unless_explicit` policy in config/deployment_profiles.yaml
    requires. vpc_endpoints and none both provision zero NAT Gateways.
  EOT
  default     = null

  validation {
    condition = var.network_egress_mode == null ? true : contains(
      ["public_ip", "single_nat", "ha_nat", "vpc_endpoints", "none"],
      var.network_egress_mode,
    )
    error_message = "network_egress_mode must be one of: public_ip, single_nat, ha_nat, vpc_endpoints, none."
  }

  # `vpc_endpoints` is a declared mode with no implementation: modules/vpc_endpoints
  # exists but the root never instantiates it, and this mode provisions no NAT and
  # assigns no public IP. Selecting it would therefore put tasks in private subnets
  # with no route to anywhere — ECR pulls fail with CannotPullContainerError, the
  # deployment circuit-breaker rolls back, and the service never reaches steady
  # state. That is precisely the defect this egress work was written to fix, so the
  # mode fails at plan time rather than silently degrading to `none`.
  #
  # To implement it: instantiate modules/vpc_endpoints for the interface endpoints
  # the runtime actually needs (ecr.api, ecr.dkr, s3 gateway, secretsmanager, logs,
  # sqs, sns, dynamodb gateway), price them in config/aws_price_book.yaml — interface
  # endpoints are ~$7.30/endpoint/month each, so this is NOT automatically cheaper
  # than a NAT Gateway and needs the comparison written down — then delete this block.
  validation {
    condition     = var.network_egress_mode != "vpc_endpoints"
    error_message = <<-EOT
      network_egress_mode = "vpc_endpoints" is declared but not implemented: the
      root never instantiates modules/vpc_endpoints, so this mode would leave ECS
      tasks in private subnets with no egress and no endpoints. Use public_ip
      (zero NAT cost) or single_nat/ha_nat. See variables.tf for what implementing
      it requires.
    EOT
  }
}

# --------------------------------------------------------------------------
# Aurora Serverless v2 (E3 — replaces RDS as the active database)
# --------------------------------------------------------------------------

variable "aurora_min_acu" {
  type        = number
  description = "Aurora Serverless v2 minimum capacity units. 0 = auto-pause (staging); 0.5 = always warm (prod)."
  default     = 0.5
}

variable "aurora_max_acu" {
  type        = number
  description = "Aurora Serverless v2 maximum capacity units."
  default     = 4
}

variable "aurora_backup_retention_days" {
  type        = number
  description = "Automated backup retention in days."
  default     = 7
}

# --------------------------------------------------------------------------
# RDS Postgres (kept for rollback safety — decommission after E3 validation)
# --------------------------------------------------------------------------

variable "db_instance_class" {
  type        = string
  description = "RDS instance class"
  default     = "db.t3.medium"
}

variable "db_name" {
  type        = string
  description = "Initial database name"
  default     = "aether"
}

variable "db_multi_az" {
  type        = bool
  description = "Enable Multi-AZ for RDS (recommended true in production)"
  default     = true
}

variable "db_allocated_storage" {
  type        = number
  description = "Initial RDS allocated storage in GiB"
  default     = 100
}

variable "db_max_allocated_storage" {
  type        = number
  description = "Maximum storage for RDS autoscaling in GiB"
  default     = 500
}

# --------------------------------------------------------------------------
# ElastiCache Redis
# --------------------------------------------------------------------------

variable "redis_node_type" {
  type        = string
  description = "ElastiCache Redis node type"
  default     = "cache.t3.micro"
}

variable "redis_num_cache_nodes" {
  type        = number
  description = "Number of cache nodes in the Redis cluster"
  default     = 1
}

# --------------------------------------------------------------------------
# MSK Kafka
# --------------------------------------------------------------------------

variable "msk_broker_instance_type" {
  type        = string
  description = "MSK broker instance type"
  default     = "kafka.m5.large"
}

variable "msk_kafka_version" {
  type        = string
  description = "Apache Kafka version for MSK"
  default     = "3.5.1"
}

variable "msk_broker_count" {
  type        = number
  description = "Number of MSK broker nodes (must be a multiple of the number of AZs)"
  default     = 3
}

variable "msk_broker_volume_size" {
  type        = number
  description = "EBS volume size in GiB per MSK broker"
  default     = 100
}

# --------------------------------------------------------------------------
# ECS / Compute
# --------------------------------------------------------------------------

# The aether-backend (api) task's sizing, baseline and autoscaling envelope are
# NOT variables. They are read from the api service in
# config/runtime_deployment.yaml by profiles.tf (local.api_cpu, local.api_memory,
# local.api_desired_count, local.api_min_capacity, local.api_max_capacity) and
# passed to modules/ecs from there. The former ecs_backend_cpu /
# ecs_backend_memory / ecs_backend_min_capacity / ecs_backend_max_capacity
# variables were a second, silently divergent source of truth for the same four
# numbers: their defaults (1024/2048/1/10) disagreed with the matrix's
# production-scale api (2048/4096/3/12) and no tfvars file set them, so a scale
# apply quietly ran the reviewed capacity of a lean one. Only the ML serving
# task, which the matrix does not describe, is still sized by variable.

variable "ecs_ml_cpu" {
  type        = number
  description = "CPU units for the aether-ml-serving task"
  default     = 2048
}

variable "ecs_ml_memory" {
  type        = number
  description = "Memory in MiB for the aether-ml-serving task"
  default     = 4096
}

variable "ecs_ml_min_capacity" {
  type        = number
  description = "Minimum number of aether-ml-serving tasks"
  default     = 1
}

variable "ecs_ml_max_capacity" {
  type        = number
  description = "Maximum number of aether-ml-serving tasks for auto-scaling"
  default     = 10
}

# --------------------------------------------------------------------------
# ALB / HTTPS
# --------------------------------------------------------------------------

variable "acm_certificate_arn" {
  type        = string
  description = "ARN of the ACM certificate for the HTTPS listener (must be in the same region)"
}

variable "domain_name" {
  type        = string
  description = "Primary domain name for the API (e.g. api.aether.io)"
}

# --------------------------------------------------------------------------
# Neptune
# --------------------------------------------------------------------------

variable "neptune_instance_class" {
  type        = string
  description = "Neptune DB instance class"
  default     = "db.r6g.large"
}

variable "neptune_cluster_size" {
  type        = number
  description = "Number of Neptune cluster instances (1 writer + N-1 readers)"
  default     = 1
}

# --------------------------------------------------------------------------
# Monitoring
# --------------------------------------------------------------------------

variable "alert_email" {
  type        = string
  description = "Email address to receive CloudWatch alarm notifications"
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention period in days (INFO/DEBUG ship to S3 via Vector; keep only WARN+ in CW)"
  default     = 3
}

# --------------------------------------------------------------------------
# Auth0
# --------------------------------------------------------------------------

# The Auth0 tenant domain and the Terraform M2M application's client id and
# secret are NOT declared here, on purpose. A root variable is reproduced in
# full in `terraform show -json` output regardless of `sensitive = true`, so
# declaring the secret here put it in clear text in every plan artifact. The
# auth0 provider takes AUTH0_DOMAIN / AUTH0_CLIENT_ID / AUTH0_CLIENT_SECRET
# from its own environment, which the CI runner exports; TF_VAR_auth0_* names
# are no longer read by anything. See modules/auth0/main.tf.
#
# Do not "restore for convenience": there is no way to declare a root variable
# that a plan JSON will not contain.

variable "auth0_api_audience" {
  type        = string
  description = "Audience identifier for the AETHER API resource server"
  default     = "https://api.aether.io"
}

variable "aether_app_url" {
  type        = string
  description = "Public URL of the Aether customer app (e.g. https://app.aether.io)"
}

variable "kyber_app_url" {
  type        = string
  description = "Public URL of the Kyber operator console (e.g. https://kyber.aether.io)"
}
