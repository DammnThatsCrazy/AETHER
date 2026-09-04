variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name"
}

variable "repository_encryption_types" {
  type        = map(string)
  default     = {}
  description = "Optional per-repository encryption overrides. Repositories default to KMS; AES256 is allowed only for an explicitly reconciled existing repository."

  validation {
    condition     = alltrue([for encryption_type in values(var.repository_encryption_types) : contains(["KMS", "AES256"], encryption_type)])
    error_message = "repository_encryption_types values must be KMS or AES256."
  }
}

variable "repository_tag_mutabilities" {
  type        = map(string)
  default     = {}
  description = "Optional per-repository tag mutability overrides. Repositories default to MUTABLE."

  validation {
    condition     = alltrue([for mutability in values(var.repository_tag_mutabilities) : contains(["MUTABLE", "IMMUTABLE"], mutability)])
    error_message = "repository_tag_mutabilities values must be MUTABLE or IMMUTABLE."
  }
}
