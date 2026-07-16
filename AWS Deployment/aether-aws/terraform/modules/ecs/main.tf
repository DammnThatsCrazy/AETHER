# ============================================================================
# AETHER — ECS Fargate Module
#
# Provisions:
#   - ECS cluster (Fargate + Fargate Spot capacity providers)
#   - Task execution IAM role (ECR pull, Secrets Manager, CloudWatch)
#   - Task role (application permissions)
#   - Task definitions for: aether-backend, aether-ml-serving
#   - ECS services with ALB target group registration
#   - Application Auto Scaling (CPU-based, 70% threshold)
#   - CloudWatch log groups per service
# ============================================================================

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# --------------------------------------------------------------------------
# CloudWatch Log Groups
# --------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.project}-${var.environment}/aether-backend"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "${var.project}-${var.environment}-backend-logs"
    Service = "aether-backend"
  }
}

resource "aws_cloudwatch_log_group" "ml" {
  name              = "/ecs/${var.project}-${var.environment}/aether-ml-serving"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "${var.project}-${var.environment}-ml-logs"
    Service = "aether-ml-serving"
  }
}

resource "aws_cloudwatch_log_group" "runtime_role" {
  for_each          = var.runtime_roles
  name              = "/ecs/${var.project}-${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days
  tags = { Service = each.key }
}

# --------------------------------------------------------------------------
# ECS Cluster
# --------------------------------------------------------------------------

resource "aws_ecs_cluster" "this" {
  name = "${var.project}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project}-${var.environment}-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name = aws_ecs_cluster.this.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# --------------------------------------------------------------------------
# IAM — Task Execution Role
# (Used by the ECS agent to pull images and send logs)
# --------------------------------------------------------------------------

resource "aws_iam_role" "execution" {
  name = "${var.project}-${var.environment}-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${var.project}-${var.environment}-ecs-execution-role"
  }
}

resource "aws_iam_role_policy_attachment" "execution_base" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "${var.project}-${var.environment}-ecs-execution-secrets"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret",
        ]
        Resource = concat(
          [for arn in values(var.secret_arns) : arn],
          [for arn in values(var.companion_secret_arns) : arn],
        )
      },
      {
        Sid    = "KMSDecrypt"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "*"
      },
    ]
  })
}

# --------------------------------------------------------------------------
# IAM — Task Role
# (Used by the application code itself)
# --------------------------------------------------------------------------

resource "aws_iam_role" "task" {
  name = "${var.project}-${var.environment}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${var.project}-${var.environment}-ecs-task-role"
  }
}

locals {
  sqs_statements = var.sqs_queue_arn != "" ? [
    {
      Sid    = "SQSEventsAccess"
      Effect = "Allow"
      Action = [
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl",
        "sqs:ChangeMessageVisibility",
      ]
      Resource = var.sqs_queue_arn
    }
  ] : []

  dynamodb_statements = var.dynamodb_cache_table_arn != "" ? [
    {
      Sid    = "DynamoDBCacheAccess"
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:BatchGetItem",
        "dynamodb:BatchWriteItem",
      ]
      Resource = var.dynamodb_cache_table_arn
    }
  ] : []
}

resource "aws_iam_role_policy" "task" {
  name = "${var.project}-${var.environment}-ecs-task-policy"
  role = aws_iam_role.task.id

  # The base statements have mixed Resource types (string vs list of strings),
  # and the sqs/dynamo statements only have string Resources. Wrapping each
  # operand in jsondecode(jsonencode(...)) coerces them to `any` so concat()
  # doesn't trip Terraform 1.7+ tuple element type unification.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      jsondecode(jsonencode([
        {
          Sid    = "CloudWatchMetrics"
          Effect = "Allow"
          Action = [
            "cloudwatch:PutMetricData",
            "cloudwatch:GetMetricStatistics",
            "cloudwatch:ListMetrics",
          ]
          Resource = "*"
        },
        {
          Sid    = "SecretsManagerRead"
          Effect = "Allow"
          Action = [
            "secretsmanager:GetSecretValue",
          ]
          Resource = concat(
            [for arn in values(var.secret_arns) : arn],
            [for arn in values(var.companion_secret_arns) : arn],
          )
        },
        {
          Sid    = "NeptuneIAMAuth"
          Effect = "Allow"
          Action = [
            "neptune-db:*",
          ]
          Resource = "arn:aws:neptune-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*/*"
        },
      ])),
      jsondecode(jsonencode(local.sqs_statements)),
      jsondecode(jsonencode(local.dynamodb_statements)),
    )
  })
}

# --------------------------------------------------------------------------
# Helpers — build the `secrets` block for task definitions
# --------------------------------------------------------------------------

