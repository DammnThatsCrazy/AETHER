locals { service_key = "tfmcp" }
data "aws_caller_identity" "current" {}

resource "aws_cloudwatch_log_group" "tfmcp" {
  count = var.enable_tfmcp ? 1 : 0
  name = "/aether/${var.environment}/${local.service_key}"
  retention_in_days = var.log_retention_days
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-logs") Purpose = "tfmcp MCP server logs" }
}

resource "random_password" "tfmcp_auth_token" {
  count = var.enable_tfmcp && var.tfmcp_auth_token == "" ? 1 : 0
  length = 32
  special = true
  override_special = "_%@"
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
  secret_string = var.tfmcp_auth_token != "" ? var.tfmcp_auth_token : random_password.tfmcp_auth_token[0].result
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
  secret_string = var.tfmcp_github_pat != "" ? var.tfmcp_github_pat : "PLACEHOLDER_REPLACE_AFTER_BUILD"
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

resource "aws_iam_role_policy" "tfmcp_execution_secrets" {
  count = var.enable_tfmcp ? 1 : 0
  name = lower("${var.project}-${var.environment}-${local.service_key}-execution-secrets")
  role = aws_iam_role.tfmcp_execution[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.tfmcp_auth[0].arn,
        aws_secretsmanager_secret.tfmcp_github_pat[0].arn,
      ]
    }]
  })
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
    sid = "TerraformStateBackendBucket"
    effect = "Allow"
    actions = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.terraform_state_key}", "${var.terraform_state_key}/*"]
    }
  }
  statement {
    sid = "TerraformStateBackendObject"
    effect = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.terraform_state_bucket}/${var.terraform_state_key}"]
  }
  statement {
    sid = "TerraformStateLock"
    effect = "Allow"
    actions = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
    resources = ["arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.terraform_lock_table}"]
  }
  dynamic "statement" {
    for_each = var.terraform_state_kms_key_arn != "" ? [1] : []
    content {
      sid = "TerraformStateKMS"
      effect = "Allow"
      actions = ["kms:Decrypt", "kms:GenerateDataKey"]
      resources = [var.terraform_state_kms_key_arn]
      condition { test = "StringEquals" variable = "kms:ViaService" values = ["s3.${var.aws_region}.amazonaws.com"] }
    }
  }
}

data "aws_iam_policy_document" "tfmcp_apply" {
  statement {
    sid = "ECSManagement"
    effect = "Allow"
    actions = [
      "ecs:CreateService", "ecs:UpdateService", "ecs:DeleteService",
      "ecs:RegisterTaskDefinition", "ecs:DeregisterTaskDefinition",
      "ecs:DescribeServices", "ecs:DescribeTaskDefinition", "ecs:ListServices",
      "ecs:RunTask", "ecs:StopTask", "ecs:DescribeTasks", "ecs:ListTasks",
      "ecs:TagResource", "ecs:UntagResource",
    ]
    resources = ["*"]
  }
  statement {
    sid = "ALBManagement"
    effect = "Allow"
    actions = [
      "elasticloadbalancing:AddListenerCertificates", "elasticloadbalancing:RemoveListenerCertificates",
      "elasticloadbalancing:CreateTargetGroup", "elasticloadbalancing:DeleteTargetGroup",
      "elasticloadbalancing:CreateListener", "elasticloadbalancing:DeleteListener",
      "elasticloadbalancing:ModifyListener", "elasticloadbalancing:ModifyTargetGroupAttributes",
      "elasticloadbalancing:RegisterTargets", "elasticloadbalancing:DeregisterTargets",
      "elasticloadbalancing:DescribeListeners", "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetHealth", "elasticloadbalancing:DescribeRules",
      "elasticloadbalancing:CreateRule", "elasticloadbalancing:DeleteRule", "elasticloadbalancing:ModifyRule",
    ]
    resources = ["*"]
  }
  statement {
    sid = "DynamoDBManagement"
    effect = "Allow"
    actions = [
      "dynamodb:CreateTable", "dynamodb:UpdateTable", "dynamodb:DeleteTable",
      "dynamodb:DescribeTable", "dynamodb:ListTables",
      "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
      "dynamodb:Query", "dynamodb:Scan",
    ]
    resources = ["*"]
  }
  statement {
    sid = "RDSManagement"
    effect = "Allow"
    actions = [
      "rds:Describe*",
      "rds:CreateDBInstance", "rds:ModifyDBInstance", "rds:DeleteDBInstance",
      "rds:CreateDBCluster", "rds:ModifyDBCluster", "rds:DeleteDBCluster",
      "rds:AddRoleToDBCluster", "rds:RemoveRoleFromDBCluster",
      "rds:CreateDBSubnetGroup", "rds:DeleteDBSubnetGroup",
      "rds:ListTagsForResource", "rds:AddTagsToResource", "rds:RemoveTagsFromResource",
    ]
    resources = ["*"]
  }
  statement {
    sid = "SQSManagement"
    effect = "Allow"
    actions = [
      "sqs:CreateQueue", "sqs:DeleteQueue", "sqs:GetQueueAttributes", "sqs:GetQueueUrl",
      "sqs:ListQueues", "sqs:PurgeQueue", "sqs:SetQueueAttributes",
      "sqs:CreateQueueBatch", "sqs:DeleteMessage", "sqs:ReceiveMessage", "sqs:SendMessage",
    ]
    resources = ["*"]
  }
  statement {
    sid = "SNSManagement"
    effect = "Allow"
    actions = [
      "sns:CreateTopic", "sns:DeleteTopic", "sns:GetTopicAttributes", "sns:ListTopics",
      "sns:Subscribe", "sns:Unsubscribe", "sns:Publish", "sns:SetTopicAttributes",
      "sns:ConfirmSubscription", "sns:ListSubscriptionsByTopic",
    ]
    resources = ["*"]
  }
  statement {
    sid = "S3Management"
    effect = "Allow"
    actions = [
      "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketTagging", "s3:GetBucketTagging",
      "s3:PutBucketVersioning", "s3:GetBucketVersioning", "s3:PutBucketAcl",
      "s3:PutBucketPolicy", "s3:GetBucketPolicy", "s3:PutBucketPublicAccessBlock",
      "s3:GetBucketPublicAccessBlock", "s3:PutBucketEncryption", "s3:GetBucketEncryption",
      "s3:PutBucketLogging", "s3:GetBucketLogging", "s3:PutBucketLifecycleConfiguration",
      "s3:GetBucketLifecycleConfiguration", "s3:ListBucket", "s3:GetObject", "s3:PutObject",
      "s3:DeleteObject", "s3:ListBucketMultipartUploads", "s3:AbortMultipartUpload",
    ]
    resources = ["*"]
  }
  statement {
    sid = "ECRManagement"
    effect = "Allow"
    actions = [
      "ecr:CreateRepository", "ecr:DeleteRepository", "ecr:DescribeRepositories",
      "ecr:ListRepositories", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
      "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:DeleteRepositoryPolicy",
      "ecr:SetRepositoryPolicy", "ecr:DescribeRepositoryCredentials",
      "ecr:GetAuthorizationToken", "ecr:BatchDeleteImage",
    ]
    resources = ["*"]
  }
  statement {
    sid = "CloudWatchManagement"
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:DescribeAlarms",
      "cloudwatch:ListMetrics", "cloudwatch:PutDashboard", "cloudwatch:DeleteDashboards",
      "cloudwatch:DescribeDashboards", "cloudwatch:GetDashboard",
      "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:DescribeLogGroups",
      "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy",
    ]
    resources = ["*"]
  }
  statement {
    sid = "KMSManagement"
    effect = "Allow"
    actions = [
      "kms:CreateKey", "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion",
      "kms:EnableKey", "kms:DisableKey", "kms:EnableKeyRotation", "kms:DisableKeyRotation",
      "kms:PutKeyPolicy", "kms:GetKeyPolicy", "kms:DeleteKeyPolicy",
      "kms:CreateAlias", "kms:DeleteAlias", "kms:UpdateAlias",
      "kms:ListKeys", "kms:DescribeKey", "kms:ListAliases",
      "kms:GenerateDataKey", "kms:Decrypt", "kms:Encrypt", "kms:ReEncrypt*",
      "kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant",
    ]
    resources = ["*"]
  }
  statement {
    sid = "IAMReadOnly"
    effect = "Allow"
    actions = ["iam:Get*", "iam:List*", "iam:GenerateCredentialReport", "iam:GetCredentialReport"]
    resources = ["*"]
  }
  statement { sid = "DenyIAMWrite" effect = "Deny" actions = ["iam:Put*", "iam:Create*", "iam:Delete*", "iam:Attach*", "iam:Detach*", "iam:Update*", "iam:SetDefaultPolicyVersion"] resources = ["*"] }
  statement { sid = "DenyOrganizations" effect = "Deny" actions = ["organizations:*"] resources = ["*"] }
  statement { sid = "DenyBilling" effect = "Deny" actions = ["budgets:*", "cur:*"] resources = ["*"] }
}

resource "aws_iam_role_policy" "tfmcp_state_backend" {
  count = var.enable_tfmcp ? 1 : 0
  name = lower("${var.project}-${var.environment}-${local.service_key}-state-backend")
  role = aws_iam_role.tfmcp[0].id
  policy = data.aws_iam_policy_document.tfmcp_state_backend.json
}

resource "aws_iam_role_policy" "tfmcp_apply" {
  count = var.enable_tfmcp ? 1 : 0
  name = lower("${var.project}-${var.environment}-${local.service_key}-apply")
  role = aws_iam_role.tfmcp[0].id
  policy = data.aws_iam_policy_document.tfmcp_apply.json
}

resource "aws_iam_role_policy" "tfmcp_secrets" {
  count = var.enable_tfmcp ? 1 : 0
  name = lower("${var.project}-${var.environment}-${local.service_key}-secrets")
  role = aws_iam_role.tfmcp[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      sid = "ReadMCPSecrets"
      effect = "Allow"
      actions = ["secretsmanager:GetSecretValue"]
      resources = [
        aws_secretsmanager_secret.tfmcp_auth[0].arn,
        aws_secretsmanager_secret.tfmcp_github_pat[0].arn,
      ]
    }]
  })
}

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
    image = "${var.tfmcp_ecr_uri}@${var.tfmcp_image_digest}"
    command = ["mcp", "--toolsets", "all"]
    environment = [
      { name = "TFMCP_LOG_LEVEL", value = var.tfmcp_log_level },
      { name = "MCP_TRANSPORT", value = "streamable-http" },
      { name = "MCP_HOST", value = "0.0.0.0" },
      { name = "MCP_PORT", value = tostring(var.tfmcp_port) },
      { name = "AETHER_REPO_REF", value = var.aether_repo_ref },
      { name = "TF_VAR_deployment_profile", value = var.deployment_profile },
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
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.tfmcp[0].name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = local.service_key
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8080/ || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 10
    }
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
  network_configuration {
    subnets         = var.ecs_subnet_ids
    security_groups = var.ecs_security_group_ids
    assign_public_ip = var.assign_public_ip
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.tfmcp[0].arn
    container_name   = local.service_key
    container_port   = var.tfmcp_port
  }
  depends_on = [aws_lb_listener_rule.tfmcp]
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-service") Purpose = "tfmcp MCP server" }
  wait_for_steady_state = true
}

resource "aws_lb_target_group" "tfmcp" {
  count = var.enable_tfmcp ? 1 : 0
  name     = lower("${var.project}-${var.environment}-${local.service_key}")
  port     = var.tfmcp_port
  protocol = "HTTP"
  vpc_id   = var.vpc_id
  health_check {
    path                = "/"
    port                = "traffic-port"
    protocol            = "HTTP"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-tg") Purpose = "tfmcp target group" }
}

resource "aws_lb_listener_rule" "tfmcp" {
  count = var.enable_tfmcp ? 1 : 0
  listener_arn = var.alb_listener_arn
  priority     = var.tfmcp_listener_priority
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.tfmcp[0].arn
  }
  condition {
    path_pattern {
      values = ["/mcp*"]
    }
  }
  tags = { Name = lower("${var.project}-${var.environment}-${local.service_key}-rule") Purpose = "tfmcp ALB listener rule" }
}
