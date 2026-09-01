locals { service_key = "tfmcp" }
data "aws_caller_identity" "current" {}

resource "aws_cloudwatch_log_group" "tfmcp" {
  count = var.enable_tfmcp ? 1 : 0
  name = "/aether/${var.environment}/${local.service_key}"
  retention_in_days = var.log_retention_days
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-logs") Purpose = "tfmcp MCP server logs" }
}

resource "aws_secretsmanager_secret" "tfmcp_auth" {
  count = var.enable_tfmcp ? 1 : 0
  name = "/aether/${var.environment}/TFMCP_AUTH_TOKEN"
  description = "Shared secret for MCP client auth"
  recovery_window_in_days = 30
  tags = { Name = lower("${var.project}-${var.environment}-tfmcp-auth") Purpose = "MCP server auth token" }
}

resource "aws_secretsmanager_secret_version" "tfmcp_auth" {
  count = var.enable_tfmcp ? 1 : 0
  secret_id = aws_secretsmanager_secret.tfmcp_auth[0].id
  secret_string = jsonencode({ token = var.tfmcp_auth_token != "" ? var.tfmcp_auth_token : uuid() })
}

resource "aws_secretsmanager_secret" "tfmcp_github_pat" {
  count = var.enable_tfmcp ? 1 : 0
  name = "/aether/${var.environment}/TFMCP_GITHUB_PAT"
  description = "GitHub PAT for cloning Aether repo"
  recovery_window_in_days = 30
  tags = { Name = lower("${var.project}-${var.environment}-tfmcp-github-pat") Purpose = "GitHub PAT" }
}

resource "aws_secretsmanager_secret_version" "tfmcp_github_pat" {
  count = var.enable_tfmcp ? 1 : 0
  secret_id = aws_secretsmanager_secret.tfmcp_github_pat[0].id
  secret_string = jsonencode({ token = var.tfmcp_github_pat != "" ? var.tfmcp_github_pat : "" })
}

resource "aws_iam_role" "tfmcp_execution" {
  count = var.enable_tfmcp ? 1 : 0
  name = lower("${var.project}-${var.environment}-${local.service_key}-execution")
  assume_role_policy = jsonencode({ Version = "2012-10-17" Statement = [{ Effect = "Allow" Principal = { Service = "ecs-tasks.amazonaws.com" } Action = "sts:AssumeRole" }] })
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-execution-role") Purpose = "ECS task execution role" }
}

