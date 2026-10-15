output "sns_topic_arn" {
  description = "ARN of the SNS topic used for CloudWatch alarm notifications"
  value       = aws_sns_topic.alerts.arn
}

output "dashboard_url" {
  description = "URL to the CloudWatch dashboard"
  value       = "https://${data.aws_region.current.name}.console.aws.amazon.com/cloudwatch/home#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "dashboard_name" {
  description = "Name of the CloudWatch dashboard"
  value       = aws_cloudwatch_dashboard.main.dashboard_name
}

output "log_archive_bucket" {
  description = "S3 bucket name used for long-term log archive (empty string if caller-provided)"
  value       = var.log_archive_bucket == "" ? aws_s3_bucket.log_archive[0].bucket : var.log_archive_bucket
}

output "app_log_group_name" {
  description = "CloudWatch log group name for aether-app"
  value       = aws_cloudwatch_log_group.app.name
}

output "ml_log_group_name" {
  description = "CloudWatch log group name for aether-ml"
  value       = aws_cloudwatch_log_group.ml.name
}
