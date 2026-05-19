# ============================================================================
# AETHER — Secrets Manager Module
#
# Creates Secrets Manager secret stubs with KMS encryption.
# No secret VALUES are stored here — values must be injected manually
# post-deploy (see the root README.md for instructions).
#
# The one exception is the db-password secret, whose value is written
# by the RDS module after the DB instance is created.
#
# Secrets:
#   aether/jwt-secret                — JWT signing key
#   aether/byok-encryption-key       — BYOK AES-256 encryption key
#   aether/db-password               — Postgres credentials (set by RDS module)
#   aether/stripe-secret-key         — Stripe secret key
#   aether/stripe-webhook-secret     — Stripe webhook signing secret
#   aether/oracle-signer-private-key — Oracle signer private key
#   aether/watermark-secret-key      — Watermark HMAC key
#   aether/canary-secret-seed        — Canary token seed
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

  tags = {
    Name = "${var.project}-${var.environment}-secrets-kms"
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
    "db-password" = {
      description = "Postgres credentials (host, port, username, password, dbname)"
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
