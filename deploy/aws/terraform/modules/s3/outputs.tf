output "ml_artifacts_bucket" {
  description = "Name of the ML artifacts S3 bucket"
  value       = aws_s3_bucket.ml_artifacts.id
}

output "ml_artifacts_bucket_arn" {
  description = "ARN of the ML artifacts S3 bucket"
  value       = aws_s3_bucket.ml_artifacts.arn
}

output "cdn_bucket" {
  description = "Name of the CDN static-assets S3 bucket"
  value       = aws_s3_bucket.cdn.id
}

output "cdn_bucket_arn" {
  description = "ARN of the CDN static-assets S3 bucket"
  value       = aws_s3_bucket.cdn.arn
}

output "dashboard_bucket" {
  description = "Name of the dashboard static-assets S3 bucket"
  value       = aws_s3_bucket.dashboard.id
}

output "dashboard_bucket_arn" {
  description = "ARN of the dashboard static-assets S3 bucket"
  value       = aws_s3_bucket.dashboard.arn
}

output "ml_artifacts_read_policy_arn" {
  description = "ARN of the least-privilege read IAM policy for the ML artifacts bucket (attach to serving task role)"
  value       = aws_iam_policy.ml_artifacts_read.arn
}

output "ml_artifacts_write_policy_arn" {
  description = "ARN of the least-privilege write IAM policy for the ML artifacts bucket (attach to training task role)"
  value       = aws_iam_policy.ml_artifacts_write.arn
}
