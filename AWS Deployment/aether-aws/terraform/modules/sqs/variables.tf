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

variable "consumer_role_queues" {
  type        = map(string)
  description = <<-EOT
    Consumer role -> canonical consumer group, mirroring the ConsumerSpec
    registry (services/runtime/consumer_specs.py). Each role receives a
    dedicated SNS-subscribed queue so roles never consume (and delete) events
    another role owns.
  EOT
  default = {
    "stream-worker"      = "aether-stream-ingestion"
    "identity-worker"    = "aether-identity"
    "graph-writer"       = "aether-graph-writer"
    "measurement-worker" = "aether-measurement"
  }
}
