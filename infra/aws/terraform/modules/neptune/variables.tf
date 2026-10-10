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
  description = "Isolated subnet IDs for the Neptune subnet group"
}

variable "neptune_sg_id" {
  type        = string
  description = "Security group ID to attach to Neptune instances"
}

variable "instance_class" {
  type        = string
  description = "Neptune DB instance class"
  default     = "db.r6g.large"
}

variable "cluster_size" {
  type        = number
  description = "Number of cluster instances (1 = writer only)"
  default     = 1
}
