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

variable "rds_sg_id" {
  type        = string
  description = "Security group ID to attach to the RDS instance"
}

variable "db_instance_class" {
  type        = string
  description = "RDS instance class"
  default     = "db.t3.medium"
}

variable "db_name" {
  type        = string
  description = "Initial database name"
  default     = "aether"
}

variable "multi_az" {
  type        = bool
  description = "Enable Multi-AZ deployment"
  default     = true
}

variable "allocated_storage" {
  type        = number
  description = "Initial storage in GiB"
  default     = 100
}

variable "max_allocated_storage" {
  type        = number
  description = "Maximum storage in GiB (autoscaling upper bound)"
  default     = 500
}

