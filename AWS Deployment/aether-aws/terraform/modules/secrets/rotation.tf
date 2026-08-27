# ============================================================================
# Automated secret rotation — Lambda function + IAM + schedules
#
# Rotates AETHER-managed secrets on a schedule using the standard AWS
# Secrets Manager 4-phase protocol (createSecret → setSecret → testSecret →
# finishSecret). The Lambda source lives at lambda/rotate_secret.py in the
# repo root; Terraform packages it into a ZIP at plan/apply time.
#
# Secrets with zero-downtime rotation (30-day schedule):
#   aether/jwt-secret           → companion: aether/jwt-secret-previous
#   aether/byok-encryption-key  → companion: aether/byok-encryption-key-previous
#
# Secrets with clean-break rotation (90-day schedule):
#   aether/watermark-secret-key
#   aether/canary-secret-seed
#
# After BYOK rotation completes, run:
#   python scripts/byok_reencrypt.py --old-key <previous> --new-key <current>
# to re-encrypt stored tenant API keys. See docs/SECRET-ROTATION.md.
# ============================================================================

# --------------------------------------------------------------------------
# Companion secrets for zero-downtime rotation
# The Lambda writes the current AWSCURRENT value here in the setSecret phase
# so the backend can still validate tokens/keys signed with the old secret
# during the window between rotation and the next ECS deployment.
# --------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "jwt_secret_previous" {
  name                    = "aether/jwt-secret-previous"
  description             = "Previous JWT signing key — populated by rotation Lambda; clear after next ECS deploy"
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = {
    Name        = "aether/jwt-secret-previous"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret" "byok_key_previous" {
  name                    = "aether/byok-encryption-key-previous"
  description             = "Previous BYOK encryption key — populated by rotation Lambda; clear after re-encryption"
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 7

  tags = {
    Name        = "aether/byok-encryption-key-previous"
    Environment = var.environment
  }
}

# --------------------------------------------------------------------------
# IAM execution role
# --------------------------------------------------------------------------

data "aws_iam_policy_document" "rotation_lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rotation_lambda" {
  name               = "${var.project}-${var.environment}-secret-rotation"
  assume_role_policy = data.aws_iam_policy_document.rotation_lambda_assume.json

  tags = {
    Name        = "${var.project}-${var.environment}-secret-rotation"
    Environment = var.environment
  }
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "rotation_lambda_policy" {
  statement {
    sid = "SecretsManagerRotation"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
      "secretsmanager:PutSecretValue",
      "secretsmanager:UpdateSecretVersionStage",
      "secretsmanager:CreateSecret",
    ]
    resources = ["arn:aws:secretsmanager:*:${data.aws_caller_identity.current.account_id}:secret:aether/*"]
  }

  statement {
    sid = "KMSForSecrets"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.secrets.arn]
  }

  statement {
    sid = "CloudWatchLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.rotation_lambda.arn}:*"]
  }
}

resource "aws_iam_role_policy" "rotation_lambda" {
  name   = "rotation-permissions"
  role   = aws_iam_role.rotation_lambda.id
  policy = data.aws_iam_policy_document.rotation_lambda_policy.json
}

# VPC execution role attachment — required if Lambda runs inside the VPC
resource "aws_iam_role_policy_attachment" "rotation_lambda_vpc" {
  role       = aws_iam_role.rotation_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# --------------------------------------------------------------------------
# CloudWatch log group (pre-create so retention is set before first invocation)
# --------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "rotation_lambda" {
  name              = "/aws/lambda/${var.project}-${var.environment}-secret-rotation"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.secrets.arn

  tags = {
    Name        = "${var.project}-${var.environment}-rotation-logs"
    Environment = var.environment
  }
}

# --------------------------------------------------------------------------
# Lambda function
# --------------------------------------------------------------------------

data "archive_file" "rotation_lambda" {
  type        = "zip"
  source_file = "${path.module}/../../../../../lambda/rotate_secret.py"
  # Keep the generated archive in the Terraform root so the reviewed-plan
  # workflow can carry the exact bytes into its apply job.
  output_path = "${path.root}/rotate_secret.zip"
}

resource "aws_lambda_function" "rotation" {
  filename         = data.archive_file.rotation_lambda.output_path
  source_code_hash = data.archive_file.rotation_lambda.output_base64sha256
  function_name    = "${var.project}-${var.environment}-secret-rotation"
  role             = aws_iam_role.rotation_lambda.arn
  handler          = "rotate_secret.lambda_handler"
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      ENVIRONMENT = var.environment
    }
  }

  depends_on = [
    aws_iam_role_policy.rotation_lambda,
    aws_cloudwatch_log_group.rotation_lambda,
  ]

  tags = {
    Name        = "${var.project}-${var.environment}-secret-rotation"
    Environment = var.environment
  }
}

# --------------------------------------------------------------------------
# Permission: Secrets Manager can invoke the rotation Lambda
# Scoped to this account to prevent confused-deputy attacks.
# --------------------------------------------------------------------------

resource "aws_lambda_permission" "secretsmanager" {
  statement_id   = "AllowSecretsManagerInvocation"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.rotation.function_name
  principal      = "secretsmanager.amazonaws.com"
  source_account = data.aws_caller_identity.current.account_id
}

# --------------------------------------------------------------------------
# Rotation schedules
# rotate_immediately = false so Terraform apply doesn't trigger an immediate
# rotation — the first automatic rotation happens after the first scheduled window.
# --------------------------------------------------------------------------

locals {
  rotatable_secrets = {
    "jwt-secret"           = { days = 30 }
    "byok-encryption-key"  = { days = 30 }
    "watermark-secret-key" = { days = 90 }
    "canary-secret-seed"   = { days = 90 }
  }
}

resource "aws_secretsmanager_secret_rotation" "this" {
  for_each = local.rotatable_secrets

  secret_id           = aws_secretsmanager_secret.this[each.key].id
  rotation_lambda_arn = aws_lambda_function.rotation.arn
  rotate_immediately  = false

  rotation_rules {
    automatically_after_days = each.value.days
  }

  depends_on = [aws_lambda_permission.secretsmanager]
}
