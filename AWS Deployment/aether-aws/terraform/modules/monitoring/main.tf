# ============================================================================
# AETHER — Monitoring Module
#
# Provisions:
#   - CloudWatch log groups (30-day retention)
#   - SNS topic for alarm notifications
#   - CloudWatch alarms:
#       ECS backend CPU > 80%
#       ECS backend Memory > 80%
#       ECS ml-serving CPU > 80%
#       ECS ml-serving Memory > 80%
#       RDS CPU > 80%
#       RDS FreeStorageSpace < 10 GB
#       ALB 5xx error rate > 1%
#       ALB p99 latency > 5 seconds
#   - CloudWatch Dashboard "AETHER-Production"
# ============================================================================

data "aws_region" "current" {}

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
# CloudWatch Log Group — application (ECS logs created by ECS module;
# this log group is for the platform / infra layer)
# --------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "platform" {
  name              = "/aether/${var.project}-${var.environment}/platform"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project}-${var.environment}-platform-logs"
  }
}

# --------------------------------------------------------------------------
# Alarms — ECS Backend
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ecs_backend_cpu" {
  alarm_name          = "${var.project}-${var.environment}-backend-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.backend_service_name
  }

  alarm_description = "ECS backend CPU utilization exceeded 80%"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-backend-cpu-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "ecs_backend_memory" {
  alarm_name          = "${var.project}-${var.environment}-backend-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.backend_service_name
  }

  alarm_description = "ECS backend Memory utilization exceeded 80%"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-backend-memory-alarm"
  }
}

# --------------------------------------------------------------------------
# Alarms — ECS ML Serving
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ecs_ml_cpu" {
  alarm_name          = "${var.project}-${var.environment}-ml-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ml_service_name
  }

  alarm_description = "ECS ml-serving CPU utilization exceeded 80%"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-ml-cpu-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "ecs_ml_memory" {
  alarm_name          = "${var.project}-${var.environment}-ml-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 60
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ml_service_name
  }

  alarm_description = "ECS ml-serving Memory utilization exceeded 80%"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-ml-memory-alarm"
  }
}

# --------------------------------------------------------------------------
# Alarms — RDS
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${var.project}-${var.environment}-rds-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Average"
  threshold           = 80

  dimensions = {
    DBInstanceIdentifier = var.rds_identifier
  }

  alarm_description = "RDS CPU utilization exceeded 80%"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-rds-cpu-alarm"
  }
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name          = "${var.project}-${var.environment}-rds-storage-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  # 10 GB in bytes
  threshold = 10737418240

  dimensions = {
    DBInstanceIdentifier = var.rds_identifier
  }

  alarm_description = "RDS free storage space below 10 GB"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-rds-storage-alarm"
  }
}

# --------------------------------------------------------------------------
# Alarms — ALB
# --------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.project}-${var.environment}-alb-5xx-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_description = "ALB 5xx error rate exceeded 1%"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "error_rate"
    expression  = "100 * errors / MAX([requests, 1])"
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

  metric_query {
    id = "requests"
    metric {
      metric_name = "RequestCount"
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

resource "aws_cloudwatch_metric_alarm" "alb_latency_p99" {
  alarm_name          = "${var.project}-${var.environment}-alb-latency-p99"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p99"
  threshold           = 5

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }

  alarm_description = "ALB p99 response time exceeded 5 seconds"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  ok_actions        = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name = "${var.project}-${var.environment}-alb-latency-alarm"
  }
}

# --------------------------------------------------------------------------
# CloudWatch Dashboard
# --------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project}-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      # Row 1: ECS Backend
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 8
        height = 6
        properties = {
          title  = "ECS Backend CPU"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [[
            "AWS/ECS", "CPUUtilization",
            "ClusterName", var.ecs_cluster_name,
            "ServiceName", var.backend_service_name,
            { stat = "Average", label = "CPU %" }
          ]]
          yAxis = { left = { min = 0, max = 100 } }
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 0
        width  = 8
        height = 6
        properties = {
          title  = "ECS Backend Memory"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [[
            "AWS/ECS", "MemoryUtilization",
            "ClusterName", var.ecs_cluster_name,
            "ServiceName", var.backend_service_name,
            { stat = "Average", label = "Memory %" }
          ]]
          yAxis = { left = { min = 0, max = 100 } }
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          title  = "ECS ML Serving CPU"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [[
            "AWS/ECS", "CPUUtilization",
            "ClusterName", var.ecs_cluster_name,
            "ServiceName", var.ml_service_name,
            { stat = "Average", label = "CPU %" }
          ]]
          yAxis = { left = { min = 0, max = 100 } }
        }
      },
      # Row 2: RDS
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "RDS CPU"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [[
            "AWS/RDS", "CPUUtilization",
            "DBInstanceIdentifier", var.rds_identifier,
            { stat = "Average", label = "CPU %" }
          ]]
          yAxis = { left = { min = 0, max = 100 } }
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "RDS Free Storage (GB)"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [[
            "AWS/RDS", "FreeStorageSpace",
            "DBInstanceIdentifier", var.rds_identifier,
            { stat = "Average", label = "Free Storage Bytes" }
          ]]
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "RDS Connections"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [[
            "AWS/RDS", "DatabaseConnections",
            "DBInstanceIdentifier", var.rds_identifier,
            { stat = "Average", label = "Connections" }
          ]]
        }
      },
      # Row 3: ALB
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 8
        height = 6
        properties = {
          title  = "ALB Request Count"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [[
            "AWS/ApplicationELB", "RequestCount",
            "LoadBalancer", var.alb_arn_suffix,
            { stat = "Sum", label = "Requests" }
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
          title  = "ALB 5xx Errors"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [[
            "AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count",
            "LoadBalancer", var.alb_arn_suffix,
            { stat = "Sum", label = "5xx Count" }
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
          title  = "ALB Target Response Time p99"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [[
            "AWS/ApplicationELB", "TargetResponseTime",
            "LoadBalancer", var.alb_arn_suffix,
            { stat = "p99", label = "p99 Latency (s)" }
          ]]
        }
      },
    ]
  })
}
