output "repository_urls" {
  description = "Map of repository name to repository URL"
  value       = { for k, v in aws_ecr_repository.this : k => v.repository_url }
}

output "repository_arns" {
  description = "Map of repository name to repository ARN"
  value       = { for k, v in aws_ecr_repository.this : k => v.arn }
}

output "kms_key_arn" {
  description = "KMS key ARN used for ECR encryption"
  value       = aws_kms_key.ecr.arn
}
