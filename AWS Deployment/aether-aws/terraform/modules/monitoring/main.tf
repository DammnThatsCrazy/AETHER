# ============================================================================
# AETHER — Monitoring Module (E6 cost reduction)
#
# Provisions (budget-optimised):
#   - CloudWatch log groups (3-day retention; longer retention → S3 archive)
#   - S3 log archive bucket (IT storage class; Glacier IR after 90 days)
#   - SNS topic for alarm notifications
#   - CloudWatch alarms (3 critical alarms only):
#       1. ALB 5xx error rate > 1%
#       2. Aurora at max ACU for > 10 min (capacity ceiling alert)
#       3. ML accuracy drift PSI breach (custom metric from nightly drift Lambda)
#   - CloudWatch Dashboard "AETHER-<env>" with ECS, Aurora, SageMaker,
#     DynamoDB, and ALB widgets
# ============================================================================

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# --------------------------------------------------------------------------
# SNS Topic for Alarms
# --------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${lower(var.project)}-${var.environment}-alerts"

  tags = {
    Name = "${var.project}-${var.environment}-alerts"
  }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --------------------------------------------------------------------------
# CloudWatch Log Groups (3-day retention; INFO/DEBUG ship to S3 via Vector)
# --------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "platform" {
  name              = "/aether/${var.project}-${var.environment}/platform"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project}-${var.environment}-platform-logs"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/aether/${var.project}-${var.environment}/app"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project}-${var.environment}-app-logs"
  }
}

resource "aws_cloudwatch_log_group" "ml" {
  name              = "/aether/${var.project}-${var.environment}/ml"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project}-${var.environment}-ml-logs"
  }
}

# --------------------------------------------------------------------------
# S3 Log Archive Bucket
# Creates the bucket only when var.log_archive_bucket is empty string.
# Otherwise callers provide their own bucket and we just reference it.
# --------------------------------------------------------------------------

resource "aws_s3_bucket" "log_archive" {
  count  = var.log_archive_bucket == "" ? 1 : 0
  bucket = "${lower(var.project)}-${var.environment}-log-archive-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${var.project}-${var.environment}-log-archive"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "log_archive" {
  count  = var.log_archive_bucket == "" ? 1 : 0
  bucket = aws_s3_bucket.log_archive[0].id

  rule {
    id     = "archive-logs"
    status = "Enabled"

    # Apply to all objects in the bucket. The empty filter prefix is required
    # by the AWS provider; without it a deprecation warning fires.
    filter {}

    # Move to Intelligent-Tiering immediately (handles automatic cold-tier move)
    transition {
      days          = 0
      storage_class = "INTELLIGENT_TIERING"
    }

    # Deep archive after 90 days
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }

    # Expire after 365 days
    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "log_archive" {
  count  = var.log_archive_bucket == "" ? 1 : 0
  bucket = aws_s3_bucket.log_archive[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "log_archive" {
  count  = var.log_archive_bucket == "" ? 1 : 0
  bucket = aws_s3_bucket.log_archive[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --------------------------------------------------------------------------
# Alarm 1: ALB 5xx Error Rate > 1%
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.project}-${var.environment}-alb-5xx-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_description = "ALB 5xx error rate exceeded 1% — likely application error or deployment issue"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "error_rate"
    expression  = "100 * errors / MAX([errors, 1])"
    label       = "5xx Error Rate (%)"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      metric_name = "HTTPCode_ELB_5XX_Count"
      namespace   = "AWS/ApplicationELB"
      period      = 60
      stat        = "Sum"
      dimensions = {
        LoadBalancer = var.alb_arn_suffix
      }
    }
  }

  tags = {
    Name = "${var.project}-${var.environment}-alb-5xx-alarm"
  }
}

# --------------------------------------------------------------------------
# Alarm 2: Aurora at max ACU for > 10 minutes
# Fires when the cluster has been pegged at max capacity for two consecutive
# 5-minute periods — indicating we may need to raise the max ACU floor.
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "aurora_max_acu" {
  count               = var.aurora_cluster_id == "" ? 0 : 1
  alarm_name          = "${var.project}-${var.environment}-aurora-max-acu"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2   # 2 × 5-min periods = 10 min sustained
  metric_name         = "ServerlessDatabaseCapacity"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Maximum"
  threshold           = var.aurora_max_acu

  dimensions = {
    DBClusterIdentifier = var.aurora_cluster_id
  }

  alarm_description = "Aurora Serverless v2 has been at max capacity (${var.aurora_max_acu} ACU) for >10 min — consider raising max_acu"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-aurora-max-acu-alarm"
  }
}

# --------------------------------------------------------------------------
# Alarm 3: ML Accuracy Drift PSI Breach
# The nightly drift Lambda publishes PSI scores to custom namespace
# "Aether/MLDrift" with metric "PSI" and dimension "Model=<name>".
# Alarm fires if any model's PSI exceeds 0.2 (significant drift threshold).
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ml_drift" {
  alarm_name          = "${var.project}-${var.environment}-ml-drift-psi"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "PSI"
  namespace           = "Aether/MLDrift"
  period              = 86400  # nightly Lambda publishes once per 24 h
  statistic           = "Maximum"
  threshold           = 0.2

  alarm_description = "ML model PSI drift score exceeded 0.2 — potential distribution shift requiring retraining"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-ml-drift-alarm"
  }
}

# --------------------------------------------------------------------------
# CloudWatch Dashboard
# Rows:
#   1. ECS (aether-app + aether-ml CPU/memory, ALB req/5xx)
#   2. Aurora (capacity ACU, connections, latency)
#   3. SageMaker Serverless (invocations per endpoint, model latency)
#   4. DynamoDB (throttles, consumed RCU/WCU)
# --------------------------------------------------------------------------

