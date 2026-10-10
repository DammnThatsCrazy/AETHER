output "queue_url" {
  description = "URL of the main events SQS queue"
  value       = aws_sqs_queue.events.url
}

output "queue_arn" {
  description = "ARN of the main events SQS queue"
  value       = aws_sqs_queue.events.arn
}

output "dlq_url" {
  description = "URL of the dead-letter queue"
  value       = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  description = "ARN of the dead-letter queue"
  value       = aws_sqs_queue.dlq.arn
}

output "fanout_topic_arn" {
  description = "ARN of the SNS fanout topic"
  value       = aws_sns_topic.fanout.arn
}

output "role_queue_urls" {
  description = "Consumer role -> dedicated SNS-subscribed queue URL"
  value       = { for role, queue in aws_sqs_queue.role : role => queue.url }
}

output "role_queue_arns" {
  description = "Consumer role -> dedicated SNS-subscribed queue ARN"
  value       = { for role, queue in aws_sqs_queue.role : role => queue.arn }
}

# The per-role dead-letter queues have always been created (they are the
# redrive target of aws_sqs_queue.role) but were never published, so nothing
# downstream could tell a task where to put a poison message. The runtime used
# to fall back to re-publishing onto the SOURCE queue, which re-received the
# copy, matched no handler and deleted it — silent loss. It now raises instead,
# so these URLs are load-bearing rather than informational.
#
# A role's DLQ can never be its own queue: both names are built from the same
# key and the DLQ carries a "-dlq" suffix, so the two queues are always
# distinct resources with distinct URLs.
output "role_dlq_queue_urls" {
  description = "Consumer role -> dedicated dead-letter queue URL (the redrive target of that role's queue)"
  value       = { for role, queue in aws_sqs_queue.role_dlq : role => queue.url }
}

output "role_dlq_queue_arns" {
  description = "Consumer role -> dedicated dead-letter queue ARN; the task role needs sqs:SendMessage on these to dead-letter at all"
  value       = { for role, queue in aws_sqs_queue.role_dlq : role => queue.arn }
}
