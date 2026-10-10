variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name for tagging and naming"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC"
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  type        = list(string)
  description = "List of availability zone names to deploy into (exactly 3 required)"
}

variable "nat_mode" {
  type        = string
  description = "NAT topology: \"none\" (no NAT Gateway), \"single\" (one shared NAT), or \"ha\" (one NAT per AZ)"
  default     = "single"

  validation {
    condition     = contains(["none", "single", "ha"], var.nat_mode)
    error_message = "nat_mode must be one of: none, single, ha."
  }
}

# Data-store security groups are only created for profiles that provision the
# matching backend, so lean profiles carry no unused network policy.

variable "enable_redis_sg" {
  type        = bool
  description = "Create the ElastiCache Redis security group"
  default     = false
}

variable "enable_msk_sg" {
  type        = bool
  description = "Create the MSK Kafka security group"
  default     = false
}

variable "enable_neptune_sg" {
  type        = bool
  description = "Create the Neptune security group"
  default     = false
}
