variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for ECS task network interfaces"
}

variable "ecs_sg_id" {
  type        = string
  description = "Security group ID for ECS tasks"
}

variable "ecr_backend_url" {
  type        = string
  description = "ECR repository URL for aether-backend"
}

variable "backend_image_digest" {
  type        = string
  description = "Immutable sha256 digest for the backend image used by API and runtime roles"
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.backend_image_digest))
    error_message = "backend_image_digest must be an immutable sha256 digest."
  }
}

variable "runtime_roles" {
  type = map(object({
    cpu           = number
    memory        = number
    desired_count = number
  }))
  description = <<-EOT
    Dedicated non-API runtime roles with per-role sizing, derived from the
    selected profile in config/runtime_deployment.yaml (see root profiles.tf).
    The api role is served by the -backend service; the local-only role all is
    forbidden.
  EOT
  validation {
    condition     = !contains(keys(var.runtime_roles), "api") && !contains(keys(var.runtime_roles), "all")
    error_message = "runtime_roles must contain dedicated workers only; api/all are forbidden."
  }
}

variable "ecr_ml_url" {
  type        = string
  description = "ECR repository URL for aether-ml-serving (unused when enable_dedicated_ml = false)"
  default     = ""
}

variable "ml_image_digest" {
  type        = string
  description = "Immutable sha256 digest for the optional ML serving image (empty string when enable_dedicated_ml = false)"
  default     = ""
  # Profiles without dedicated ML have no ML image to pin, so the empty string
  # is accepted; any non-empty value must still be an immutable digest.
  validation {
    condition     = var.ml_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.ml_image_digest))
    error_message = "ml_image_digest must be an immutable sha256 digest."
  }
}

variable "alb_backend_tg_arn" {
  type        = string
  description = "ARN of the ALB target group for the backend service"
}

variable "alb_ml_tg_arn" {
  type        = string
  description = "ARN of the ALB target group for ml-serving (empty string when enable_dedicated_ml = false)"
  default     = ""
}

variable "secret_arns" {
  type        = map(string)
  description = "Map of secret name to Secrets Manager ARN"
}

variable "companion_secret_arns" {
  type        = map(string)
  description = "ARNs of companion *-previous secrets populated by the rotation Lambda (jwt-secret-previous, byok-encryption-key-previous)"
  default     = {}
}

variable "backend_cpu" {
  type        = number
  description = "CPU units for the backend task"
  default     = 1024
}

variable "backend_memory" {
  type        = number
  description = "Memory in MiB for the backend task"
  default     = 2048
}

variable "ml_cpu" {
  type        = number
  description = "CPU units for the ml-serving task"
  default     = 2048
}

variable "ml_memory" {
  type        = number
  description = "Memory in MiB for the ml-serving task"
  default     = 4096
}

variable "backend_min_capacity" {
  type        = number
  description = "Minimum running tasks for the backend service"
  default     = 1
}

variable "backend_max_capacity" {
  type        = number
  description = "Maximum running tasks for the backend service"
  default     = 10
}

variable "ml_min_capacity" {
  type        = number
  description = "Minimum running tasks for ml-serving"
  default     = 1
}

variable "ml_max_capacity" {
  type        = number
  description = "Maximum running tasks for ml-serving"
  default     = 10
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log group retention in days"
  default     = 30
}

variable "redis_host" {
  type        = string
  description = "ElastiCache Redis primary endpoint hostname (empty string = DynamoDB cache backend)"
  default     = ""
}

variable "redis_port" {
  type        = number
  description = "ElastiCache Redis port"
  default     = 6379
}

variable "kafka_bootstrap_servers" {
  type        = string
  description = "MSK Kafka TLS bootstrap broker string (empty string = SQS event broker)"
  default     = ""
}

variable "sqs_queue_url" {
  type        = string
  description = "SQS events queue URL (used when EVENT_BROKER=sns_sqs; empty string falls back to Kafka)"
  default     = ""
}

variable "dynamodb_cache_table" {
  type        = string
  description = "DynamoDB table name for the shared cache (used when non-empty; falls back to Redis)"
  default     = ""
}

variable "sqs_queue_arn" {
  type        = string
  description = "SQS events queue ARN (used for IAM policy scoping; empty string = no SQS permissions)"
  default     = ""
}

