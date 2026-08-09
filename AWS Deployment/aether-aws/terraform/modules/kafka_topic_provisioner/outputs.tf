# ============================================================================
# AETHER — Kafka Topic Provisioner Module Outputs
# ============================================================================

output "function_name" {
  description = "Name of the topic-provisioner Lambda function"
  value       = aws_lambda_function.topic_provisioner.function_name
}

output "function_arn" {
  description = "ARN of the topic-provisioner Lambda function"
  value       = aws_lambda_function.topic_provisioner.arn
}

output "invocation_result" {
  description = "Raw JSON string returned by the one-shot invocation (created/already_existed counts; mocked placeholder at plan time)."
  value       = aws_lambda_invocation.provision_topics.result
}