resource "aws_iam_role_policy_attachment" "tfmcp_execution_ecs" {
  count = var.enable_tfmcp ? 1 : 0
  role = aws_iam_role.tfmcp_execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECS_Fargate_TaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "tfmcp_assume" {
  statement { actions = ["sts:AssumeRole"] principals { type = "Service" identifiers = ["ecs-tasks.amazonaws.com"] } }
}

resource "aws_iam_role" "tfmcp" {
  count = var.enable_tfmcp ? 1 : 0
  name = lower("${var.project}-${var.environment}-${local.service_key}-role")
  assume_role_policy = data.aws_iam_policy_document.tfmcp_assume.json
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-role") Purpose = "ECS task role for tfmcp" }
}

data "aws_iam_policy_document" "tfmcp_state_backend" {
  statement {
    sid = "TerraformStateBackend"
    effect = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket}", "arn:aws:s3:::${var.terraform_state_bucket}/*"]
  }
  statement {
    sid = "TerraformStateLock"
    effect = "Allow"
    actions = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
    resources = ["arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.terraform_lock_table}"]
  }
  statement {
    sid = "TerraformStateKMS"
    effect = "Allow"
    actions = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = var.terraform_state_kms_key_arn != "" ? [var.terraform_state_kms_key_arn] : []
    condition { test = "StringEquals" variable = "kms:ViaService" values = ["s3.${var.aws_region}.amazonaws.com"] }
  }
}

data "aws_iam_policy_document" "tfmcp_readonly" {
  statement {
    sid = "CloudControlReadOnly"
    effect = "Allow"
    actions = ["ec2:Describe*", "ecs:Describe*", "ecs:List*", "elasticloadbalancing:Describe*", "elasticloadbalancing:List*", "rds:Describe*", "rds:List*", "dynamodb:Describe*", "dynamodb:List*", "sqs:GetQueueAttributes", "sqs:ListQueues", "sns:GetTopicAttributes", "sns:ListTopics", "s3:GetBucketLocation", "s3:GetBucketTagging", "iam:Get*", "iam:List*", "iam:GenerateCredentialReport", "kms:DescribeKey", "kms:List*", "cloudwatch:Describe*", "cloudwatch:Get*", "logs:Describe*", "logs:Get*", "logs:FilterLogEvents", "sts:GetCallerIdentity", "ecr:Describe*", "ecr:Get*", "ecr:List*"]
    resources = ["*"]
  }
  statement { sid = "DenyIAMWrite" effect = "Deny" actions = ["iam:Put*", "iam:Create*", "iam:Delete*", "iam:Attach*", "iam:Detach*", "iam:Update*", "iam:SetDefaultPolicyVersion"] resources = ["*"] }
  statement { sid = "DenyOrganizations" effect = "Deny" actions = ["organizations:*"] resources = ["*"] }
  statement { sid = "DenyBilling" effect = "Deny" actions = ["budgets:*", "cur:*"] resources = ["*"] }
}

resource "aws_iam_role_policy" "tfmcp_state_backend" { count = var.enable_tfmcp ? 1 : 0; name = lower("${var.project}-${var.environment}-${local.service_key}-state-backend"); role = aws_iam_role.tfmcp[0].id; policy = data.aws_iam_policy_document.tfmcp_state_backend.json }
resource "aws_iam_role_policy" "tfmcp_readonly" { count = var.enable_tfmcp ? 1 : 0; name = lower("${var.project}-${var.environment}-${local.service_key}-readonly"); role = aws_iam_role.tfmcp[0].id; policy = data.aws_iam_policy_document.tfmcp_readonly.json }

data "aws_iam_policy_document" "tfmcp_secrets" {
  statement { sid = "ReadMCPSecrets" effect = "Allow" actions = ["secretsmanager:GetSecretValue"] resources = [aws_secretsmanager_secret.tfmcp_auth[0].arn, aws_secretsmanager_secret.tfmcp_github_pat[0].arn] }
}

resource "aws_iam_role_policy" "tfmcp_secrets" { count = var.enable_tfmcp ? 1 : 0; name = lower("${var.project}-${var.environment}-${local.service_key}-secrets"); role = aws_iam_role.tfmcp[0].id; policy = data.aws_iam_policy_document.tfmcp_secrets.json }

resource "aws_ecs_task_definition" "tfmcp" {
  count = var.enable_tfmcp ? 1 : 0
  family = lower("${var.project}-${var.environment}-${local.service_key}")
  network_mode = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu = var.tfmcp_cpu
  memory = var.tfmcp_memory
  execution_role_arn = aws_iam_role.tfmcp_execution[0].arn
  task_role_arn = aws_iam_role.tfmcp[0].arn
  container_definitions = jsonencode([{
    name = local.service_key
    image = var.tfmcp_image_digest
    command = ["mcp", "--toolsets", "all"]
    environment = [
      { name = "TFMCP_LOG_LEVEL", value = var.tfmcp_log_level },
      { name = "MCP_TRANSPORT", value = "streamable-http" },
      { name = "MCP_HOST", value = "0.0.0.0" },
      { name = "MCP_PORT", value = tostring(var.tfmcp_port) },
      { name = "AETHER_REPO_REF", value = var.aether_repo_ref },
      { name = "DEPLOYMENT_PROFILE", value = var.deployment_profile },
      { name = "TF_BACKEND_BUCKET", value = var.terraform_state_bucket },
      { name = "TF_BACKEND_KEY", value = var.terraform_state_key },
      { name = "TF_BACKEND_DYNAMODB_TABLE", value = var.terraform_lock_table },
      { name = "TF_BACKEND_REGION", value = var.aws_region },
      { name = "TF_BACKEND_KMS_KEY_ID", value = var.terraform_state_kms_key_arn != "" ? var.terraform_state_kms_key_arn : "" },
      { name = "TFMCP_AUTH_TOKEN", value = "" },
      { name = "GITHUB_PAT", value = "" },
    ]
    secrets = [
      { name = "TFMCP_AUTH_TOKEN", valueFrom = aws_secretsmanager_secret.tfmcp_auth[0].arn },
      { name = "GITHUB_PAT", valueFrom = aws_secretsmanager_secret.tfmcp_github_pat[0].arn },
    ]
    portMappings = [{ containerPort = var.tfmcp_port, hostPort = var.tfmcp_port, protocol = "tcp" }]
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.tfmcp[0].name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = local.service_key } }
    healthCheck = { command = ["CMD-SHELL", "pgrep -x tfmcp || exit 1"], interval = 30, timeout = 5, retries = 3, startPeriod = 10 }
    linuxParameters = { initProcessEnabled = true }
    readonlyRootFileSystem = false
  }])
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-task") Purpose = "tfmcp task definition" }
}

resource "aws_ecs_service" "tfmcp" {
  count = var.enable_tfmcp ? 1 : 0
  name = lower("${var.project}-${var.environment}-${local.service_key}")
  cluster = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.tfmcp[0].arn
  desired_count = var.tfmcp_desired_count
  launch_type = "FARGATE"
  network_configuration { subnets = var.ecs_subnet_ids; security_groups = var.ecs_security_group_ids; assign_public_ip = true }
  load_balancer { target_group_arn = aws_lb_target_group.tfmcp[0].arn; container_name = local.service_key; container_port = var.tfmcp_port }
  lifecycle { ignore_changes = [desired_count] }
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-service") Purpose = "tfmcp MCP server" }
  wait_for_steady_state = true
}

resource "aws_lb_target_group" "tfmcp" {
  count = var.enable_tfmcp ? 1 : 0
  name = lower("${var.project}-${var.environment}-${local.service_key}")
  port = var.tfmcp_port
  protocol = "HTTP"
  vpc_id = var.vpc_id
  health_check { path = "/" port = "traffic-port" protocol = "HTTP" interval = 30 timeout = 5 healthy_threshold = 2 unhealthy_threshold = 3 matcher = "200" }
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-tg") Purpose = "tfmcp target group" }
}

resource "aws_lb_listener_rule" "tfmcp" {
  count = var.enable_tfmcp ? 1 : 0
  listener_arn = var.alb_listener_arn
  priority = var.tfmcp_listener_priority
  action { type = "forward" target_group_arn = aws_lb_target_group.tfmcp[0].arn }
  condition { path_pattern { values = ["/mcp*"] } }
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-rule") Purpose = "tfmcp ALB listener rule" }
}