locals {
  # Secret name → container env var name mapping for backend
  backend_secrets = merge(
    {
      JWT_SECRET                = var.secret_arns["jwt-secret"]
      BYOK_ENCRYPTION_KEY       = var.secret_arns["byok-encryption-key"]
      DATABASE_URL_SECRET       = var.secret_arns["db-password"]
      STRIPE_SECRET_KEY         = var.secret_arns["stripe-secret-key"]
      STRIPE_WEBHOOK_SECRET     = var.secret_arns["stripe-webhook-secret"]
      ORACLE_SIGNER_PRIVATE_KEY = var.secret_arns["oracle-signer-private-key"]
      WATERMARK_SECRET_KEY      = var.secret_arns["watermark-secret-key"]
      CANARY_SECRET_SEED        = var.secret_arns["canary-secret-seed"]
      # Redis AUTH token — read by shared/cache/cache.py as REDIS_PASSWORD
      REDIS_PASSWORD            = var.secret_arns["redis-auth-token"]
    },
    # Companion secrets for zero-downtime rotation window.
    # Populated by the rotation Lambda in setSecret phase; empty until first rotation.
    lookup(var.companion_secret_arns, "jwt-secret-previous", null) != null ? {
      JWT_SECRET_PREVIOUS = var.companion_secret_arns["jwt-secret-previous"]
    } : {},
    lookup(var.companion_secret_arns, "byok-encryption-key-previous", null) != null ? {
      BYOK_ENCRYPTION_KEY_PREVIOUS = var.companion_secret_arns["byok-encryption-key-previous"]
    } : {},
  )

  backend_secrets_block = [for env_var, arn in local.backend_secrets : {
    name      = env_var
    valueFrom = arn
  }]

  ml_secrets_block = [
    {
      name      = "JWT_SECRET"
      valueFrom = var.secret_arns["jwt-secret"]
    },
  ]
}

# --------------------------------------------------------------------------
# Task Definition — aether-backend
# --------------------------------------------------------------------------

resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.project}-${var.environment}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.backend_cpu
  memory                   = var.backend_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "aether-backend"
      image     = "${var.ecr_backend_url}@${var.backend_image_digest}"
      essential = true

      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]

      environment = concat(
        [
          { name = "APP_ENV",           value = var.environment },
          { name = "AETHER_ENV",        value = var.environment },
          { name = "PORT",              value = "8000" },
          { name = "LOG_LEVEL",         value = var.environment == "production" ? "INFO" : "DEBUG" },
          { name = "NEPTUNE_ENDPOINT",  value = var.neptune_endpoint },
          { name = "ML_SERVING_URL",    value = var.ml_serving_url },
          { name = "ML_SERVING_INLINE", value = var.ml_serving_inline ? "true" : "false" },
        ],
        # SQS event broker — set when sqs_queue_url is provided; otherwise Kafka
        var.sqs_queue_url != "" ? [
          { name = "EVENT_BROKER", value = "sns_sqs" },
          { name = "SQS_QUEUE_URL", value = var.sqs_queue_url },
        ] : [
          { name = "EVENT_BROKER",            value = "kafka" },
          { name = "KAFKA_BOOTSTRAP_SERVERS", value = var.kafka_bootstrap_servers },
        ],
        # DynamoDB cache — set when dynamodb_cache_table is provided; otherwise Redis
        var.dynamodb_cache_table != "" ? [
          { name = "DYNAMODB_CACHE_TABLE", value = var.dynamodb_cache_table },
        ] : [
          { name = "REDIS_HOST", value = var.redis_host },
          { name = "REDIS_PORT", value = tostring(var.redis_port) },
        ],
      )

      secrets = local.backend_secrets_block

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.backend.name
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/v1/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      readonlyRootFilesystem = false
      user                   = "1000:1000"
    }
  ])

  tags = {
    Name    = "${var.project}-${var.environment}-backend-task"
    Service = "aether-backend"
  }
}


# Dedicated worker task definitions. They use the same immutable application
# image as the API but execute only their canonical role entrypoint.
resource "aws_ecs_task_definition" "runtime_role" {
  for_each                 = var.runtime_roles
  family                   = "${var.project}-${var.environment}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name      = each.key
    image     = "${var.ecr_backend_url}@${var.backend_image_digest}"
    essential = true
    command   = ["python", "-m", "services.runtime.run_role", each.key]
    environment = [
      { name = "APP_ENV", value = var.environment },
      { name = "AETHER_ENV", value = var.environment },
      { name = "AETHER_ROLE", value = each.key },
      { name = "ML_SERVING_INLINE", value = var.ml_serving_inline ? "true" : "false" },
      { name = "SQS_QUEUE_URL", value = var.sqs_queue_url },
      { name = "DYNAMODB_CACHE_TABLE", value = var.dynamodb_cache_table },
    ]
    secrets = local.backend_secrets_block
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.runtime_role[each.key].name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = each.key
      }
    }
    readonlyRootFilesystem = false
    user                   = "1000:1000"
  }])
  tags = { Service = each.key }
}

