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

variable "runtime_services" {
  type = map(object({
    roles         = list(string)
    cpu           = number
    memory        = number
    desired_count = number
    capacity_provider = object({
      base       = string
      base_count = number
      surge      = string
    })
    autoscaling = object({
      min_capacity         = number
      max_capacity         = number
      metric               = string
      cooldown_seconds     = number
      queue_depth_target   = optional(number)
      request_count_target = optional(number)
    })
  }))
  description = <<-EOT
    Non-API runtime SERVICES, derived from the selected profile's schema-v2
    `services:` map in config/runtime_deployment.yaml (see root profiles.tf).

    The unit here is one ECS service + one task definition, NOT one logical
    role: `roles` names the logical roles that single task hosts, which is one
    role in a `dedicated` profile and eight in a `consolidated` one. The map
    KEY is the AETHER_ROLE token the container boots with, so a consolidated
    entry is keyed `lean-worker` (an execution group in
    services/runtime/roles.py) rather than by any role it contains.

    The api service is absent by construction: it is served by the -backend
    service, the one load-bearing naming exception in the matrix.
  EOT
  validation {
    condition     = !contains(keys(var.runtime_services), "api") && !contains(keys(var.runtime_services), "all")
    error_message = "runtime_services must contain non-api runtime services only; api is served by the -backend service and `all` is the local single-process token, never deployable."
  }
  validation {
    # A service hosting no role would boot a task with an AETHER_ROLE that
    # expands to nothing: it would start, pass no work, and consume nothing.
    condition     = alltrue([for cfg in var.runtime_services : length(cfg.roles) > 0])
    error_message = "every runtime service must declare at least one logical role in `roles`."
  }
  validation {
    # `alb-request-count-per-target` needs a target group to measure, and no
    # non-api runtime service registers with the ALB — only the -backend
    # service does. Rejecting it here fails the plan loudly instead of
    # provisioning a scaling target that silently never scales.
    condition     = alltrue([for cfg in var.runtime_services : cfg.autoscaling.metric == "sqs-queue-depth"])
    error_message = "a non-api runtime service registers with no load balancer, so its autoscaling metric must be sqs-queue-depth."
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

# The backend (api) task's sizing, baseline and autoscaling envelope carry no
# defaults on purpose. They come from the api service in the schema-v2runtime
# matrix via the root's local.api_* values, and a default here would be a
# second source of truth for a number the matrix already states — exactly the
# divergence that let a production-scale plan run a lean-sized API.

variable "backend_cpu" {
  type        = number
  description = "CPU units for the backend task (config/runtime_deployment.yaml -> profiles.<p>.services.api.cpu)"
}

variable "backend_memory" {
  type        = number
  description = "Memory in MiB for the backend task (…services.api.memory)"
}

variable "backend_capacity_provider" {
  type = object({
    base       = string
    base_count = number
    surge      = string
  })
  description = <<-EOT
    Capacity providers for the backend service: `base_count` guaranteed tasks on
    `base`, everything above that floor on `surge`
    (…services.api.capacity_provider). The matrix pins api to FARGATE for both,
    because a Spot reclaim on the public request path is not worth the discount;
    scripts/release/check_delivery_topology.py enforces that as policy.
  EOT
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

variable "backend_desired_count" {
  type        = number
  description = <<-EOT
    Baseline task count for the backend service (…services.api.desired_count,
    already multiplied by the staging wake/sleep state). Distinct from
    backend_min_capacity, which is the autoscaling floor: the matrix declares
    both and they are equal today, but conflating them would silently redefine
    one of them the first time they diverge.
  EOT
}

variable "backend_min_capacity" {
  type        = number
  description = "Autoscaling floor for the backend service (…services.api.autoscaling.min_capacity)"
}

variable "backend_max_capacity" {
  type        = number
  description = "Autoscaling ceiling for the backend service (…services.api.autoscaling.max_capacity)"
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
