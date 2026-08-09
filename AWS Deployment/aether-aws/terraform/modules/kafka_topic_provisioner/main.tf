# ============================================================================
# AETHER — Kafka Topic Provisioner Module
#
# MSK is configured with auto.create.topics.enable=false (modules/msk), so no
# topic ever appears by magic: every topic the runtime publishes/consumes must
# exist before the first producer connects. The declared topic set lives in
# shared/events/events.py (enum Topic), is emitted to deploy/kafka/topics.json
# by deploy/kafka (regeneration verified by its drift test), and this module
# turns that registry into a Lambda that creates the topics against the
# freshly-provisioned MSK cluster at apply time.
#
# The Lambda is triggered once by aws_lambda_invocation with depends_on on the
# MSK cluster, so topic creation happens exactly after the brokers are reachable
# and before any task can publish. It is idempotent (TopicAlreadyExistsError is
# a no-op), so re-runs and partial failures converge.
#
# The source is the single source of truth at deploy/kafka (repo root), zipped
# by the archive provider. The dependency bundle (kafka-python + certifi) is
# prepared into that directory by the release pipeline before apply — see
# deploy/kafka/README.md "Packaging" — because archive_file only archives what
# is already on disk and offline plans must never need a network fetch.
#
# VPC placement: the Lambda ENI joins the ECS security group and a private
# subnet, so the brokers' ingress rule (which sources the ECS SG on TLS 9094)
# accepts its connections, and the profile's NAT Gateway provides the
# CloudWatch/logs egress the Lambda needs.
# ============================================================================

data "aws_region" "current" {}

# --------------------------------------------------------------------------
# Package deploy/kafka (topic_provisioner.py, lambda_handler.py, topics.json,
# deps/) into the Lambda zip. The path walks five levels up from the module
# directory to the repo root; the release pipeline pre-bundles dependencies.
# --------------------------------------------------------------------------

data "archive_file" "topic_provisioner" {
  type        = "zip"
  source_dir  = "${path.module}/../../../../../deploy/kafka"
  output_path = "${path.module}/.build/topic_provisioner.zip"
  excludes    = ["tests", "tests/*", "README.md"]
}

# --------------------------------------------------------------------------
# IAM — Lambda execution (logs) + VPC ENI management.
# --------------------------------------------------------------------------

resource "aws_iam_role" "topic_provisioner" {
  name = "${var.project}-${var.environment}-kafka-topic-provisioner"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${var.project}-${var.environment}-kafka-topic-provisioner-role"
  }
}

resource "aws_iam_role_policy_attachment" "topic_provisioner_basic" {
  role       = aws_iam_role.topic_provisioner.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "topic_provisioner_vpc" {
  role       = aws_iam_role.topic_provisioner.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# --------------------------------------------------------------------------
# Lambda function
# --------------------------------------------------------------------------

resource "aws_lambda_function" "topic_provisioner" {
  function_name    = "${var.project}-${var.environment}-kafka-topic-provisioner"
  role             = aws_iam_role.topic_provisioner.arn
  handler          = "lambda_handler.handler"
  runtime          = "python3.12"
  timeout          = var.lambda_timeout_seconds
  memory_size      = var.lambda_memory_mb
  filename         = data.archive_file.topic_provisioner.output_path
  source_code_hash = data.archive_file.topic_provisioner.output_base64sha256

  environment {
    variables = {
      KAFKA_BOOTSTRAP_SERVERS        = var.bootstrap_servers
      KAFKA_TOPICS_FILE              = "topics.json"
      KAFKA_TOPIC_PARTITIONS         = tostring(var.topic_partitions)
      KAFKA_TOPIC_REPLICATION_FACTOR = tostring(var.topic_replication_factor)
      KAFKA_TOPIC_CREATE_TIMEOUT_MS  = tostring(var.topic_create_timeout_ms)
    }
  }

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.lambda_security_group_id]
  }

  tags = {
    Name = "${var.project}-${var.environment}-kafka-topic-provisioner"
  }
}

resource "aws_cloudwatch_log_group" "topic_provisioner" {
  name              = "/aws/lambda/${aws_lambda_function.topic_provisioner.function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name = "${var.project}-${var.environment}-kafka-topic-provisioner-logs"
  }
}

# --------------------------------------------------------------------------
# One-shot invocation — runs after the MSK cluster exists, creates every topic
# declared in the registry. Idempotent, so safe to re-run.
# --------------------------------------------------------------------------

resource "aws_lambda_invocation" "provision_topics" {
  function_name = aws_lambda_function.topic_provisioner.function_name
  # depends_on is deliberately NOT set to a resource inside this module: the
  # caller (root main.tf) sets depends_on = [module.msk] so the invocation
  # cannot fire before the cluster is reachable.
  input = jsonencode({
    bootstrap_servers  = var.bootstrap_servers
    topics_file        = "topics.json"
    partitions         = var.topic_partitions
    replication_factor = var.topic_replication_factor
    timeout_ms         = var.topic_create_timeout_ms
  })

  lifecycle {
    # Re-invoke only when the registry/payload/topics change, never on every
    # apply (the Lambda is idempotent, but pointless re-runs cost time).
    replace_triggered_by = [
      aws_lambda_function.topic_provisioner.source_code_hash,
    ]
  }
}