resource "aws_ecs_service" "runtime_role" {
  for_each        = var.runtime_roles
  name            = "${var.project}-${var.environment}-${each.key}"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.runtime_role[each.key].arn
  desired_count   = 1
  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    base              = 1
    weight            = 100
  }
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = false
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  enable_execute_command = false
  tags = { Service = each.key }
}

# --------------------------------------------------------------------------
# Task Definition — aether-ml-serving
# --------------------------------------------------------------------------

resource "aws_ecs_task_definition" "ml" {
  family                   = "${var.project}-${var.environment}-ml-serving"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ml_cpu
  memory                   = var.ml_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "aether-ml-serving"
      image     = "${var.ecr_ml_url}@${var.ml_image_digest}"
      essential = true

      portMappings = [
        {
          containerPort = 8080
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "PORT", value = "8080" },
        { name = "LOG_LEVEL", value = var.environment == "production" ? "INFO" : "DEBUG" },
      ]

      secrets = local.ml_secrets_block

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ml.name
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 90
      }

      readonlyRootFilesystem = false
      user                   = "1000:1000"
    }
  ])

  tags = {
    Name    = "${var.project}-${var.environment}-ml-task"
    Service = "aether-ml-serving"
  }
}

# --------------------------------------------------------------------------
# ECS Service — aether-backend
# --------------------------------------------------------------------------

resource "aws_ecs_service" "backend" {
  name            = "${var.project}-${var.environment}-backend"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.backend_min_capacity

  # Use Fargate Spot when var.use_fargate_spot = true (E2 cost reduction).
  # Base = 1 on-demand keeps one guaranteed task; the rest scale on Spot.
  dynamic "capacity_provider_strategy" {
    for_each = var.use_fargate_spot ? [] : [1]
    content {
      capacity_provider = "FARGATE"
      base              = 1
      weight            = 100
    }
  }

  dynamic "capacity_provider_strategy" {
    for_each = var.use_fargate_spot ? [1] : []
    content {
      capacity_provider = "FARGATE"
      base              = 1
      weight            = 1
    }
  }

  dynamic "capacity_provider_strategy" {
    for_each = var.use_fargate_spot ? [1] : []
    content {
      capacity_provider = "FARGATE_SPOT"
      base              = 0
      weight            = 4
    }
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.alb_backend_tg_arn
    container_name   = "aether-backend"
    container_port   = 8000
  }

  health_check_grace_period_seconds = 60

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_controller {
    type = "ECS"
  }

  enable_execute_command = false

  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  tags = {
    Name    = "${var.project}-${var.environment}-backend-service"
    Service = "aether-backend"
  }
}

# --------------------------------------------------------------------------
# ECS Service — aether-ml-serving
# --------------------------------------------------------------------------

resource "aws_ecs_service" "ml" {
  name            = "${var.project}-${var.environment}-ml-serving"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.ml.arn
  # Zero tasks when ML serving is inlined into the backend (E2).
  # Set ml_serving_inline = false to restore the dedicated ML service.
  desired_count   = var.ml_serving_inline ? 0 : var.ml_min_capacity

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    base              = 1
    weight            = 100
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.alb_ml_tg_arn
    container_name   = "aether-ml-serving"
    container_port   = 8080
  }

  health_check_grace_period_seconds = 90

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_controller {
    type = "ECS"
  }

  enable_execute_command = false

  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }

  tags = {
    Name    = "${var.project}-${var.environment}-ml-service"
    Service = "aether-ml-serving"
  }
}

# --------------------------------------------------------------------------
# Application Auto Scaling — Backend
# --------------------------------------------------------------------------

resource "aws_appautoscaling_target" "backend" {
  max_capacity       = var.backend_max_capacity
  min_capacity       = var.backend_min_capacity
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.backend.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "backend_cpu" {
  name               = "${var.project}-${var.environment}-backend-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.backend.resource_id
  scalable_dimension = aws_appautoscaling_target.backend.scalable_dimension
  service_namespace  = aws_appautoscaling_target.backend.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "backend_memory" {
  name               = "${var.project}-${var.environment}-backend-memory-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.backend.resource_id
  scalable_dimension = aws_appautoscaling_target.backend.scalable_dimension
  service_namespace  = aws_appautoscaling_target.backend.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value       = 80.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# --------------------------------------------------------------------------
# Application Auto Scaling — ML Serving
# Disabled when ML serving is inlined into the backend (ml_serving_inline=true).
# --------------------------------------------------------------------------

resource "aws_appautoscaling_target" "ml" {
  count              = var.ml_serving_inline ? 0 : 1
  max_capacity       = var.ml_max_capacity
  min_capacity       = var.ml_min_capacity
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.ml.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "ml_cpu" {
  count              = var.ml_serving_inline ? 0 : 1
  name               = "${var.project}-${var.environment}-ml-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ml[0].resource_id
  scalable_dimension = aws_appautoscaling_target.ml[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.ml[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
