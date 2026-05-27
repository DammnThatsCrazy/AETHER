variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name"
}

variable "visibility_timeout_seconds" {
  type        = number
  description = "SQS visibility timeout — should be >= Lambda/consumer processing timeout"
  default     = 60
}

variable "message_retention_seconds" {
  type        = number
  description = "How long SQS retains undelivered messages (seconds)"
  default     = 345600 # 4 days
}

variable "max_receive_count" {
  type        = number
  description = "Number of times a message can be received before going to the DLQ"
  default     = 5
}
