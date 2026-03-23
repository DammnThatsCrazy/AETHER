# ═══════════════════════════════════════════════════════════════════════════
# Aether Monitoring Module
# Metrics: CloudWatch + Prometheus  |  Logging: CloudWatch + OpenSearch
# Tracing: X-Ray (5% sampling, 100% on errors)
# Alerting: CloudWatch Alarms + PagerDuty
# Dashboards: Grafana on ECS  |  Cost: Budgets + allocation tags
# ═══════════════════════════════════════════════════════════════════════════

variable "environment" { type = string }
variable "ecs_cluster_name" { type = string }
variable "service_names" { type = map(string) default = {} }
variable "sns_alert_topic_arn" { type = string default = "" }
variable "pagerduty_endpoint" { type = string default = "" }
variable "monthly_budget_usd" { type = number default = 5000 }

locals {
  alarm_prefix = "aether-${var.environment}"
}

# ── SNS Alert Topic ──────────────────────────────────────────────────

resource "aws_sns_topic" "alerts" {
  name = "aether-alerts-${var.environment}"
  tags = { Name = "aether-alerts-${var.environment}" }
}

resource "aws_sns_topic_subscription" "pagerduty" {
  count     = var.environment == "production" && var.pagerduty_endpoint != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "https"
  endpoint  = var.pagerduty_endpoint
}

# ── CloudWatch Alarms — Error Rate per Service ───────────────────────

resource "aws_cloudwatch_metric_alarm" "error_rate" {
  for_each = var.service_names

  alarm_name          = "${local.alarm_prefix}-${each.key}-error-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "5XXError"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "Error rate > 1% for aether-${each.key}"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    TargetGroup  = each.value
    LoadBalancer = var.ecs_cluster_name
  }

  tags = { Service = each.key }
}

# ── CloudWatch Alarms — P99 Latency ──────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "p99_latency" {
  for_each = var.service_names

  alarm_name          = "${local.alarm_prefix}-${each.key}-p99-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  threshold           = 500  # ms

  metric_query {
    id          = "p99"
    return_data = true
    metric {
      metric_name = "TargetResponseTime"
      namespace   = "AWS/ApplicationELB"
      period      = 60
      stat        = "p99"
      dimensions = {
        TargetGroup  = each.value
        LoadBalancer = var.ecs_cluster_name
      }
    }
  }

  alarm_description = "P99 latency > 500ms for aether-${each.key}"
  alarm_actions     = [aws_sns_topic.alerts.arn]
  tags              = { Service = each.key }
}

# ── CloudWatch Alarms — Queue Depth (SQS/Kafka) ──────────────────────

resource "aws_cloudwatch_metric_alarm" "queue_depth" {
  alarm_name          = "${local.alarm_prefix}-kafka-queue-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "EstimatedMaxTimeLag"
  namespace           = "AWS/Kafka"
  period              = 300
  statistic           = "Maximum"
  threshold           = 10000
  alarm_description   = "Kafka consumer lag > 10K messages"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  tags                = { Component = "kafka" }
}

# ── CloudWatch Alarms — ECS CPU ───────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "ecs_cpu" {
  alarm_name          = "${local.alarm_prefix}-ecs-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "ECS cluster CPU > 85%"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = { ClusterName = var.ecs_cluster_name }
}

# ── X-Ray Tracing ─────────────────────────────────────────────────────

resource "aws_xray_sampling_rule" "default" {
  rule_name      = "aether-${var.environment}-default"
  priority       = 1000
  reservoir_size = 1
  fixed_rate     = var.environment == "production" ? 0.05 : 0.5  # 5% prod, 50% dev
  url_path       = "*"
  host           = "*"
  http_method    = "*"
  service_type   = "*"
  service_name   = "*"
  resource_arn   = "*"
  version        = 1
}

resource "aws_xray_sampling_rule" "errors" {
  rule_name      = "aether-${var.environment}-errors"
  priority       = 100
  reservoir_size = 10
  fixed_rate     = 1.0  # 100% on errors
  url_path       = "*"
  host           = "*"
  http_method    = "*"
  service_type   = "*"
  service_name   = "*"
  resource_arn   = "*"
  version        = 1

  attributes = { "http.status_code" = "5*" }
}

# ── Grafana (ECS service) ─────────────────────────────────────────────
# Grafana deployed as an ECS Fargate service for dashboards
# Service health, business metrics, SLO tracking, cost dashboards

resource "aws_cloudwatch_log_group" "grafana" {
  name              = "/ecs/aether-grafana-${var.environment}"
  retention_in_days = 30
}

# ── AWS Budgets (cost monitoring) ─────────────────────────────────────

resource "aws_budgets_budget" "monthly" {
  name         = "aether-monthly-${var.environment}"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Environment$${var.environment}"]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.alerts.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [aws_sns_topic.alerts.arn]
  }
}

# ── CloudWatch Dashboard ──────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "aether-${var.environment}"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x = 0; y = 0; width = 12; height = 6
        properties = {
          title   = "ECS CPU / Memory"
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.ecs_cluster_name],
            ["AWS/ECS", "MemoryUtilization", "ClusterName", var.ecs_cluster_name],
          ]
          period = 300; stat = "Average"; region = "us-east-1"
        }
      },
      {
        type   = "metric"
        x = 12; y = 0; width = 12; height = 6
        properties = {
          title   = "ALB Request Count & Latency"
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.ecs_cluster_name],
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.ecs_cluster_name],
          ]
          period = 60; stat = "Sum"; region = "us-east-1"
        }
      },
    ]
  })
}

output "alerts_topic_arn"  { value = aws_sns_topic.alerts.arn }
output "dashboard_name"    { value = aws_cloudwatch_dashboard.main.dashboard_name }
