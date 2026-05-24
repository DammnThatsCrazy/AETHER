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
  description = "ECS aether-app service name"
}

variable "ml_service_name" {
  type        = string
  description = "ECS aether-ml service name"
}

# Replaces rds_identifier — Aurora Serverless v2 uses cluster-level metrics.
# Optional: leave empty during the RDS→Aurora migration; alarm/widgets skip
# when unset so the module continues to plan cleanly against an RDS-only root.
variable "aurora_cluster_id" {
  type        = string
  description = "Aurora Serverless v2 cluster identifier (used in CloudWatch alarm dimensions). Empty string disables Aurora alarms/widgets."
  default     = ""
}

variable "aurora_max_acu" {
  type        = number
  description = "Aurora max ACU configured on the cluster (used to compute the max-ACU alarm threshold)"
  default     = 4
}

variable "alb_arn_suffix" {
  type        = string
  description = "ALB ARN suffix (used in CloudWatch alarm dimensions)"
}

variable "alert_email" {
  type        = string
  description = "Email address for alarm notifications"
}

# Serverless endpoint names for dashboard widgets (M4, M5, M8).
variable "sagemaker_endpoint_names" {
  type        = list(string)
  description = "SageMaker Serverless endpoint names to show per-model invocations on the dashboard"
  default = [
    "aether-identity-resolution-serverless",
    "aether-journey-prediction-serverless",
    "aether-anomaly-detection-serverless",
  ]
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention in days"
  default     = 3
}

variable "log_archive_bucket" {
  type        = string
  description = "S3 bucket name for long-term log archive (Vector → S3 Parquet). Created by this module if empty string."
  default     = ""
}
