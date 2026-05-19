variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name"
}

variable "ecs_cluster_name" {
  type        = string
  description = "ECS cluster name (used in CloudWatch alarm dimensions)"
}

variable "backend_service_name" {
  type        = string
  description = "ECS backend service name"
}

variable "ml_service_name" {
  type        = string
  description = "ECS ml-serving service name"
}

variable "rds_identifier" {
  type        = string
  description = "RDS instance identifier"
}

variable "alb_arn_suffix" {
  type        = string
  description = "ALB ARN suffix (used in CloudWatch alarm dimensions)"
}

variable "alert_email" {
  type        = string
  description = "Email address for alarm notifications"
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention in days"
  default     = 30
}
