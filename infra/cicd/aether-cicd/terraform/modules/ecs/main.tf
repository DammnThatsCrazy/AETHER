# ═══════════════════════════════════════════════════════════════════════════
# Aether ECS Module -- Fargate services for all backend components
# Includes: ALB, target groups (stable + canary), task definitions,
#           autoscaling, CloudWatch log groups, IAM policies,
#           ECR lifecycle, security groups, WAF association
# ═══════════════════════════════════════════════════════════════════════════

variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "image_tag" { type = string }
variable "ecr_registry" { type = string }
variable "acm_cert_arn" { type = string default = "" }

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}


# ── Service Definitions ──────────────────────────────────────────────────
# All 9 backend services defined as a map for DRY configuration

locals {
  services = {
    ingestion = {
      cpu    = 512
      memory = 1024
      port   = 8001
      scaling = { min = 2, max = 20, target_cpu = 60 }
    }
    identity = {
      cpu    = 512
      memory = 1024
      port   = 8002
      scaling = { min = 2, max = 10, target_cpu = 60 }
    }
    analytics = {
      cpu    = 1024
      memory = 2048
      port   = 8003
      scaling = { min = 2, max = 15, target_cpu = 70 }
    }
    ml-serving = {
      cpu    = 1024
      memory = 4096
      port   = 8004
      scaling = { min = 2, max = 20, target_cpu = 50 }
    }
    agent = {
      cpu    = 512
      memory = 2048
      port   = 8005
      scaling = { min = 1, max = 10, target_cpu = 70 }
      spot   = true   # agent workers on Spot for cost efficiency
    }
    campaign = {
      cpu    = 256
      memory = 512
      port   = 8006
      scaling = { min = 1, max = 5, target_cpu = 60 }
    }
    consent = {
      cpu    = 256
      memory = 512
      port   = 8007
      scaling = { min = 1, max = 3, target_cpu = 60 }
    }
    notification = {
      cpu    = 256
      memory = 512
      port   = 8008
      scaling = { min = 1, max = 5, target_cpu = 60 }
    }
    admin = {
      cpu    = 256
      memory = 512
      port   = 8009
      scaling = { min = 1, max = 3, target_cpu = 60 }
    }
  }
}


# ── ECS Cluster ──────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "aether-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 1
    capacity_provider = "FARGATE"
  }
}


# ── CloudWatch Log Groups ───────────────────────────────────────────────
# Created before task definitions so logs work from first deploy

resource "aws_cloudwatch_log_group" "services" {
  for_each = local.services

  name              = "/ecs/aether-${each.key}-${var.environment}"
  retention_in_days = var.environment == "production" ? 90 : 30

  tags = { Service = each.key }
}


# ── ECR Repositories + Lifecycle ────────────────────────────────────────
# Keep only 25 tagged images and expire untagged after 7 days

resource "aws_ecr_repository" "services" {
  for_each = local.services

  name                 = "aether-${each.key}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "services" {
  for_each = local.services

  repository = aws_ecr_repository.services[each.key].name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only last 25 tagged images"
        selection = {
          tagStatus   = "tagged"
          tagPrefixList = ["latest"]
          countType   = "imageCountMoreThan"
          countNumber = 25
        }
        action = { type = "expire" }
      }
    ]
  })
}


# ── ALB ──────────────────────────────────────────────────────────────────

resource "aws_lb" "api" {
  name               = "aether-api-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  subnets            = var.subnet_ids
  security_groups    = [aws_security_group.alb.id]

  drop_invalid_header_fields = true

  tags = { Name = "aether-api-${var.environment}" }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_cert_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.services["ingestion"].arn
  }
}

# Redirect HTTP -> HTTPS
resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}


# ── ALB Security Group ──────────────────────────────────────────────────

resource "aws_security_group" "alb" {
  name_prefix = "aether-alb-${var.environment}-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS from internet"
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP redirect"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  lifecycle {
    create_before_destroy = true
  }
}


# ── Stable Target Groups ────────────────────────────────────────────────

resource "aws_lb_target_group" "services" {
  for_each = local.services

  name        = "aether-${each.key}-${var.environment}"
  port        = each.value.port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/v1/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 30

  stickiness {
    type    = "lb_cookie"
    enabled = false
  }
}


# ── Canary Target Groups (for progressive deployment) ───────────────────

resource "aws_lb_target_group" "canary" {
  for_each = local.services

  name        = "ae-${each.key}-can-${var.environment}"
  port        = each.value.port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/v1/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  deregistration_delay = 15
}


# ── Task Definitions ────────────────────────────────────────────────────

