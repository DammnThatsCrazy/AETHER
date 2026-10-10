# ============================================================================
# AETHER — DynamoDB Cache Module (E1: replaces ElastiCache Redis)
#
# Provisions:
#   - On-Demand DynamoDB table for shared cache state (quota counters,
#     idempotency keys, session cache, rate-limit sliding windows)
#   - TTL attribute enabled so items expire automatically
#   - Optional provisioned + autoscale path via var.use_provisioned_capacity
# ============================================================================

resource "aws_dynamodb_table" "cache" {
  name         = "${var.project}-${var.environment}-cache"
  billing_mode = var.use_provisioned_capacity ? "PROVISIONED" : "PAY_PER_REQUEST"

  # When PAY_PER_REQUEST, read/write capacity must be unset (null). When
  # PROVISIONED, both must be > 0. aws_dynamodb_table uses these as
  # top-level args (not a provisioned_throughput nested block).
  read_capacity  = var.use_provisioned_capacity ? var.read_capacity : null
  write_capacity = var.use_provisioned_capacity ? var.write_capacity : null

  hash_key = "cache_key"

  attribute {
    name = "cache_key"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  # Point-in-time recovery is cheap insurance; ~$0.20/GB/month
  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name = "${var.project}-${var.environment}-cache"
  }
}

# --------------------------------------------------------------------------
# Autoscaling — only when provisioned capacity is used
# --------------------------------------------------------------------------

resource "aws_appautoscaling_target" "read" {
  count              = var.use_provisioned_capacity ? 1 : 0
  max_capacity       = var.max_read_capacity
  min_capacity       = var.read_capacity
  resource_id        = "table/${aws_dynamodb_table.cache.name}"
  scalable_dimension = "dynamodb:table:ReadCapacityUnits"
  service_namespace  = "dynamodb"
}

resource "aws_appautoscaling_target" "write" {
  count              = var.use_provisioned_capacity ? 1 : 0
  max_capacity       = var.max_write_capacity
  min_capacity       = var.write_capacity
  resource_id        = "table/${aws_dynamodb_table.cache.name}"
  scalable_dimension = "dynamodb:table:WriteCapacityUnits"
  service_namespace  = "dynamodb"
}

resource "aws_appautoscaling_policy" "read" {
  count              = var.use_provisioned_capacity ? 1 : 0
  name               = "${var.project}-${var.environment}-cache-read-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.read[0].resource_id
  scalable_dimension = aws_appautoscaling_target.read[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.read[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "DynamoDBReadCapacityUtilization"
    }
    target_value = 80.0
  }
}

resource "aws_appautoscaling_policy" "write" {
  count              = var.use_provisioned_capacity ? 1 : 0
  name               = "${var.project}-${var.environment}-cache-write-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.write[0].resource_id
  scalable_dimension = aws_appautoscaling_target.write[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.write[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "DynamoDBWriteCapacityUtilization"
    }
    target_value = 80.0
  }
}