locals {
  # Aurora widgets are gated by `for ... if` so the result is a homogeneous
  # list type whether populated or empty. A naive `cond ? [] : [...]` fails
  # tuple-type unification in Terraform 1.7+.
  _aurora_widget_specs = [
    {
      x           = 0
      title       = "Aurora Serverless Capacity (ACU)"
      metric_name = "ServerlessDatabaseCapacity"
      stat        = "Maximum"
    },
    {
      x           = 8
      title       = "Aurora DB Connections"
      metric_name = "DatabaseConnections"
      stat        = "Average"
    },
  ]

  aurora_widgets = [
    for spec in local._aurora_widget_specs : {
      type   = "metric"
      x      = spec.x
      y      = 6
      width  = 8
      height = 6
      properties = {
        title  = spec.title
        view   = "timeSeries"
        region = data.aws_region.current.name
        metrics = [[
          "AWS/RDS", spec.metric_name,
          "DBClusterIdentifier", var.aurora_cluster_id,
          { stat = spec.stat }
        ]]
      }
    } if var.aurora_cluster_id != ""
  ]

  sm_endpoint_widgets = [
    for idx, ep_name in var.sagemaker_endpoint_names : {
      type   = "metric"
      x      = (idx % 3) * 8
      y      = 18 + floor(idx / 3) * 6
      width  = 8
      height = 6
      properties = {
        title  = "SageMaker Invocations — ${ep_name}"
        view   = "timeSeries"
        region = data.aws_region.current.name
        metrics = [
          [
            "AWS/SageMaker", "Invocations",
            "EndpointName", ep_name,
            { stat = "Sum", label = "Invocations" }
          ],
          [
            "AWS/SageMaker", "ModelLatency",
            "EndpointName", ep_name,
            { stat = "p99", label = "Model Latency p99 (us)", yAxis = "right" }
          ],
        ]
      }
    }
  ]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project}-${var.environment}"

  dashboard_body = jsonencode({
    widgets = concat(
      [
        # ── Row 1: ECS + ALB ──────────────────────────────────────────
        {
          type   = "metric"
          x      = 0
          y      = 0
          width  = 6
          height = 6
          properties = {
            title  = "aether-app CPU %"
            view   = "timeSeries"
            region = data.aws_region.current.name
            metrics = [[
              "AWS/ECS", "CPUUtilization",
              "ClusterName", var.ecs_cluster_name,
              "ServiceName", var.backend_service_name,
              { stat = "Average" }
            ]]
            yAxis = { left = { min = 0, max = 100 } }
          }
        },
        {
          type   = "metric"
          x      = 6
          y      = 0
          width  = 6
          height = 6
          properties = {
            title  = "aether-ml CPU %"
            view   = "timeSeries"
            region = data.aws_region.current.name
            metrics = [[
              "AWS/ECS", "CPUUtilization",
              "ClusterName", var.ecs_cluster_name,
              "ServiceName", var.ml_service_name,
              { stat = "Average" }
            ]]
            yAxis = { left = { min = 0, max = 100 } }
          }
        },
        {
          type   = "metric"
          x      = 12
          y      = 0
          width  = 6
          height = 6
          properties = {
            title  = "ALB Request Count"
            view   = "timeSeries"
            region = data.aws_region.current.name
            metrics = [[
              "AWS/ApplicationELB", "RequestCount",
              "LoadBalancer", var.alb_arn_suffix,
              { stat = "Sum" }
            ]]
          }
        },
        {
          type   = "metric"
          x      = 18
          y      = 0
          width  = 6
          height = 6
          properties = {
            title  = "ALB 5xx Errors"
            view   = "timeSeries"
            region = data.aws_region.current.name
            metrics = [[
              "AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count",
              "LoadBalancer", var.alb_arn_suffix,
              { stat = "Sum", color = "#d62728" }
            ]]
          }
        },
        # ── Row 3: DynamoDB ───────────────────────────────────────────
        # SEARCH expressions aggregate across all tables so no TableName
        # dimension is required. Without a dimension the bare metrics arrays
        # produce empty graphs because DynamoDB throttle events are per-table.
        {
          type   = "metric"
          x      = 0
          y      = 12
          width  = 8
          height = 6
          properties = {
            title  = "DynamoDB Read Throttles (all tables)"
            view   = "timeSeries"
            region = data.aws_region.current.name
            metrics = [[
              { expression = "SUM(SEARCH('{AWS/DynamoDB,TableName} MetricName=\"ReadThrottleEvents\"', 'Sum', 300))"
                id    = "read_throttles"
                label = "Read Throttles"
                color = "#d62728" }
            ]]
          }
        },
        {
          type   = "metric"
          x      = 8
          y      = 12
          width  = 8
          height = 6
          properties = {
            title  = "DynamoDB Write Throttles (all tables)"
            view   = "timeSeries"
            region = data.aws_region.current.name
            metrics = [[
              { expression = "SUM(SEARCH('{AWS/DynamoDB,TableName} MetricName=\"WriteThrottleEvents\"', 'Sum', 300))"
                id    = "write_throttles"
                label = "Write Throttles"
                color = "#d62728" }
            ]]
          }
        },
        {
          type   = "metric"
          x      = 16
          y      = 12
          width  = 8
          height = 6
          properties = {
            title  = "ML Drift PSI Score"
            view   = "timeSeries"
            region = data.aws_region.current.name
            metrics = [[
              "Aether/MLDrift", "PSI",
              { stat = "Maximum", label = "Max PSI (all models)" }
            ]]
            annotations = {
              horizontal = [{
                label = "Drift threshold"
                value = 0.2
                color = "#ff7f0e"
              }]
            }
          }
        },
      ],
      local.aurora_widgets,
      local.sm_endpoint_widgets
    )
  })
}
