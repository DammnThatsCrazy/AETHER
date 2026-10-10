output "key_id" {
  description = "KMS CMK key id for provider-credential envelope encryption. Wire into the backend as CREDENTIAL_KMS_KEY_ID."
  value       = aws_kms_key.this.key_id
}

output "key_arn" {
  description = "KMS CMK ARN for provider-credential envelope encryption."
  value       = aws_kms_key.this.arn
}

output "alias_name" {
  description = "KMS alias name (alias/<project>-<env>-provider-credentials)."
  value       = aws_kms_alias.this.name
}

output "iam_policy_json" {
  description = <<-EOT
    Least-privilege IAM identity policy JSON granting kms:Encrypt, kms:Decrypt,
    kms:GenerateDataKey and kms:DescribeKey on this CMK, constrained to the
    five-key {tenant_id, provider, environment, slot_name, credential_version}
    encryption context. Attach to the ECS API + worker task role via
    aws_iam_role_policy so the AwsKmsEnvelopeCredentialCipher can perform
    envelope crypto.
  EOT
  value       = data.aws_iam_policy_document.task_attach.json
}
