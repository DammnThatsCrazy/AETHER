# ═══════════════════════════════════════════════════════════════════════════
# Aether — Shared Variable Definitions
# Reusable across all environment compositions.
# ═══════════════════════════════════════════════════════════════════════════

variable "environment" {
  type        = string
  description = "Environment name (dev, staging, production, demo)"
  validation {
    condition     = contains(["dev", "staging", "production", "demo"], var.environment)
    error_message = "Environment must be dev, staging, production, or demo."
  }
}

variable "aws_region" {
  type        = string
  description = "Primary AWS region"
  default     = "us-east-1"
  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "Must be a valid AWS region identifier."
  }
}

variable "image_tag" {
  type        = string
  description = "Docker image tag for ECS services"
  default     = "latest"
}

variable "ecr_registry" {
  type        = string
  description = "ECR registry URL (account_id.dkr.ecr.region.amazonaws.com)"
}

variable "acm_cert_arn" {
  type        = string
  description = "ACM certificate ARN for HTTPS (empty to skip custom domain)"
  default     = ""
}

variable "hosted_zone_id" {
  type        = string
  description = "Route 53 hosted zone ID (empty to skip DNS records)"
  default     = ""
}

variable "monthly_budget_usd" {
  type        = number
  description = "Monthly budget in USD for cost alerts"
  default     = 15000
  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "Budget must be positive."
  }
}
