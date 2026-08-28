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
  description = "ECS aether-ml service name (empty string when enable_dedicated_ml = false)"
  default     = ""
}

# Replaces rds_identifier — Aurora Serverless v2 uses cluster-level metrics.
# Optional: leave empty during the RDS→Aurora migration; alarm/widgets skip
# when unset so the module continues to plan cleanly against an RDS-only root.
variable "aurora_cluster_id" {
  type        = string
  description = "Aurora Serverless v2 cluster identifier (used in CloudWatch alarm dimensions). Empty string disables Aurora alarms/widgets."
  default     = ""
}

variable "enable_aurora_observability" {
  type        = bool
  description = "Whether Aurora alarms and dashboard widgets are present. This must be a static profile decision, not one inferred from a resource-derived cluster identifier."
  default     = false
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

# When populated, the dashboard renders one read-throttle and one write-throttle
# widget per table with an explicit TableName dimension. When empty, the
# dashboard falls back to a SEARCH-based metric math expression that aggregates
# throttle events across all DynamoDB tables in the account. Both paths surface
# real data — the explicit per-table path is preferred when the set of tables
# is known so individual hot tables stand out in the graph.
variable "dynamodb_table_names" {
  type        = list(string)
  description = "Optional list of DynamoDB table names to chart per-table throttle widgets for. Empty list = aggregate via SEARCH."
  default     = []
}

# --------------------------------------------------------------------------
# Deployment profile gating
#
# Mirrors the toggles in modules/ecs. Alarms for a cost-gated component only
# exist when the profile actually provisions that component, and alarms for
# the lean replacements (DynamoDB cache, SQS) only exist once the caller
# passes the corresponding identifier. Everything defaults to the lean
# profile, so an un-wired caller never creates an alarm for a resource that
# does not exist.
# --------------------------------------------------------------------------

variable "enable_elasticache" {
  type        = bool
  description = "ElastiCache Redis is part of the profile. Gates the Redis memory-pressure alarm."
  default     = false
}

variable "enable_msk" {
  type        = bool
  description = "MSK is part of the profile. Gates the Kafka offline-partitions alarm."
  default     = false
}

variable "enable_neptune" {
  type        = bool
  description = "Neptune is part of the profile. Gates the Neptune CPU alarm."
  default     = false
}

variable "enable_dedicated_ml" {
  type        = bool
  description = "The dedicated aether-ml-serving ECS service exists. Gates its dashboard widget; the ML drift alarm is independent of it because drift is published by the nightly Lambda in every profile."
  default     = false
}

variable "elasticache_replication_group_id" {
  type        = string
  description = "ElastiCache replication group ID for the Redis alarm. Empty string skips the alarm even when enable_elasticache is true."
  default     = ""
}

variable "msk_cluster_name" {
  type        = string
  description = "MSK cluster name for the Kafka alarm. Empty string skips the alarm even when enable_msk is true."
  default     = ""
}

variable "neptune_cluster_id" {
  type        = string
  description = "Neptune cluster identifier for the Neptune alarm. Empty string skips the alarm even when enable_neptune is true."
  default     = ""
}

variable "dynamodb_cache_table_name" {
  type        = string
  description = "DynamoDB cache table name (the lean profile's ElastiCache replacement). Empty string disables the cache throttle alarm."
  default     = ""
}

variable "sqs_queue_name" {
  type        = string
  description = "Primary SQS events queue NAME (not URL/ARN — CloudWatch uses the QueueName dimension). Empty string disables the queue depth and oldest-message-age alarms."
  default     = ""
}

variable "sqs_dlq_name" {
  type        = string
  description = "SQS dead-letter queue NAME. Empty string disables the DLQ depth alarm."
  default     = ""
}

variable "sqs_queue_depth_threshold" {
  type        = number
  description = "Visible-message count above which the SQS backlog alarm fires"
  default     = 1000
}

variable "sqs_oldest_message_age_threshold" {
  type        = number
  description = "Age in seconds of the oldest queued message above which the SQS staleness alarm fires"
  default     = 900
}

variable "runtime_service_log_groups" {
  type        = map(string)
  description = <<-EOT
    Runtime service key -> CloudWatch log group name for that service's tasks.
    Used to turn the supervisor's per-role failure line into a metric and an
    alarm. Empty map = no runtime-role health alarm.
  EOT
  default     = {}
}