variable "sqs_role_queue_urls" {
  type        = map(string)
  description = "Consumer role -> dedicated SNS-subscribed queue URL. Consumer roles receive their own queue; other roles fall back to the shared events queue."
  default     = {}
}

variable "sqs_role_queue_arns" {
  type        = map(string)
  description = "Consumer role -> dedicated queue ARN (IAM policy scoping)"
  default     = {}
}

variable "sns_topic_arn" {
  type        = string
  description = "SNS fanout topic ARN. When set with the SQS broker, producers publish to SNS so every per-role queue receives the event (empty string = direct SQS publish)."
  default     = ""
}

variable "dynamodb_cache_table_arn" {
  type        = string
  description = "DynamoDB cache table ARN (used for IAM policy scoping; empty string = no DynamoDB permissions)"
  default     = ""
}

variable "neptune_endpoint" {
  type        = string
  description = "Neptune cluster writer endpoint (empty string = in-memory fallback)"
  default     = ""
}

variable "ml_serving_url" {
  type        = string
  description = "Internal URL for the ML serving service (empty string = unreachable fallback)"
  default     = ""
}

variable "use_fargate_spot" {
  type        = bool
  description = "Use Fargate Spot capacity for the backend service (E2). 4:1 Spot:on-demand ratio; base on-demand task ensures one guaranteed task survives Spot reclamation."
  default     = false
}

variable "ml_serving_inline" {
  type        = bool
  description = "When true, ML serving is handled in-process by the backend (ML_SERVING_INLINE=true). Advertises the runtime mode to the application only; whether the dedicated aether-ml-serving resources exist is controlled by enable_dedicated_ml."
  default     = false
}

# --------------------------------------------------------------------------
# Deployment profile gating
#
# Resource toggles and backend selectors derived from var.deployment_profile
# in the root module (see profiles.tf and config/deployment_profiles.yaml).
# Everything defaults to the lean profile so an un-wired caller never
# provisions a cost-gated component by accident.
# --------------------------------------------------------------------------

variable "enable_elasticache" {
  type        = bool
  description = "ElastiCache Redis is part of the profile. Gates the REDIS_PASSWORD secret mapping and the Redis AUTH token read permission; without it the ElastiCache module can be deleted outright."
  default     = false
}

variable "enable_msk" {
  type        = bool
  description = "MSK is part of the profile. Kafka broker configuration is only injected into tasks when this is true and event_broker = kafka."
  default     = false
}

variable "enable_neptune" {
  type        = bool
  description = "Neptune is part of the profile. Gates the neptune-db IAM statement on the task role."
  default     = false
}

variable "enable_dedicated_ml" {
  type        = bool
  description = "Create the dedicated aether-ml-serving log group, task definition, service and autoscaling. When false those resources do not exist at all (they are not merely scaled to zero)."
  default     = false
}

variable "event_broker" {
  type        = string
  description = "Explicit event broker selection (EVENT_BROKER). Replaces the previous 'sqs_queue_url is non-empty' sentinel."
  default     = "sns_sqs"
  validation {
    condition     = contains(["sns_sqs", "kafka"], var.event_broker)
    error_message = "event_broker must be one of: sns_sqs, kafka."
  }
}

variable "cache_backend" {
  type        = string
  description = "Explicit cache backend selection (CACHE_BACKEND). Replaces the previous 'dynamodb_cache_table is non-empty' sentinel."
  default     = "dynamodb"
  validation {
    condition     = contains(["dynamodb", "redis"], var.cache_backend)
    error_message = "cache_backend must be one of: dynamodb, redis."
  }
}

variable "graph_backend" {
  type        = string
  description = "Explicit graph backend selection (GRAPH_BACKEND). NEPTUNE_ENDPOINT is only injected when this is neptune."
  default     = "postgres"
  validation {
    condition     = contains(["postgres", "neptune"], var.graph_backend)
    error_message = "graph_backend must be one of: postgres, neptune."
  }
}

variable "analytics_backend" {
  type        = string
  description = "Explicit analytics backend selection (ANALYTICS_BACKEND)."
  default     = "postgres"
  validation {
    condition     = contains(["postgres", "clickhouse"], var.analytics_backend)
    error_message = "analytics_backend must be one of: postgres, clickhouse."
  }
}

variable "assign_public_ip" {
  type        = bool
  description = "Assign a public IP to every task ENI. Required when tasks run in public subnets with no NAT gateway; false for private subnets reaching AWS through NAT or VPC endpoints."
  default     = false
}
