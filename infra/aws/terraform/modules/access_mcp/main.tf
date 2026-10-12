locals {
  service_name = "${lower(var.project)}-${var.environment}-access-mcp"
  task_cpu     = 256
  task_memory  = 512
  log_group    = "/aether/${var.environment}/access-mcp"
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

data "aws_iam_policy_document" "tasks_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

resource "aws_cloudwatch_log_group" "this" {
  name              = local.log_group
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "${local.service_name}-logs"
    Service = "access-mcp"
  }
}

# This role is used by the ECS/Fargate agent for ECR image pulls and awslogs.
# The policy is scoped to this image repository and log group. No secret is
# injected into this task, so no Secrets Manager or KMS permission is needed.
resource "aws_iam_role" "execution" {
  name               = "${local.service_name}-execution"
  assume_role_policy = data.aws_iam_policy_document.tasks_assume.json

  tags = {
    Name    = "${local.service_name}-execution"
    Service = "access-mcp"
  }
}

resource "aws_iam_role_policy" "execution" {
  name = "${local.service_name}-execution"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrAuthorizationToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "PullAccessMcpImage"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = var.ecr_repository_arn
      },
      {
        Sid    = "WriteAccessMcpLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.this.arn}:*"
      },
    ]
  })
}

# The customer-facing MCP process receives only caller-provided, per-request
# Aether credentials. It does not receive an AWS permission policy.
resource "aws_iam_role" "task" {
  name               = "${local.service_name}-task"
  assume_role_policy = data.aws_iam_policy_document.tasks_assume.json

  tags = {
    Name    = "${local.service_name}-task"
    Service = "access-mcp"
  }
}

resource "aws_security_group" "this" {
  name_prefix = "${local.service_name}-"
  description = "Access Kit MCP: accept application traffic only from the existing ALB"
  vpc_id      = var.vpc_id

  ingress {
    description     = "MCP HTTP from the existing ALB"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [var.alb_sg_id]
  }

  egress {
    description = "HTTPS to the Aether API, ECR and CloudWatch Logs endpoints"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${local.service_name}-sg"
    Service = "access-mcp"
  }
}

resource "aws_ecs_task_definition" "this" {
  family                   = local.service_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(local.task_cpu)
  memory                   = tostring(local.task_memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "aether-access-mcp"
      image     = "${var.ecr_repository_url}@${var.image_digest}"
      essential = true
      cpu       = local.task_cpu
      memory    = local.task_memory
      portMappings = [
        {
          containerPort = 8080
          hostPort      = 8080
          protocol      = "tcp"
        }
      ]
      environment = concat([
        { name = "NODE_ENV", value = "production" },
        { name = "HOST", value = "0.0.0.0" },
        { name = "PORT", value = "8080" },
        { name = "AETHER_API_URL", value = var.api_url },
        { name = "AETHER_MCP_ALLOWED_HOSTS", value = var.allowed_host },
        { name = "AETHER_MCP_PATH", value = var.access_mcp_path },
        ], length(var.allowed_origins) == 0 ? [] : [
        { name = "AETHER_MCP_ALLOWED_ORIGINS", value = join(",", var.allowed_origins) },
      ])
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "access-mcp"
        }
      }
      stopTimeout = 30
    }
  ])

  tags = {
    Name    = local.service_name
    Service = "access-mcp"
  }
}

resource "aws_ecs_service" "this" {
  name            = local.service_name
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60
  enable_execute_command             = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.this.id]
    assign_public_ip = var.assign_public_ip
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "aether-access-mcp"
    container_port   = 8080
  }

  tags = {
    Name    = local.service_name
    Service = "access-mcp"
  }
}
