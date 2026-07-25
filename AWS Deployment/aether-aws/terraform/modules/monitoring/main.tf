# ============================================================================
# AETHER — Monitoring Module (E6 cost reduction)
#
# Provisions (budget-optimised):
#   - CloudWatch log groups (3-day retention; longer retention → S3 archive)
#   - S3 log archive bucket (IT storage class; Glacier IR after 90 days)
#   - SNS topic for alarm notifications
#   - CloudWatch alarms (always on):
#       1. ALB 5xx error rate > 1%
#       2. Aurora at max ACU for > 10 min (capacity ceiling alert)
#       3. ML accuracy drift PSI breach (custom metric from nightly drift Lambda)
#     Lean-profile backends (created once the caller passes the identifier):
#       4. DynamoDB cache table throttling
#       5. SQS backlog depth
#       6. SQS oldest-message age
#       7. SQS dead-letter queue depth
#     Cost-gated components (created only when their enable_* toggle is on):
#       8. ElastiCache memory pressure
#       9. MSK offline partitions
#      10. Neptune CPU saturation
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
  evaluation_periods  = 2 # 2 × 5-min periods = 10 min sustained
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
  period              = 86400 # nightly Lambda publishes once per 24 h
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
# Alarm 4: DynamoDB cache throttling
# The lean profile replaces ElastiCache with the DynamoDB cache table, so
# throttles on that table are the cache-degradation signal.
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "dynamodb_cache_throttled" {
  count               = var.dynamodb_cache_table_name == "" ? 0 : 1
  alarm_name          = "${var.project}-${var.environment}-dynamodb-cache-throttled"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 0
  treat_missing_data  = "notBreaching"

  alarm_description = "DynamoDB cache table ${var.dynamodb_cache_table_name} is throttling requests — the cache backend is degraded"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "throttled"
    expression  = "reads + writes"
    label       = "Throttled cache requests"
    return_data = true
  }

  metric_query {
    id = "reads"
    metric {
      metric_name = "ReadThrottleEvents"
      namespace   = "AWS/DynamoDB"
      period      = 300
      stat        = "Sum"
      dimensions = {
        TableName = var.dynamodb_cache_table_name
      }
    }
  }

  metric_query {
    id = "writes"
    metric {
      metric_name = "WriteThrottleEvents"
      namespace   = "AWS/DynamoDB"
      period      = 300
      stat        = "Sum"
      dimensions = {
        TableName = var.dynamodb_cache_table_name
      }
    }
  }

  tags = {
    Name = "${var.project}-${var.environment}-dynamodb-cache-throttled-alarm"
  }
}

# --------------------------------------------------------------------------
# Alarm 5: SQS backlog depth
# The lean profile replaces MSK with SQS, so a growing visible-message count
# is the consumer-capacity signal Kafka lag used to provide.
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "sqs_queue_depth" {
  count               = var.sqs_queue_name == "" ? 0 : 1
  alarm_name          = "${var.project}-${var.environment}-sqs-queue-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = var.sqs_queue_depth_threshold

  dimensions = {
    QueueName = var.sqs_queue_name
  }

  alarm_description = "SQS events queue backlog exceeded ${var.sqs_queue_depth_threshold} visible messages — consumers are falling behind"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-sqs-queue-depth-alarm"
  }
}

# --------------------------------------------------------------------------
# Alarm 6: SQS oldest-message age
# Depth alone misses a small-but-stuck queue; age catches a stalled consumer.
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "sqs_oldest_message_age" {
  count               = var.sqs_queue_name == "" ? 0 : 1
  alarm_name          = "${var.project}-${var.environment}-sqs-oldest-message-age"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = var.sqs_oldest_message_age_threshold

  dimensions = {
    QueueName = var.sqs_queue_name
  }

  alarm_description = "Oldest SQS message is older than ${var.sqs_oldest_message_age_threshold}s — a consumer role is stalled or crash-looping"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-sqs-oldest-message-age-alarm"
  }
}

# --------------------------------------------------------------------------
# Alarm 7: SQS dead-letter queue depth
# Any message on the DLQ means events were dropped after every retry.
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "sqs_dlq_depth" {
  count               = var.sqs_dlq_name == "" ? 0 : 1
  alarm_name          = "${var.project}-${var.environment}-sqs-dlq-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0

  dimensions = {
    QueueName = var.sqs_dlq_name
  }

  alarm_description = "Messages landed on the SQS dead-letter queue — events were dropped after exhausting retries"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-sqs-dlq-depth-alarm"
  }
}

