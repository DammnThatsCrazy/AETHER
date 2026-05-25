# ============================================================================
# AETHER — SQS Module (E1: replaces MSK Kafka)
#
# Provisions:
#   - Dead-letter queue (aether-{env}-events-dlq)
#   - Main events queue (aether-{env}-events) with DLQ redrive policy
#   - SNS topic for fanout (aether-{env}-fanout)
#   - SNS → SQS subscription (allows broadcast to multiple consumers)
#   - SQS queue policy granting SNS publish access
# ============================================================================

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# --------------------------------------------------------------------------
# Dead-letter queue
# --------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  name                       = "${var.project}-${var.environment}-events-dlq"
  message_retention_seconds  = 1209600 # 14 days
  visibility_timeout_seconds = 30

  tags = {
    Name = "${var.project}-${var.environment}-events-dlq"
  }
}

# --------------------------------------------------------------------------
# Main events queue
# --------------------------------------------------------------------------

resource "aws_sqs_queue" "events" {
  name                       = "${var.project}-${var.environment}-events"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  receive_wait_time_seconds  = 20 # long-poll to reduce empty receives

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = {
    Name = "${var.project}-${var.environment}-events-queue"
  }
}

# --------------------------------------------------------------------------
# SNS fanout topic
# --------------------------------------------------------------------------

resource "aws_sns_topic" "fanout" {
  name = "${var.project}-${var.environment}-fanout"

  tags = {
    Name = "${var.project}-${var.environment}-fanout-topic"
  }
}

# --------------------------------------------------------------------------
# SNS → SQS subscription
# --------------------------------------------------------------------------

resource "aws_sns_topic_subscription" "events" {
  topic_arn = aws_sns_topic.fanout.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.events.arn

  # Unwrap the SNS envelope so consumers see the original message body
  raw_message_delivery = true
}

# --------------------------------------------------------------------------
# SQS queue policy: allow SNS and ECS tasks to send/receive
# --------------------------------------------------------------------------

resource "aws_sqs_queue_policy" "events" {
  queue_url = aws_sqs_queue.events.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowSNSPublish"
        Effect = "Allow"
        Principal = {
          Service = "sns.amazonaws.com"
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.events.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = aws_sns_topic.fanout.arn
          }
        }
      },
    ]
  })
}
