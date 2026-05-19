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

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnet IDs for the ALB"
}

variable "alb_sg_id" {
  type        = string
  description = "Security group ID for the ALB"
}

variable "acm_certificate_arn" {
  type        = string
  description = "ACM certificate ARN for HTTPS listener"
}
