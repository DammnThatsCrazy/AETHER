# ============================================================================
# AETHER — Secrets Manager Module
#
# Creates Secrets Manager secret stubs with KMS encryption.
# No secret VALUES are stored here — values must be injected manually
# post-deploy (see the root README.md for instructions).
#
# Secrets:
#   aether/jwt-secret                — JWT signing key
#   aether/byok-encryption-key       — BYOK AES-256 encryption key
#   aether/stripe-secret-key         — Stripe secret key
#   aether/stripe-webhook-secret     — Stripe webhook signing secret
#   aether/oracle-signer-private-key — Oracle signer private key
#   aether/watermark-secret-key      — Watermark HMAC key
#   aether/canary-secret-seed        — Canary token seed
#   aether/extraction-canary-seed    — Extraction mesh canary seed
#   aether/sdk-config-secret         — SDK manifest signing secret
#
# DB credentials: managed by the RDS module via manage_master_user_password.
# Redis AUTH token: managed by the ElastiCache module. Both ARNs are passed
# into the ECS module at the root level — neither value touches TF state.
#
# ECS task definitions reference these ARNs via the `secrets:` block,
# so the values are injected at container start (never in env vars).
# ============================================================================

# --------------------------------------------------------------------------
# KMS Key shared by all secrets
# --------------------------------------------------------------------------

resource "aws_kms_key" "secrets" {
  description             = "${var.project} Secrets Manager encryption key (${var.environment})"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.secrets.json

  tags = {
    Name        = "${var.project}-${var.environment}-secrets-kms"
    Environment = var.environment
  }
}

# Keep service-side use of this CMK explicit.  Secrets Manager and CloudWatch
# Logs do not inherit the deployment role's identity policy: each service must
# be named in the key policy and constrained to this account, region, and the
# staging AETHER secret/log namespace.  The account-root statement preserves
# IAM delegation for the rotation Lambda and the reviewed apply role.
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

data "aws_iam_policy_document" "secrets" {
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

  statement {
    sid       = "AllowSecretsManagerServiceUse"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKey", "kms:GenerateDataKeyWithoutPlaintext"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["secretsmanager.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${data.aws_region.current.name}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:SecretARN"
      values   = ["arn:${data.aws_partition.current.partition}:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:aether/*"]
    }
  }

  statement {
    sid       = "AllowCloudWatchLogsServiceUse"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey", "kms:GenerateDataKeyWithoutPlaintext", "kms:ReEncrypt*"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["logs.${data.aws_region.current.name}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["logs.${data.aws_region.current.name}.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project}-${var.environment}-*"]
    }
  }
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${lower(var.project)}-${var.environment}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

# --------------------------------------------------------------------------
# Secret definitions
# --------------------------------------------------------------------------

locals {
  secrets = {
    "jwt-secret" = {
      description = "JWT signing key for AETHER authentication service"
    }
    "byok-encryption-key" = {
      description = "BYOK AES-256 encryption key for user-controlled encryption"
    }
    "stripe-secret-key" = {
      description = "Stripe secret API key for payment processing"
    }
    "stripe-webhook-secret" = {
      description = "Stripe webhook endpoint signing secret"
    }
    "oracle-signer-private-key" = {
      description = "Private key for the AETHER oracle signing service"
    }
    "watermark-secret-key" = {
      description = "HMAC key for invisible watermarking"
    }
    "canary-secret-seed" = {
      description = "Seed for canary token generation"
    }
    "extraction-canary-seed" = {
      description = "Seed for extraction mesh canary generation"
    }
    "sdk-config-secret" = {
      description = "HMAC signing secret for SDK configuration manifests"
    }
  }
}

resource "aws_secretsmanager_secret" "this" {
  for_each = local.secrets

  name        = "aether/${each.key}"
  description = each.value.description
  kms_key_id  = aws_kms_key.secrets.arn

  recovery_window_in_days = 30

  tags = {
    Name        = "aether/${each.key}"
    Environment = var.environment
  }
}
