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
