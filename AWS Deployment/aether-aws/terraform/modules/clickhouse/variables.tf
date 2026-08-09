# ============================================================================
# AETHER — ClickHouse Analytics Module Variables
# ============================================================================

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
  description = "VPC ID the appliance is placed in"
}

variable "subnet_id" {
  type        = string
  description = "Isolated subnet ID for the appliance (one AZ)"
}

variable "allowed_sg_id" {
  type        = string
  description = "Security group allowed to reach ClickHouse (the ECS task SG)"
}

variable "ami_id" {
  type        = string
  description = <<-EOT
    Amazon Linux 2023 AMI for the ClickHouse appliance. A regional default must
    be supplied by the caller (the root module defaults it to a us-east-1 AL2023
    AMI; override per region via `clickhouse_ami_id`).
  EOT
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type for the ClickHouse appliance"
  default     = "m6i.large"
}

variable "key_name" {
  type        = string
  description = "Optional EC2 key pair name for operator SSH (null = no SSH access)"
  default     = null
}

variable "root_volume_size" {
  type        = number
  description = "Root EBS volume size in GiB"
  default     = 20
}

variable "data_volume_size" {
  type        = number
  description = "Dedicated ClickHouse data volume size in GiB"
  default     = 100
}

variable "data_volume_type" {
  type        = string
  description = "EBS volume type for the data volume"
  default     = "gp3"
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch retention for the ClickHouse log group"
  default     = 30
}
