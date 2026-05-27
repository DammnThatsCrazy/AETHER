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
