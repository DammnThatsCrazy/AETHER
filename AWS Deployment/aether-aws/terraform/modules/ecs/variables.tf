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

variable "ecr_ml_url" {
  type        = string
  description = "ECR repository URL for aether-ml-serving"
}

variable "alb_backend_tg_arn" {
  type        = string
  description = "ARN of the ALB target group for the backend service"
}

variable "alb_ml_tg_arn" {
  type        = string
  description = "ARN of the ALB target group for ml-serving"
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
