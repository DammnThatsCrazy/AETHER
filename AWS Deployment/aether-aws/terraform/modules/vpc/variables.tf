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

variable "enable_nat_gateway_ha" {
  type        = bool
  description = "Deploy one NAT Gateway per AZ (true) or a single shared NAT (false)"
  default     = false
}
