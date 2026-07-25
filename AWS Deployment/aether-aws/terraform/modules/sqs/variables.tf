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
    registry (services/runtime/consumer_specs.py). Each role listed here
    receives a dedicated SNS-subscribed queue plus its own dead-letter queue,
    so roles never consume (and delete) events another role owns, and a poison
    message never lands back on the queue it came from.

    FOUR ROLES, NOT FIVE, AND DELIBERATELY SO. roles.py::CONSUMER_ROLES
    declares five; `semantic-worker` is absent here and resolves through the
    documented SQS_QUEUE_URL fallback to the shared events queue, with the
    shared events DLQ as its dead-letter destination. That is a decision, not
    an oversight: semantic-worker has no ConsumerSpec of its own to give a
    queue a consumer group, and a queue nothing is declared to drain is a
    standing cost that silently accrues a backlog. Giving it a dedicated queue
    means adding its consumer group here AND to the runtime registry in the
    same change — the two must not disagree.
  EOT
  default = {
    "stream-worker"      = "aether-stream-ingestion"
    "identity-worker"    = "aether-identity"
    "graph-writer"       = "aether-graph-writer"
    "measurement-worker" = "aether-measurement"
  }
}
