variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Isolated subnet IDs for the DB subnet group"
}

variable "aurora_sg_id" {
  type        = string
  description = "Security group ID to attach to the Aurora cluster"
}

variable "db_name" {
  type        = string
  description = "Initial database name"
  default     = "aether"
}

variable "min_acu" {
  type        = number
  description = "Aurora Serverless v2 minimum capacity units (0 = auto-pause; prod callers should pass 0.5)"
  default     = 0
}

variable "max_acu" {
  type        = number
  description = "Aurora Serverless v2 maximum capacity units"
  default     = 4
}

variable "auto_pause_seconds" {
  type        = number
  description = "Idle seconds before Aurora Serverless v2 auto-pauses; null disables auto-pause for warm profiles."
  default     = null

  validation {
    condition     = var.auto_pause_seconds == null || (var.auto_pause_seconds >= 300 && var.auto_pause_seconds <= 86400)
    error_message = "auto_pause_seconds must be null or between 300 and 86400 seconds."
  }
}

variable "backup_retention_days" {
  type        = number
  description = "Automated backup retention in days"
  default     = 7
}

variable "deletion_protection" {
  type        = bool
  description = "Enable deletion protection"
  default     = false
}