# --------------------------------------------------------------------------
# Alarms 8-10: cost-gated components
# These only exist in profiles that provision the component, so a lean plan
# never creates an alarm pointing at a resource that was never created.
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "elasticache_memory" {
  count               = var.enable_elasticache && var.elasticache_replication_group_id != "" ? 1 : 0
  alarm_name          = "${var.project}-${var.environment}-elasticache-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseMemoryUsagePercentage"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Maximum"
  threshold           = 90

  dimensions = {
    ReplicationGroupId = var.elasticache_replication_group_id
  }

  alarm_description = "ElastiCache Redis memory usage above 90% — evictions are imminent"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-elasticache-memory-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "msk_offline_partitions" {
  count               = var.enable_msk && var.msk_cluster_name != "" ? 1 : 0
  alarm_name          = "${var.project}-${var.environment}-msk-offline-partitions"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "OfflinePartitionsCount"
  namespace           = "AWS/Kafka"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0

  dimensions = {
    "Cluster Name" = var.msk_cluster_name
  }

  alarm_description = "MSK has offline partitions — Kafka topics are unavailable for produce/consume"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-msk-offline-partitions-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "neptune_cpu" {
  count               = var.enable_neptune && var.neptune_cluster_id != "" ? 1 : 0
  alarm_name          = "${var.project}-${var.environment}-neptune-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/Neptune"
  period              = 300
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    DBClusterIdentifier = var.neptune_cluster_id
  }

  alarm_description = "Neptune cluster CPU above 80% for 15 min — graph queries are saturating the writer"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-neptune-cpu-alarm"
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

  # The dedicated aether-ml ECS service only exists when the profile enables
  # it; iterating a conditionally-empty list keeps the result a homogeneous
  # list type, the same idiom used by aurora_widgets above.
  ml_service_widgets = [
    for service_name in(var.enable_dedicated_ml ? [var.ml_service_name] : []) : {
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
          "ServiceName", service_name,
          { stat = "Average" }
        ]]
        yAxis = { left = { min = 0, max = 100 } }
      }
    }
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

  # DynamoDB throttle widgets. Throttle events are emitted per-table with a
  # TableName dimension, so a bare `["AWS/DynamoDB", "ReadThrottleEvents"]`
  # array renders an empty graph. We support two modes:
  #
  #   1. When dynamodb_table_names is populated, render one widget per table
  #      with the explicit TableName dimension so individual hot tables stand
  #      out in the dashboard.
  #   2. When dynamodb_table_names is empty, fall back to a single aggregate
  #      widget per metric using a SEARCH metric-math expression that scans
  #      across every table with the TableName dimension.
  #
  # `for ... if` filters keep both branches as a homogeneous list type so
  # concat() in the dashboard body type-checks cleanly under Terraform 1.7+.
  _dynamo_per_table_widgets = concat(
    [
      for idx, tn in var.dynamodb_table_names : {
        type   = "metric"
        x      = (idx % 2) * 12
        y      = 12 + floor(idx / 2) * 6
        width  = 12
        height = 6
        properties = {
          title  = "DynamoDB Throttles — ${tn}"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            [
              "AWS/DynamoDB", "ReadThrottleEvents",
              "TableName", tn,
              { stat = "Sum", label = "Read", color = "#d62728" }
            ],
            [
              "AWS/DynamoDB", "WriteThrottleEvents",
              "TableName", tn,
              { stat = "Sum", label = "Write", color = "#ff7f0e" }
            ],
          ]
        }
      }
    ],
  )

  _dynamo_aggregate_widgets = [
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
            id         = "read_throttles"
            label      = "Read Throttles"
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
            id         = "write_throttles"
            label      = "Write Throttles"
          color = "#d62728" }
        ]]
      }
    },
  ]

  # Each branch is jsondecode(jsonencode(...))-wrapped BEFORE the conditional
  # so both sides resolve to `any` and the ?: operator sees a single type.
  # The two branches' metrics arrays have different inner shapes (4-element
  # legacy arrays vs. single-element metric-math objects), which otherwise
  # trips tuple-element type unification under Terraform 1.7+.
  dynamo_widgets = (
    length(var.dynamodb_table_names) > 0
    ? jsondecode(jsonencode(local._dynamo_per_table_widgets))
    : jsondecode(jsonencode(local._dynamo_aggregate_widgets))
  )
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
        # ── Row 3: ML Drift (DynamoDB widgets come from local.dynamo_widgets) ─
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
      local.ml_service_widgets,
      local.dynamo_widgets,
      local.aurora_widgets,
      local.sm_endpoint_widgets
    )
  })
}
