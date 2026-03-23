# ═══════════════════════════════════════════════════════════════════════════
# Aether ECS Module — Fargate Compute
# 9 backend services, ALB, autoscaling on CPU/memory/request count
# Agent workers on Fargate Spot for cost efficiency
# Canary + stable target groups for progressive deployment
# ═══════════════════════════════════════════════════════════════════════════

variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "private_subnet_ids" { type = list(string) }
variable "image_tag" { type = string default = "latest" }
variable "ecr_registry" { type = string }
variable "acm_cert_arn" { type = string default = "" }
variable "allowed_db_security_groups" {
  type    = list(string)
  default = []
  description = "SG IDs for data stores so ECS tasks can connect"
}

locals {
  services = {
    ingestion    = { cpu = 512,  memory = 1024, port = 8001, min = 2, max = 20, cpu_target = 60, spot = false }
    identity     = { cpu = 512,  memory = 1024, port = 8002, min = 2, max = 10, cpu_target = 60, spot = false }
    analytics    = { cpu = 1024, memory = 2048, port = 8003, min = 2, max = 15, cpu_target = 70, spot = false }
    ml-serving   = { cpu = 1024, memory = 4096, port = 8004, min = 2, max = 20, cpu_target = 50, spot = false }
    agent        = { cpu = 512,  memory = 2048, port = 8005, min = 1, max = 10, cpu_target = 70, spot = true  }
    campaign     = { cpu = 256,  memory = 512,  port = 8006, min = 1, max = 5,  cpu_target = 60, spot = false }
    consent      = { cpu = 256,  memory = 512,  port = 8007, min = 1, max = 3,  cpu_target = 60, spot = false }
    notification = { cpu = 256,  memory = 512,  port = 8008, min = 1, max = 5,  cpu_target = 60, spot = false }
    admin        = { cpu = 256,  memory = 512,  port = 8009, min = 1, max = 3,  cpu_target = 60, spot = false }
  }
}

# ── ECS Cluster ───────────────────────────────────────────────────────

resource "aws_ecs_cluster" "main" {
  name = "aether-${var.environment}"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = { Name = "aether-cluster-${var.environment}" }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

# ── ALB ───────────────────────────────────────────────────────────────

resource "aws_security_group" "alb" {
  name_prefix = "aether-alb-${var.environment}-"
  vpc_id      = var.vpc_id

  ingress { from_port = 443;  to_port = 443;  protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"]; description = "HTTPS" }
  ingress { from_port = 80;   to_port = 80;   protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"]; description = "HTTP redirect" }
  egress  { from_port = 0;    to_port = 0;    protocol = "-1";  cidr_blocks = ["0.0.0.0/0"] }

  tags = { Name = "aether-alb-sg-${var.environment}" }
}

resource "aws_lb" "main" {
  name               = "aether-alb-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = var.environment == "production"
  drop_invalid_header_fields = true

  tags = { Name = "aether-alb-${var.environment}" }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_cert_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = "{\"error\":\"Not found\"}"
      status_code  = "404"
    }
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
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

# ── ECS Security Group ────────────────────────────────────────────────

resource "aws_security_group" "ecs" {
  name_prefix = "aether-ecs-${var.environment}-"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "From ALB"
  }

  ingress {
    from_port = 0; to_port = 65535; protocol = "tcp"
    self = true; description = "Inter-service"
  }

  egress { from_port = 0; to_port = 0; protocol = "-1"; cidr_blocks = ["0.0.0.0/0"] }

  tags = { Name = "aether-ecs-sg-${var.environment}" }
}

# ── IAM Roles ─────────────────────────────────────────────────────────

resource "aws_iam_role" "ecs_execution" {
  name = "aether-ecs-exec-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Action = "sts:AssumeRole", Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task" {
  name = "aether-ecs-task-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Action = "sts:AssumeRole", Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" } }]
  })
}

# ── CloudWatch Log Groups ─────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "services" {
  for_each          = local.services
  name              = "/ecs/aether-${each.key}-${var.environment}"
  retention_in_days = 30
}

# ── Stable Target Groups ─────────────────────────────────────────────

resource "aws_lb_target_group" "stable" {
  for_each = local.services

  name        = "ae-${substr(each.key, 0, 10)}-s-${var.environment}"
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
  tags = { Name = "aether-${each.key}-stable-${var.environment}" }
}

# ── Canary Target Groups (progressive deployment) ─────────────────────

resource "aws_lb_target_group" "canary" {
  for_each = local.services

  name        = "ae-${substr(each.key, 0, 10)}-c-${var.environment}"
  port        = each.value.port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path    = "/v1/health"
    matcher = "200"
  }

  tags = { Name = "aether-${each.key}-canary-${var.environment}" }
}

# ── ALB Listener Rules (path-based routing) ───────────────────────────

resource "aws_lb_listener_rule" "services" {
  for_each = local.services

  listener_arn = aws_lb_listener.https.arn
  priority     = 100 + index(keys(local.services), each.key)

  action {
    type = "forward"
    forward {
      target_group { arn = aws_lb_target_group.stable[each.key].arn; weight = 100 }
      target_group { arn = aws_lb_target_group.canary[each.key].arn; weight = 0 }
    }
  }

  condition {
    path_pattern { values = ["/v1/${replace(each.key, "-", "")}*", "/v1/${replace(each.key, "-", "")}/*"] }
  }
}

# ── Task Definitions ──────────────────────────────────────────────────

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
    portMappings = [{ containerPort = each.value.port, protocol = "tcp" }]
    environment = [
      { name = "AETHER_ENV", value = var.environment },
      { name = "PORT", value = tostring(each.value.port) },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/aether-${each.key}-${var.environment}"
        "awslogs-region"        = "us-east-1"
        "awslogs-stream-prefix" = "ecs"
      }
    }
    healthCheck = {
      command = ["CMD-SHELL", "curl -f http://localhost:${each.value.port}/v1/health || exit 1"]
      interval = 30; timeout = 5; retries = 3; startPeriod = 60
    }
  }])
}

# ── ECS Services ──────────────────────────────────────────────────────

resource "aws_ecs_service" "services" {
  for_each = local.services

  name            = "aether-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.services[each.key].arn
  desired_count   = each.value.min

  capacity_provider_strategy {
    capacity_provider = each.value.spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 1
    base              = each.value.spot ? 0 : 1
  }

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.ecs.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.stable[each.key].arn
    container_name   = "aether-${each.key}"
    container_port   = each.value.port
  }

  deployment_circuit_breaker { enable = true; rollback = true }

  lifecycle { ignore_changes = [desired_count] }
}

# ── Autoscaling ───────────────────────────────────────────────────────

resource "aws_appautoscaling_target" "services" {
  for_each           = local.services
  max_capacity       = each.value.max
  min_capacity       = each.value.min
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.services[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  for_each           = local.services
  name               = "aether-${each.key}-cpu-${var.environment}"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.services[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.services[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.services[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = each.value.cpu_target
    predefined_metric_specification { predefined_metric_type = "ECSServiceAverageCPUUtilization" }
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

output "cluster_name"       { value = aws_ecs_cluster.main.name }
output "cluster_arn"        { value = aws_ecs_cluster.main.arn }
output "alb_dns_name"       { value = aws_lb.main.dns_name }
output "alb_arn"            { value = aws_lb.main.arn }
output "alb_listener_arn"   { value = aws_lb_listener.https.arn }
output "ecs_security_group" { value = aws_security_group.ecs.id }
output "service_names"      { value = { for k, v in aws_ecs_service.services : k => v.name } }
