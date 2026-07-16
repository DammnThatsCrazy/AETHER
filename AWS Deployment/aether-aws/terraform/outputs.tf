# ============================================================================
# AETHER — Root Outputs
# ============================================================================

# --------------------------------------------------------------------------
# ALB / API entry point
# --------------------------------------------------------------------------

output "alb_dns" {
  description = "DNS name of the Application Load Balancer"
  value       = module.alb.alb_dns_name
}

output "backend_url" {
  description = "HTTPS URL for the AETHER backend API"
  value       = "https://${var.domain_name}"
}

# --------------------------------------------------------------------------
# ECR
# --------------------------------------------------------------------------

output "ecr_urls" {
  description = "Map of ECR repository URLs keyed by service name"
  value       = module.ecr.repository_urls
}

# --------------------------------------------------------------------------
# Data stores
# --------------------------------------------------------------------------

output "rds_endpoint" {
  description = "RDS Postgres endpoint address"
  value       = module.rds.endpoint
}

output "rds_port" {
  description = "RDS Postgres port"
  value       = module.rds.port
}

output "rds_db_name" {
  description = "RDS initial database name"
  value       = module.rds.db_name
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = module.elasticache.primary_endpoint
}

output "kafka_brokers" {
  description = "MSK TLS bootstrap broker endpoints"
  value       = module.msk.bootstrap_brokers_tls
}

output "sqs_events_queue_url" {
  description = "SQS events queue URL (E1 replacement for MSK Kafka)"
  value       = module.sqs.queue_url
}

output "sqs_fanout_topic_arn" {
  description = "SNS fanout topic ARN (E1)"
  value       = module.sqs.fanout_topic_arn
}

output "dynamodb_cache_table_name" {
  description = "DynamoDB cache table name (E1 replacement for ElastiCache)"
  value       = module.dynamodb_cache.table_name
}

output "neptune_endpoint" {
  description = "Neptune cluster writer endpoint"
  value       = module.neptune.cluster_endpoint
}

output "neptune_reader_endpoint" {
  description = "Neptune cluster reader endpoint"
  value       = module.neptune.reader_endpoint
}

# --------------------------------------------------------------------------
# ECS
# --------------------------------------------------------------------------

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "ecs_backend_service_name" {
  description = "ECS service name for the backend"
  value       = module.ecs.backend_service_name
}

output "ecs_runtime_role_service_names" {
  description = "ECS services keyed by canonical dedicated runtime role"
  value       = module.ecs.runtime_role_service_names
}

output "ecs_ml_service_name" {
  description = "ECS service name for ml-serving"
  value       = module.ecs.ml_service_name
}

# --------------------------------------------------------------------------
# Secrets Manager ARNs (no values exposed)
# --------------------------------------------------------------------------

output "secret_arns" {
  description = "Map of Secrets Manager secret ARNs — inject values manually post-deploy"
  value       = module.secrets.secret_arns
}

# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------

output "vpc_id" {
  description = "ID of the AETHER VPC"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "IDs of private subnets (ECS tasks)"
  value       = module.vpc.private_subnet_ids
}

output "isolated_subnet_ids" {
  description = "IDs of isolated subnets (data stores)"
  value       = module.vpc.isolated_subnet_ids
}

# --------------------------------------------------------------------------
# Monitoring
# --------------------------------------------------------------------------

output "cloudwatch_dashboard_url" {
  description = "URL to the AETHER-Production CloudWatch dashboard"
  value       = module.monitoring.dashboard_url
}

output "sns_alert_topic_arn" {
  description = "ARN of the SNS topic used for CloudWatch alarms"
  value       = module.monitoring.sns_topic_arn
}

output "log_archive_bucket" {
  description = "S3 bucket used for long-term log archive and drift reference data"
  value       = module.monitoring.log_archive_bucket
}

# --------------------------------------------------------------------------
# ML Drift Lambda
# --------------------------------------------------------------------------

output "drift_lambda_arn" {
  description = "ARN of the nightly ML drift Lambda"
  value       = module.ml_drift_lambda.lambda_arn
}

output "drift_lambda_function_name" {
  description = "Function name of the nightly ML drift Lambda"
  value       = module.ml_drift_lambda.lambda_function_name
}
