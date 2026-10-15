# ============================================================================
# AETHER — Provider-Credential Envelope-Encryption KMS Module
#
# A dedicated customer-managed CMK for the durable, envelope-encrypted provider
# credential authority. The approved backend cipher
# (AwsKmsEnvelopeCredentialCipher) calls kms:GenerateDataKey + kms:Decrypt under
# this key, binding a
#   {tenant_id, provider, environment, slot_name, credential_version}
# KMS encryption context on every operation. The backend reads the key id from
# the CREDENTIAL_KMS_KEY_ID env var (wired into the ECS task definition at the
# root/runtime layer); this module only owns the key, its alias, and the least-
# privilege grants.
#
# This CMK is deliberately separate from modules/secrets' Secrets Manager CMK:
# that key encrypts static secret stubs, this one is the root of trust for every
# per-tenant provider credential ever written, and the two have different
# rotation, access, and blast-radius profiles.
# ============================================================================

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  name_prefix = "${var.project}-${var.environment}"
  alias_name  = "alias/${lower(var.project)}-${var.environment}-provider-credentials"

  crypto_actions = [
    "kms:Encrypt",
    "kms:Decrypt",
    "kms:GenerateDataKey",
    "kms:DescribeKey",
  ]
}

# --------------------------------------------------------------------------
# CMK key policy (resource-based)
#
# Statement 1 gives the account root full control so the key stays manageable
# and IAM identity policies (the task_attach document below) can govern access —
# omitting it orphans the key. Statement 2 is the least-privilege crypto grant
# to the ECS task role(s), constrained so the request MUST carry exactly the
# five-key encryption context; a call with a missing or extra context key is
# denied at the key. It is only emitted when a task role is passed.
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "key" {
  statement {
    sid       = "EnableIAMRootPermissions"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  dynamic "statement" {
    for_each = length(var.key_admin_role_arns) > 0 ? [1] : []

    content {
      sid       = "AllowKeyAdministrators"
      effect    = "Allow"
      actions   = ["kms:CancelKeyDeletion", "kms:DescribeKey", "kms:DisableKey", "kms:EnableKey", "kms:GetKeyPolicy", "kms:GetKeyRotationStatus", "kms:ListResourceTags", "kms:PutKeyPolicy", "kms:TagResource", "kms:UntagResource", "kms:UpdateKeyDescription", "kms:UpdateKeyRotationStatus"]
      resources = ["*"]

      principals {
        type        = "AWS"
        identifiers = var.key_admin_role_arns
      }

    }
  }

  # Keep the destructive key-policy path aligned with Terraform's
  # deletion-window contract. This condition is deliberately separate from
  # read/rotation actions, which do not provide a deletion-window value.
  dynamic "statement" {
    for_each = length(var.key_admin_role_arns) > 0 ? [1] : []

    content {
      sid       = "AllowKeyAdministratorDeletion"
      effect    = "Allow"
      actions   = ["kms:ScheduleKeyDeletion"]
      resources = ["*"]

      principals {
        type        = "AWS"
        identifiers = var.key_admin_role_arns
      }

      condition {
        test     = "StringEquals"
        variable = "kms:ScheduleKeyDeletionPendingWindowInDays"
        values   = [tostring(var.deletion_window_in_days)]
      }
    }
  }

  dynamic "statement" {
    for_each = length(var.task_role_arns) > 0 ? [1] : []

    content {
      sid       = "AllowTaskRoleEnvelopeCrypto"
      effect    = "Allow"
      actions   = local.crypto_actions
      resources = ["*"]

      principals {
        type        = "AWS"
        identifiers = var.task_role_arns
      }

      # ForAllValues:StringEquals bounds the request's encryption-context key set
      # to exactly the five-key binding — no unexpected keys are accepted.
      condition {
        test     = "ForAllValues:StringEquals"
        variable = "kms:EncryptionContextKeys"
        values   = var.encryption_context_keys
      }
    }
  }
}

resource "aws_kms_key" "this" {
  description             = "Aether provider-credential envelope encryption"
  deletion_window_in_days = var.deletion_window_in_days
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.key.json

  tags = {
    Name        = "${local.name_prefix}-provider-credentials-kms"
    Environment = var.environment
  }

  lifecycle {
    prevent_destroy = true

    # This CMK is the root of trust for every stored provider credential:
    # destroying it makes every envelope-encrypted credential permanently
    # undecryptable. Following the same rule modules/rds implements, a plan that
    # would destroy this key (e.g. flipping the enable_credential_kms toggle to
    # false, taking the module count to 0) becomes a hard plan error — the
    # stop-the-line event — rather than a diff someone skims. Retiring it for
    # real goes through DECOMMISSION.md: release it from state first, then
    # decommission it as a separate, explicitly approved change.
  }
}

resource "aws_kms_alias" "this" {
  name          = local.alias_name
  target_key_id = aws_kms_key.this.key_id
}

# --------------------------------------------------------------------------
# IAM identity policy for the ECS task role to attach
#
# No principal — this is an identity policy the ECS task-role wiring attaches to
# the API + worker task role (aws_iam_role_policy). It grants the same four
# crypto actions, scoped to THIS key only, under the same five-key encryption-
# context binding. Exposed as the iam_policy_json output.
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "task_attach" {
  statement {
    sid       = "ProviderCredentialEnvelopeCrypto"
    effect    = "Allow"
    actions   = local.crypto_actions
    resources = [aws_kms_key.this.arn]

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "kms:EncryptionContextKeys"
      values   = var.encryption_context_keys
    }
  }
}
