# ============================================================================
# AETHER — Application Load Balancer Module
#
# Provisions an internet-facing ALB with:
#   - HTTP (port 80) → redirect to HTTPS
#   - HTTPS (port 443) with ACM certificate
#   - Target group for aether-backend  (port 8000, /v1/health)
#   - Target group for aether-ml-serving (port 8080, /health) — only when
#     enable_dedicated_ml is set; cost-capped profiles serve ML inline
#   - Path-based routing:
#       /v1/ml/* → ml-serving target group (only when enable_dedicated_ml)
#       *         → backend target group (default)
#
# Access logs are written to S3 (bucket must exist and have the correct
# bucket policy before this resource is applied; omitted here to keep the
# module self-contained — enable by uncommenting the access_logs block).
# ============================================================================

data "aws_region" "current" {}

# --------------------------------------------------------------------------
# Application Load Balancer
# --------------------------------------------------------------------------

resource "aws_lb" "this" {
  name               = "${lower(var.project)}-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = var.environment == "production"
  idle_timeout               = 60

  # Uncomment to enable access logs (S3 bucket + bucket policy required):
  # access_logs {
  #   bucket  = "your-alb-access-logs-bucket"
  #   prefix  = "${var.project}-${var.environment}"
  #   enabled = true
  # }

  tags = {
    Name = "${var.project}-${var.environment}-alb"
  }
}

# --------------------------------------------------------------------------
# Target Group — Backend (port 8000)
# --------------------------------------------------------------------------

resource "aws_lb_target_group" "backend" {
  count = var.environment == "staging" ? 1 : 0

  # Keep the deterministic name across profiles. If a staging rehearsal is
  # interrupted after AWS creates this target group but before state persists,
  # reconcile it through the reviewed import-only workflow before reapplying.
  name        = "${lower(var.project)}-${var.environment}-backend"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/v1/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = {
    Name    = "${var.project}-${var.environment}-backend-tg"
    Service = "backend"
  }

  lifecycle {
    # The deterministic staging name is also the import/reconcile identity.
    # Replacements must not ask AWS for a second target group with that same
    # name. The listener still references this group, so fail closed on a
    # ForceNew change; a reviewed listener-detach transition must precede any
    # intentional replacement.
    create_before_destroy = false
  }
}

# Production-class profiles keep replacement-before-destroy for availability.
# This is a separate resource because Terraform lifecycle meta-arguments must
# be literal: interpolating var.environment here is rejected before planning.
resource "aws_lb_target_group" "backend_replacement" {
  count = var.environment != "staging" ? 1 : 0

  name        = "${lower(var.project)}-${var.environment}-backend"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/v1/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = {
    Name    = "${var.project}-${var.environment}-backend-tg"
    Service = "backend"
  }

  lifecycle {
    create_before_destroy = true
  }
}

locals {
  backend_target_group = var.environment == "staging" ? aws_lb_target_group.backend[0] : aws_lb_target_group.backend_replacement[0]
}

# --------------------------------------------------------------------------
# Target Group — ML Serving (port 8080)
# Gated: the dedicated ML ECS service in modules/ecs is gated on the same flag,
# so the target group and its only registrant appear and disappear together.
# --------------------------------------------------------------------------

resource "aws_lb_target_group" "ml" {
  count = var.enable_dedicated_ml ? 1 : 0

  name        = "${lower(var.project)}-${var.environment}-ml"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  deregistration_delay = 30

  tags = {
    Name    = "${var.project}-${var.environment}-ml-tg"
    Service = "ml-serving"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --------------------------------------------------------------------------
# HTTP Listener — redirect all traffic to HTTPS
# --------------------------------------------------------------------------

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
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

  tags = {
    Name = "${var.project}-${var.environment}-alb-http-listener"
  }
}

# --------------------------------------------------------------------------
# HTTPS Listener — routes by path
# --------------------------------------------------------------------------

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  # Default: send everything to backend
  default_action {
    type             = "forward"
    target_group_arn = var.environment == "staging" && var.staging_listener_target_group_arn != "" ? var.staging_listener_target_group_arn : local.backend_target_group.arn
  }

  tags = {
    Name = "${var.project}-${var.environment}-alb-https-listener"
  }
}

# --------------------------------------------------------------------------
# Listener Rule — ML serving path prefix
# Without the rule, /v1/ml/* falls through to the HTTPS listener default action
# and is served by the backend task, which is exactly the inline-ML behaviour.
# --------------------------------------------------------------------------

resource "aws_lb_listener_rule" "ml_serving" {
  count = var.enable_dedicated_ml ? 1 : 0

  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  condition {
    path_pattern {
      values = ["/v1/ml/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ml[0].arn
  }

  tags = {
    Name = "${var.project}-${var.environment}-ml-serving-rule"
  }
}
