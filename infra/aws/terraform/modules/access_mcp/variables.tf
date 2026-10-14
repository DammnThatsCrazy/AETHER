variable "environment" {
  type        = string
  description = "Deployment environment label."
}

variable "project" {
  type        = string
  description = "Project name used for service and IAM resource names."
}

variable "aws_region" {
  type        = string
  description = "AWS region used by the ECS awslogs driver and IAM policy."
}

variable "vpc_id" {
  type        = string
  description = "VPC hosting the existing ALB and ECS cluster."
}

variable "subnet_ids" {
  type        = list(string)
  description = "Existing workload subnets selected by the root egress profile."
}

variable "assign_public_ip" {
  type        = bool
  description = "Use the root profile's public-IP egress mode for ECS task ENIs."
}

variable "alb_sg_id" {
  type        = string
  description = "Existing public ALB security group; the only ingress peer for the MCP task."
}

variable "cluster_arn" {
  type        = string
  description = "Existing AETHER ECS cluster ARN."
}

variable "target_group_arn" {
  type        = string
  description = "Dedicated Access Kit MCP ALB target group ARN."
}

variable "ecr_repository_url" {
  type        = string
  description = "Dedicated aether-access-mcp ECR repository URL."
  validation {
    condition     = var.ecr_repository_url != ""
    error_message = "The dedicated aether-access-mcp ECR repository must be provisioned before enabling the service."
  }
}

variable "ecr_repository_arn" {
  type        = string
  description = "Dedicated aether-access-mcp ECR repository ARN for execution-role pull access."
  validation {
    condition     = can(regex("^arn:aws:ecr:[^:]+:[0-9]{12}:repository/aether-access-mcp$", var.ecr_repository_arn))
    error_message = "ecr_repository_arn must identify the dedicated aether-access-mcp repository."
  }
}

variable "image_digest" {
  type        = string
  description = "Immutable sha256 image digest."
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be an immutable sha256 digest."
  }
}

variable "api_url" {
  type        = string
  description = "HTTPS API origin used by the request-scoped Access Kit MCP tools."
  validation {
    condition     = can(regex("^https://[^/]+$", var.api_url))
    error_message = "api_url must be an HTTPS origin without a path."
  }
}

variable "oauth_resource_uri" {
  type        = string
  description = "Exact public MCP resource URI registered as the Auth0 API audience."
}

variable "oauth_issuer" {
  type        = string
  description = "HTTPS Auth0 authorization-server issuer URL."
}

variable "allowed_host" {
  type        = string
  description = "Exact public API hostname allowed by the Access Kit MCP host guard."
  validation {
    condition     = can(regex("^[A-Za-z0-9.-]+$", var.allowed_host)) && !startswith(var.allowed_host, ".") && !endswith(var.allowed_host, ".")
    error_message = "allowed_host must be a DNS hostname without scheme, port, path, or wildcard."
  }
}

variable "allowed_origins" {
  type        = list(string)
  description = "Optional exact HTTPS origins allowed by the HTTP host."
  default     = []
}

variable "access_mcp_path" {
  type        = string
  description = "HTTP path exposed by the Access Kit MCP host."
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention in days."
}

variable "desired_count" {
  type        = number
  description = "Fixed desired Fargate task count. There is no service autoscaling."
  default     = 2
  validation {
    condition     = var.desired_count >= 1 && var.desired_count <= 4 && floor(var.desired_count) == var.desired_count
    error_message = "desired_count must be an integer between 1 and 4."
  }
}
