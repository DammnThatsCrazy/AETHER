# ============================================================================
# AETHER — ML Drift Lambda Module (E6)
#
# Provisions:
#   - Lambda function (nightly PSI drift check for all ML models)
#   - IAM role with S3 read + CloudWatch PutMetricData permissions
#   - EventBridge rule (cron schedule, default 02:00 UTC daily)
#   - Lambda permission for EventBridge invocation
# ============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# --------------------------------------------------------------------------
# Package Lambda source into a zip archive at plan/apply time
# --------------------------------------------------------------------------

data "archive_file" "lambda_zip" {
  type       = "zip"
  source_dir = "${path.module}/lambda_src"
  # The archive provider does not create parent directories. Keep the
  # generated package in the initialized Terraform root, which exists in both
  # plan and apply runners, rather than relying on an absent module-local
  # `.build` directory.
  output_path = "${path.root}/drift_lambda.zip"
}

# --------------------------------------------------------------------------
# IAM Role
# --------------------------------------------------------------------------

resource "aws_iam_role" "drift_lambda" {
  name = "${var.project}-${var.environment}-drift-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${var.project}-${var.environment}-drift-lambda-role"
  }
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.drift_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "drift_lambda_policy" {
  name = "${var.project}-${var.environment}-drift-lambda-policy"
  role = aws_iam_role.drift_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3ReadPredictions"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = [
          "arn:aws:s3:::${var.log_bucket}",
          "arn:aws:s3:::${var.log_bucket}/predictions/*",
          "arn:aws:s3:::${var.log_bucket}/drift-reference/*",
        ]
      },
      {
        Sid    = "CloudWatchPutMetrics"
        Effect = "Allow"
        Action = ["cloudwatch:PutMetricData"]
        # Scoped to the Aether/MLDrift namespace
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "Aether/MLDrift"
          }
        }
      },
    ]
  })
}

# --------------------------------------------------------------------------
# Lambda Function
# --------------------------------------------------------------------------

resource "aws_lambda_function" "drift" {
  function_name    = "${var.project}-${var.environment}-ml-drift"
  role             = aws_iam_role.drift_lambda.arn
  handler          = "drift_lambda.handler"
  runtime          = "python3.12"
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  environment {
    variables = {
      LOG_BUCKET    = var.log_bucket
      MODEL_NAMES   = join(",", var.model_names)
      PSI_THRESHOLD = tostring(var.psi_threshold)
    }
  }

  tags = {
    Name = "${var.project}-${var.environment}-ml-drift-lambda"
  }
}

resource "aws_cloudwatch_log_group" "drift_lambda" {
  name              = "/aws/lambda/${aws_lambda_function.drift.function_name}"
  retention_in_days = 7
}

# --------------------------------------------------------------------------
# EventBridge (CloudWatch Events) nightly schedule
# --------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "nightly_drift" {
  name                = "${var.project}-${var.environment}-nightly-drift"
  description         = "Triggers the ML drift Lambda nightly to compute PSI scores and publish to CloudWatch"
  schedule_expression = var.schedule_expression

  tags = {
    Name = "${var.project}-${var.environment}-nightly-drift-rule"
  }
}

resource "aws_cloudwatch_event_target" "drift_lambda" {
  rule      = aws_cloudwatch_event_rule.nightly_drift.name
  target_id = "DriftLambda"
  arn       = aws_lambda_function.drift.arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.drift.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.nightly_drift.arn
}
