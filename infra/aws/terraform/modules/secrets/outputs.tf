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

output "rotation_lambda_arn" {
  description = "ARN of the secret rotation Lambda function"
  value       = aws_lambda_function.rotation.arn
}

output "companion_secret_arns" {
  description = <<-EOT
    ARNs of companion *-previous secrets populated during zero-downtime rotation.
    Wire these into ECS as the matching *_PREVIOUS variables so the backend
    can read records protected by the prior key during the rotation window.
  EOT
  value = {
    "jwt-secret-previous"                         = aws_secretsmanager_secret.jwt_secret_previous.arn
    "byok-encryption-key-previous"                = aws_secretsmanager_secret.byok_key_previous.arn
    "identity-verification-token-key-previous" = aws_secretsmanager_secret.identity_verification_token_key_previous.arn
  }
}
