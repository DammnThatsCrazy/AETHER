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

variable "environment" {
  type        = string
  description = "Deployment environment (production, staging, dev)"
  default     = "production"

  validation {
    condition     = contains(["production", "staging", "dev"], var.environment)
    error_message = "environment must be one of: production, staging, dev."
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

variable "enable_nat_gateway_ha" {
  type        = bool
  description = "When true, provision one NAT Gateway per AZ; when false, use a single shared NAT (lower cost)"
  default     = false
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

variable "ecs_backend_cpu" {
  type        = number
  description = "CPU units (1024 = 1 vCPU) for the aether-backend task"
  default     = 1024
}

variable "ecs_backend_memory" {
  type        = number
  description = "Memory in MiB for the aether-backend task"
  default     = 2048
}

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

variable "ecs_backend_min_capacity" {
  type        = number
  description = "Minimum number of aether-backend tasks"
  default     = 1
}

variable "ecs_backend_max_capacity" {
  type        = number
  description = "Maximum number of aether-backend tasks for auto-scaling"
  default     = 10
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

variable "auth0_domain" {
  type        = string
  description = "Auth0 tenant domain (e.g. your-tenant.auth0.com)"
}

variable "auth0_management_client_id" {
  type        = string
  description = "Client ID of the Terraform M2M application in Auth0"
  sensitive   = true
}

variable "auth0_management_client_secret" {
  type        = string
  description = "Client secret of the Terraform M2M application in Auth0"
  sensitive   = true
}

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
