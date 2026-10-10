variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name"
  default     = "aether"
}

variable "dr_region" {
  type        = string
  description = "Disaster-recovery region for cross-region replication; empty string disables replication"
  default     = ""
}

variable "enable_replication" {
  type        = bool
  description = "Enable cross-region replication for the ML artifacts bucket (production only)"
  default     = false
}