resource "aws_ecs_task_definition" "services" {
  for_each = local.services

  family                   = "aether-${each.key}-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name  = "aether-${each.key}"
    image = "${var.ecr_registry}/aether-${each.key}:${var.image_tag}"
    portMappings = [{
      containerPort = each.value.port
      protocol      = "tcp"
    }]
    environment = [
      { name = "AETHER_ENV", value = var.environment },
      { name = "PORT",       value = tostring(each.value.port) },
      { name = "AWS_REGION", value = data.aws_region.current.name },
    ]
    secrets = [
      {
        name      = "DATABASE_URL"
        valueFrom = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:aether/${var.environment}/database-url"
      },
      {
        name      = "REDIS_URL"
        valueFrom = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:aether/${var.environment}/redis-url"
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.services[each.key].name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = "ecs"
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:${each.value.port}/v1/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])

  tags = { Service = each.key }
}


# ── ECS Services ────────────────────────────────────────────────────────

resource "aws_ecs_service" "services" {
  for_each = local.services

  name            = "aether-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.services[each.key].arn
  desired_count   = each.value.scaling.min

  capacity_provider_strategy {
    capacity_provider = lookup(each.value, "spot", false) ? "FARGATE_SPOT" : "FARGATE"
    weight            = 1
    base              = lookup(each.value, "spot", false) ? 0 : 1
  }

  network_configuration {
    subnets         = var.subnet_ids
    security_groups = [aws_security_group.ecs.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.services[each.key].arn
    container_name   = "aether-${each.key}"
    container_port   = each.value.port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  propagate_tags = "SERVICE"

  lifecycle {
    ignore_changes = [desired_count]  # managed by autoscaling
  }
}


# ── ECS Security Group ──────────────────────────────────────────────────

resource "aws_security_group" "ecs" {
  name_prefix = "aether-ecs-${var.environment}-"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "Allow traffic from ALB"
  }

  ingress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    self        = true
    description = "Allow inter-service communication"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  lifecycle {
    create_before_destroy = true
  }
}


# ── Autoscaling ─────────────────────────────────────────────────────────

resource "aws_appautoscaling_target" "services" {
  for_each = local.services

  max_capacity       = each.value.scaling.max
  min_capacity       = each.value.scaling.min
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.services[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  for_each = local.services

  name               = "aether-${each.key}-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.services[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.services[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.services[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = each.value.scaling.target_cpu
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# Memory-based scaling for ML-heavy services
resource "aws_appautoscaling_policy" "memory" {
  for_each = {
    for k, v in local.services : k => v if v.memory >= 2048
  }

  name               = "aether-${each.key}-memory-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.services[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.services[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.services[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = 75
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}


# ── IAM Roles ───────────────────────────────────────────────────────────

resource "aws_iam_role" "ecs_execution" {
  name = "aether-ecs-execution-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

# Execution role policies: ECR pull + CloudWatch logs + Secrets Manager
resource "aws_iam_role_policy_attachment" "ecs_execution_base" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "aether-ecs-secrets-${var.environment}"
  role = aws_iam_role.ecs_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:aether/${var.environment}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/ecs/aether-*"
      }
    ]
  })
}

resource "aws_iam_role" "ecs_task" {
  name = "aether-ecs-task-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

# Task role policies: S3, SQS, SNS, DynamoDB, Neptune, SageMaker
resource "aws_iam_role_policy" "ecs_task_services" {
  name = "aether-ecs-task-services-${var.environment}"
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::aether-*-${var.environment}",
          "arn:aws:s3:::aether-*-${var.environment}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = "arn:aws:sqs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:aether-*"
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = "arn:aws:sns:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:aether-*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/aether-*"
      },
      {
        Effect = "Allow"
        Action = [
          "sagemaker:InvokeEndpoint"
        ]
        Resource = "arn:aws:sagemaker:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:endpoint/aether-*"
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "Aether/${var.environment}"
          }
        }
      }
    ]
  })
}


# ── Outputs ─────────────────────────────────────────────────────────────

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "alb_dns_name" {
  value = aws_lb.api.dns_name
}

output "alb_arn" {
  value = aws_lb.api.arn
}

output "service_arns" {
  value = { for k, v in aws_ecs_service.services : k => v.id }
}

output "stable_target_group_arns" {
  value = { for k, v in aws_lb_target_group.services : k => v.arn }
}

output "canary_target_group_arns" {
  value = { for k, v in aws_lb_target_group.canary : k => v.arn }
}

output "ecr_repository_urls" {
  value = { for k, v in aws_ecr_repository.services : k => v.repository_url }
}
