output "secret_arns" {
  description = "Map of secret name to Secrets Manager ARN — no values are exposed"
  value       = { for k, v in aws_secretsmanager_secret.this : k => v.arn }
}

output "kms_key_arn" {
  description = "KMS key ARN used to encrypt all secrets"
  value       = aws_kms_key.secrets.arn
}

output "kms_key_id" {
  description = "KMS key ID used to encrypt all secrets"
  value       = aws_kms_key.secrets.key_id
}
