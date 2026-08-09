# ============================================================================
# AETHER — Kafka Topic Provisioner Module Variables
# ============================================================================

variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name"
}

variable "bootstrap_servers" {
  type        = string
  description = "MSK TLS bootstrap broker string the provisioner creates topics against (module.msk[0].bootstrap_brokers_tls)."
}

variable "subnet_ids" {
  type        = list(string)
  description = "Subnets for the Lambda ENI (the profile's private subnets, which have NAT egress for CloudWatch logs)."
}

variable "lambda_security_group_id" {
  type        = string
  description = "Security group for the Lambda ENI. The MSK ingress rule sources the ECS task SG on TLS 9094, so pass module.vpc.ecs_sg_id to reuse that allowance."
}

variable "topic_partitions" {
  type        = number
  description = "Partition count for every created topic (matches MSK num.partitions=3)."
  default     = 3
}

variable "topic_replication_factor" {
  type        = number
  description = "Replication factor for every created topic (matches MSK default.replication.factor=3; broker_count must be >= this)."
  default     = 3
}

variable "topic_create_timeout_ms" {
  type        = number
  description = "Per-topic create timeout for the Kafka admin client."
  default     = 30000
}

variable "lambda_timeout_seconds" {
  type        = number
  description = "Lambda function timeout in seconds."
  default     = 120
}

variable "lambda_memory_mb" {
  type        = number
  description = "Lambda function memory in MiB."
  default     = 256
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch retention for the provisioner Lambda log group."
  default     = 30
}
