variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name"
}

variable "use_provisioned_capacity" {
  type        = bool
  description = "Use PROVISIONED billing with autoscaling instead of PAY_PER_REQUEST. Cheaper at sustained steady load; may briefly throttle on spikes until autoscale catches up."
  default     = false
}

variable "read_capacity" {
  type        = number
  description = "Base read capacity units (provisioned mode only)"
  default     = 5
}

variable "write_capacity" {
  type        = number
  description = "Base write capacity units (provisioned mode only)"
  default     = 5
}

variable "max_read_capacity" {
  type        = number
  description = "Maximum read capacity units for autoscaling (provisioned mode only)"
  default     = 50
}

variable "max_write_capacity" {
  type        = number
  description = "Maximum write capacity units for autoscaling (provisioned mode only)"
  default     = 50
}
