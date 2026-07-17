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
