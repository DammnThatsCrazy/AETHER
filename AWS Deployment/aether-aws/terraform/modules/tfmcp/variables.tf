variable "enable_tfmcp" { type = bool description = "Whether to deploy the tfmcp MCP server." default = false }
variable "tfmcp_image_digest" { type = string description = "Immutable sha256 digest of the tfmcp container image." default = "" validation { condition = can(regex("^sha256:[0-9a-f]{64}$", var.tfmcp_image_digest)) error_message = "tfmcp_image_digest must be an immutable sha256 digest." } }
variable "tfmcp_cpu" { type = number description = "Fargate CPU units." default = 512 validation { condition = contains([256, 512, 1024, 2048, 4096], var.tfmcp_cpu) error_message = "tfmcp_cpu must be a valid Fargate CPU value." } }
variable "tfmcp_memory" { type = number description = "Fargate memory (MiB)." default = 1024 validation { condition = contains([512, 1024, 2048, 4096, 8192, 16384], var.tfmcp_memory) error_message = "tfmcp_memory must be a valid Fargate memory value." } }
variable "tfmcp_port" { type = number description = "Port the tfmcp MCP server listens on." default = 8080 validation { condition = var.tfmcp_port >= 1 && var.tfmcp_port <= 65535 error_message = "tfmcp_port must be between 1 and 65535." } }
variable "tfmcp_desired_count" { type = number description = "Desired task count." default = 1 validation { condition = var.tfmcp_desired_count >= 0 error_message = "tfmcp_desired_count must be >= 0." } }
variable "tfmcp_log_level" { type = string description = "Log level." default = "info" validation { condition = contains(["trace", "debug", "info", "warn", "error"], var.tfmcp_log_level) error_message = "tfmcp_log_level must be one of: trace, debug, info, warn, error." } }
variable "tfmcp_listener_priority" { type = number description = "ALB listener rule priority for /mcp." default = 100 validation { condition = var.tfmcp_listener_priority >= 1 && var.tfmcp_listener_priority <= 50000 error_message = "tfmcp_listener_priority must be between 1 and 50000." } }
variable "aether_repo_ref" { type = string description = "Git ref of the Aether repo to clone." default = "main" }
variable "tfmcp_auth_token" { type = string description = "MCP auth token (32+ chars). Auto-generated if empty." default = "" sensitive = true validation { condition = var.tfmcp_auth_token == "" || length(var.tfmcp_auth_token) >= 32 error_message = "tfmcp_auth_token must be at least 32 characters or empty." } }
variable "tfmcp_github_pat" { type = string description = "GitHub PAT for cloning the Aether repo. Empty if public." default = "" sensitive = true }
variable "alb_listener_arn" { type = string description = "ARN of the ALB listener to attach the /mcp rule to." default = "" }
variable "vpc_id" { type = string description = "VPC ID." default = "" }
variable "ecs_cluster_id" { type = string description = "ECS cluster ID." default = "" }
variable "ecs_subnet_ids" { type = list(string) description = "Subnet IDs for the tfmcp task ENI." default = [] }
variable "ecs_security_group_ids" { type = list(string) description = "Security group IDs for the tfmcp task ENI." default = [] }
variable "terraform_state_bucket" { type = string description = "S3 bucket name for the Terraform state backend." default = "" }
variable "terraform_state_key" { type = string description = "S3 key for the Terraform state file." default = "" }
variable "terraform_lock_table" { type = string description = "DynamoDB table name for the Terraform state lock." default = "" }
variable "terraform_state_kms_key_arn" { type = string description = "ARN of the KMS key encrypting the Terraform state." default = "" }
