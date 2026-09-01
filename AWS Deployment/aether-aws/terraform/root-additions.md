# Root module additions for tfmcp

## variables.tf — add these variables

```hcl
# ---------------------------------------------------------------------------
# tfmcp MCP Server
# ---------------------------------------------------------------------------

variable "enable_tfmcp" {
  type        = bool
  description = "Deploy the tfmcp Terraform MCP server. Profile-gated in profiles.tf."
  default     = false
}

variable "tfmcp_image_digest" {
  type        = string
  description = "Immutable sha256 digest of the tfmcp container image."
  default     = ""
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.tfmcp_image_digest))
    error_message = "tfmcp_image_digest must be an immutable sha256 digest (e.g. sha256:abc123...)."
  }
}

variable "tfmcp_auth_token" {
  type      = string
  description = "MCP auth token (32+ chars). Auto-generated if empty."
  default   = ""
  sensitive = true

  validation {
    condition     = var.tfmcp_auth_token == "" || length(var.tfmcp_auth_token) >= 32
    error_message = "tfmcp_auth_token must be at least 32 characters or empty (auto-generated)."
  }
}

variable "tfmcp_github_pat" {
  type      = string
  description = "GitHub PAT for cloning the Aether repo into the tfmcp container. Empty if the repo is public."
  default   = ""
  sensitive = true
}

variable "tfmcp_cpu" {
  type        = number
  description = "Fargate CPU units for the tfmcp task."
  default     = 512
}

variable "tfmcp_memory" {
  type        = number
  description = "Fargate memory (MiB) for the tfmcp task."
  default     = 1024
}

variable "tfmcp_desired_count" {
  type        = number
  description = "Desired task count for the tfmcp service."
  default     = 1
}

variable "tfmcp_log_level" {
  type        = string
  description = "tfmcp log level."
  default     = "info"
}

variable "tfmcp_listener_priority" {
  type        = number
  description = "ALB listener rule priority for /mcp."
  default     = 100
}

variable "aether_repo_ref" {
  type        = string
  description = "Git ref of the Aether repo to clone into the tfmcp container."
  default     = "main"
}

variable "enable_tfmcp_in_lean" {
  type        = bool
  description = "Opt-in flag to deploy tfmcp in the production-lean profile. Off by default — lean stays lean unless you explicitly want operator tooling."
  default     = false
}

variable "terraform_state_bucket" {
  type        = string
  description = "S3 bucket name for the Terraform state backend."
  default     = ""
}

variable "terraform_state_key" {
  type        = string
  description = "S3 key for the Terraform state file."
  default     = ""
}

variable "terraform_lock_table" {
  type        = string
  description = "DynamoDB table name for the Terraform state lock."
  default     = ""
}

variable "terraform_state_kms_key_arn" {
  type        = string
  description = "ARN of the KMS key encrypting the Terraform state. Empty if not encrypted."
  default     = ""
}
```

## profiles.tf — add to locals block

```hcl
  enable_tfmcp = local.scale || local.enterprise || (local.lean && var.enable_tfmcp_in_lean)
```

## main.tf — add the module call (after ECS module, before monitoring)

```hcl
module "tfmcp" {
  count = local.enable_tfmcp ? 1 : 0
  source = "./modules/tfmcp"

  enable_tfmcp            = local.enable_tfmcp  # drive from profile gate, not root var (default=false, unused)
  tfmcp_image_digest      = var.tfmcp_image_digest
  tfmcp_cpu               = var.tfmcp_cpu
  tfmcp_memory            = var.tfmcp_memory
  tfmcp_desired_count     = var.tfmcp_desired_count
  tfmcp_log_level         = var.tfmcp_log_level
  tfmcp_listener_priority = var.tfmcp_listener_priority
  aether_repo_ref         = var.aether_repo_ref
  tfmcp_auth_token        = var.tfmcp_auth_token
  tfmcp_github_pat        = var.tfmcp_github_pat

  vpc_id                 = module.vpc.vpc_id
  ecs_cluster_id         = module.ecs.cluster_id
  ecs_subnet_ids         = module.vpc.public_subnet_ids
  ecs_security_group_ids = [module.ecs.tasks_secgroup_id]

  # IMPORTANT: The ALB listener ARN output key must match your ALB module's actual output.
  # terraform-aws-modules/alb exports listeners as a map: module.alb.listeners["http"].arn
  # Verify this against your modules/alb/outputs.tf. If your module defines a custom
  # output like http_listener_arn, use that instead.
  alb_listener_arn = module.alb.listeners["http"].arn
  alb_dns_name     = module.alb.dns_name

  terraform_state_bucket      = var.terraform_state_bucket
  terraform_state_key         = var.terraform_state_key
  terraform_lock_table        = var.terraform_lock_table
  terraform_state_kms_key_arn = var.terraform_state_kms_key_arn

  environment        = var.environment
  project            = var.project
  aws_region         = var.aws_region
  log_retention_days = var.log_retention_days
  deployment_profile = var.deployment_profile
}
```

## profiles/production-lean.tfvars — opt in

```hcl
enable_tfmcp_in_lean = true
# tfmcp_image_digest = "sha256:abc123..."  # after build
```
