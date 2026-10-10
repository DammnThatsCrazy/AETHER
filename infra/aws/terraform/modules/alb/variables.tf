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

# Profile gating: the dedicated aether-ml-serving target group and its listener
# rule only exist for profiles that run the dedicated ML service. Cost-capped
# profiles serve ML inline inside the backend task, so an ML target group there
# would be a permanently empty forbidden resource.
variable "enable_dedicated_ml" {
  type        = bool
  description = "Create the aether-ml-serving target group and the /v1/ml/* listener rule"
  default     = false
}

variable "staging_listener_target_group_arn" {
  type        = string
  description = "Maintenance target group ARN during a reviewed staging backend replacement transition"
  default     = ""
}
