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
  description = "ElastiCache Redis primary endpoint hostname"
}

variable "redis_port" {
  type        = number
  description = "ElastiCache Redis port"
  default     = 6379
}

variable "kafka_bootstrap_servers" {
  type        = string
  description = "MSK Kafka TLS bootstrap broker string"
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
