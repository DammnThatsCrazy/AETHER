output "lambda_arn" {
  value       = aws_lambda_function.drift.arn
  description = "ARN of the nightly ML drift Lambda"
}

output "lambda_function_name" {
  value       = aws_lambda_function.drift.function_name
  description = "Function name of the nightly ML drift Lambda"
}

output "event_rule_arn" {
  value       = aws_cloudwatch_event_rule.nightly_drift.arn
  description = "ARN of the EventBridge rule that triggers the drift Lambda"
}
