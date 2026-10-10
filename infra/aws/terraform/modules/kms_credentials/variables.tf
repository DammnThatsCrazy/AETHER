variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name used for resource naming and tagging"
}

variable "task_role_arns" {
  type        = list(string)
  description = <<-EOT
    ECS task-role ARNs granted envelope-encryption crypto on the CMK. The API and
    the worker services share a single ECS task role today (modules/ecs
    aws_iam_role.task), so pass that one ARN as a single-element list; the CMK key
    policy names every element as a principal. Empty list = no principal grant in
    the key policy (the account-root admin statement still governs the key).
  EOT
  default     = []
}

variable "key_admin_role_arns" {
  type        = list(string)
  description = "Deployment/admin role ARNs explicitly allowed to manage the CMK policy and key lifecycle."
  default     = []
}

variable "deletion_window_in_days" {
  type        = number
  description = "KMS CMK deletion window in days. 30 mirrors the secrets and RDS CMKs."
  default     = 30

  validation {
    condition     = var.deletion_window_in_days >= 7 && var.deletion_window_in_days <= 30
    error_message = "deletion_window_in_days must be between 7 and 30."
  }
}

variable "encryption_context_keys" {
  type        = list(string)
  description = <<-EOT
    The KMS encryption-context binding keys the approved
    AwsKmsEnvelopeCredentialCipher passes on every kms:GenerateDataKey /
    kms:Decrypt call. Both the CMK key policy and the exported task IAM policy
    constrain access to exactly this key set via kms:EncryptionContextKeys, so a
    caller that omits or adds a context key is denied. Keep in sync with the
    backend cipher.
  EOT
  default     = ["tenant_id", "provider", "environment", "slot_name", "credential_version"]

  validation {
    condition     = length(var.encryption_context_keys) == 5
    error_message = "encryption_context_keys must be exactly the five-key binding {tenant_id, provider, environment, slot_name, credential_version}."
  }
}
