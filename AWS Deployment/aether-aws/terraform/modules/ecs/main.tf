# ============================================================================
# AETHER — ECS Fargate Module
#
# Provisions:
#   - ECS cluster (Fargate + Fargate Spot capacity providers)
#   - Task execution IAM role (ECR pull, Secrets Manager, CloudWatch)
#   - Task role (application permissions)
#   - Task definitions for: aether-backend, the runtime services declared by the
#     profile, and aether-ml-serving (only when enable_dedicated_ml)
#   - ECS services with ALB target group registration
#   - Application Auto Scaling: CPU/memory for the backend, SQS backlog-per-task
#     for the runtime services
#   - CloudWatch log groups per service
#
# Backend selection (event broker, cache, graph) is an explicit profile input;
# see the "Deployment profile gating" section of variables.tf.
# ============================================================================

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# --------------------------------------------------------------------------
# Task network placement
#
# Every ECS service in this module places its ENIs here, and there is nowhere
# else for it to place them: the module receives one tier's subnets, not a
# menu. The keys travel with the IDs so `task_subnet_keys` below can state the
# tier at plan time — a subnet ID is unknown until apply and can prove nothing
# about which route table the task will actually use.
# --------------------------------------------------------------------------

locals {
  task_subnet_keys = sort(keys(var.task_subnets))
  task_subnet_ids  = [for key in local.task_subnet_keys : var.task_subnets[key]]
}

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
  count             = var.enable_dedicated_ml ? 1 : 0
  name              = "/ecs/${var.project}-${var.environment}/aether-ml-serving"
  retention_in_days = var.log_retention_days

  tags = {
    Name    = "${var.project}-${var.environment}-ml-logs"
    Service = "aether-ml-serving"
  }
}

resource "aws_cloudwatch_log_group" "runtime_service" {
  for_each          = var.runtime_services
  name              = "/ecs/${var.project}-${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days
  tags              = { Service = each.key }
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
        Resource = local.readable_secret_arns
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
      # Dead-letter queues are included deliberately. Handing a task a DLQ
      # URL it has no sqs:SendMessage grant for turns a poison message into an
      # AccessDenied at exactly the moment the system is already failing.
      Resource = concat(
        [var.sqs_queue_arn],
        values(var.sqs_role_queue_arns),
        var.sqs_dlq_arn != "" ? [var.sqs_dlq_arn] : [],
        values(var.sqs_role_dlq_queue_arns),
      )
    }
  ] : []

  sns_statements = var.sns_topic_arn != "" ? [
    {
      Sid      = "SNSFanoutPublish"
      Effect   = "Allow"
      Action   = ["sns:Publish"]
      Resource = var.sns_topic_arn
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

  # Neptune IAM auth follows the same conditional-statement pattern as the
  # queue/cache statements: profiles without a Neptune cluster must not carry
  # a neptune-db grant at all.
  neptune_statements = var.enable_neptune ? [
    {
      Sid    = "NeptuneIAMAuth"
      Effect = "Allow"
      Action = [
        "neptune-db:*",
      ]
      Resource = "arn:aws:neptune-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*/*"
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
          Resource = local.readable_secret_arns
        },
      ])),
      jsondecode(jsonencode(local.sqs_statements)),
      jsondecode(jsonencode(local.sns_statements)),
      jsondecode(jsonencode(local.dynamodb_statements)),
      jsondecode(jsonencode(local.neptune_statements)),
    )
  })
}

# --------------------------------------------------------------------------
# Helpers — build the `secrets` block for task definitions
# --------------------------------------------------------------------------

locals {
  # Secrets the tasks are allowed to read. The Redis AUTH token is only
  # reachable when ElastiCache is part of the profile, so lean tasks hold no
  # permission for a secret they never mount.
  readable_secret_arns = concat(
    [
      for name, arn in var.secret_arns : arn
      if var.enable_elasticache || name != "redis-auth-token"
    ],
    [for arn in values(var.companion_secret_arns) : arn],
  )

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
      EXTRACTION_CANARY_SEED    = var.secret_arns["extraction-canary-seed"]
      SDK_CONFIG_SECRET         = var.secret_arns["sdk-config-secret"]
      FIRST_ADMIN_BOOTSTRAP_TOKEN = var.secret_arns["first-admin-bootstrap-token"]
    },
    # Redis AUTH token — read by shared/cache/cache.py as REDIS_PASSWORD.
    # Only mounted when ElastiCache exists; every task (API and workers)
    # shares this block, so an unconditional mapping would pin the
    # ElastiCache module in place for the whole fleet.
    var.enable_elasticache ? {
      REDIS_PASSWORD = var.secret_arns["redis-auth-token"]
    } : {},
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
          { name = "APP_ENV", value = var.environment },
          { name = "AETHER_ENV", value = var.environment },
          { name = "PORT", value = "8000" },
          { name = "LOG_LEVEL", value = var.environment == "production" ? "INFO" : "DEBUG" },
          { name = "CACHE_BACKEND", value = var.cache_backend },
          { name = "GRAPH_BACKEND", value = var.graph_backend },
          { name = "ANALYTICS_BACKEND", value = var.analytics_backend },
          { name = "ML_SERVING_URL", value = var.ml_serving_url },
          { name = "ML_SERVING_INLINE", value = var.ml_serving_inline ? "true" : "false" },
        ],
        # Provider-credential envelope-encryption CMK. The backend's
        # AwsKmsEnvelopeCredentialCipher reads this key id to call
        # kms:GenerateDataKey / kms:Decrypt. Only injected when the profile
        # provisions the key (every cloud profile does).
        var.credential_kms_key_id != "" ? [
          { name = "CREDENTIAL_KMS_KEY_ID", value = var.credential_kms_key_id },
        ] : [],
        # Graph backend — the Neptune endpoint is only injected when the
        # profile actually selects Neptune; postgres profiles never see it.
        var.graph_backend == "neptune" ? [
          { name = "NEPTUNE_ENDPOINT", value = var.neptune_endpoint },
        ] : [],
        # Event broker selected explicitly by the profile, not inferred from
        # whether sqs_queue_url happens to be set. SNS_TOPIC_ARN makes the
        # producer publish through the fanout topic so every per-role consumer
        # queue receives the event.
        var.event_broker == "kafka" ? [
          { name = "EVENT_BROKER", value = "kafka" },
          { name = "KAFKA_BOOTSTRAP_SERVERS", value = var.kafka_bootstrap_servers },
          ] : concat(
          [
            { name = "EVENT_BROKER", value = "sns_sqs" },
            { name = "SQS_QUEUE_URL", value = var.sqs_queue_url },
            # The api task publishes and can consume the shared events queue,
            # so it needs the same real dead-letter destination the workers do.
            { name = "SQS_DLQ_QUEUE_URL", value = var.sqs_dlq_url },
          ],
          var.sns_topic_arn != "" ? [
            { name = "SNS_TOPIC_ARN", value = var.sns_topic_arn },
          ] : [],
        ),
        # Cache backend selected explicitly by the profile.
        var.cache_backend == "redis" ? [
          { name = "REDIS_HOST", value = var.redis_host },
          { name = "REDIS_PORT", value = tostring(var.redis_port) },
          ] : [
          { name = "DYNAMODB_CACHE_TABLE", value = var.dynamodb_cache_table },
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


# --------------------------------------------------------------------------
# Runtime services — derived shapes
# --------------------------------------------------------------------------

locals {
  # ── Per-service queue bindings ─────────────────────────────────────────────
  # THE consolidation-critical derivation. modules/sqs provisions one
  # SNS-subscribed queue per consumer role (aws_sqs_queue.role, for_each over
  # var.consumer_role_queues), and a task must bind one consumer per role it
  # hosts. A single SQS_QUEUE_URL can only ever name one queue, so it is
  # sufficient for a dedicated task and structurally wrong for a consolidated
  # one: `lean-worker` hosts eight roles and must poll every queue those roles
  # own, or the seven it cannot address consume nothing at all while the
  # deployment looks entirely healthy.
  #
  # services/runtime/consumer_runner.py::role_queue_urls therefore reads
  # SQS_ROLE_QUEUE_URLS, a JSON object of role -> queue URL, and
  # ::resolve_queue_url falls back to SQS_QUEUE_URL for any role the object
  # omits. This map is that object, built from each service's OWN roles so a
  # task is told about the queues it hosts and nothing else — and so
  # ::_assert_distinct_queues, which fails closed when two consumers in one
  # process resolve to the same queue, has a distinct entry per role to work
  # with.
  #
  # Roles with no dedicated queue are omitted deliberately rather than mapped
  # to the shared queue: omission is what triggers the runtime's documented
  # SQS_QUEUE_URL fallback, and it keeps the map an honest statement of which
  # queues Terraform actually provisioned for this service.
  runtime_service_role_queues = {
    for service, cfg in var.runtime_services :
    service => {
      for role in cfg.roles : role => var.sqs_role_queue_urls[role]
      if contains(keys(var.sqs_role_queue_urls), role)
    }
  }

  # The dead-letter mirror of the map above, derived the same way from the same
  # `cfg.roles`, so a consolidated lean-worker is handed all eight of its roles'
  # DLQs and a dedicated service exactly its own. It has to be per-service for
  # the same reason the queue map does: one SQS_DLQ_QUEUE_URL can name one
  # destination, and eight co-hosted roles need eight.
  #
  # Getting this wrong is not a degraded mode, it is data loss. Until these
  # URLs reached the task the runtime had no dead-letter destination at all and
  # fell back to re-publishing the poison message onto the queue it had just
  # read it from — where it was re-received, matched no handler, and was
  # deleted. The runtime now raises rather than doing that, so an unset value
  # is loud; this map is what stops it being unset.
  runtime_service_role_dlqs = {
    for service, cfg in var.runtime_services :
    service => {
      for role in cfg.roles : role => var.sqs_role_dlq_queue_urls[role]
      if contains(keys(var.sqs_role_dlq_queue_urls), role)
    }
  }

  # Only a service whose roles own at least one dedicated queue has a backlog
  # signal to scale on. A service with none (outbox-relay drains the database
  # outbox, maintenance runs cron loops) still gets a scaling TARGET, which
  # pins its min/max, but no queue-depth policy — inventing a backlog metric
  # from a queue it never polls would scale it on another service's work.
  runtime_service_scaling_queues = {
    for service, queues in local.runtime_service_role_queues :
    service => queues if length(queues) > 0
  }

  # ── Capacity provider strategy ─────────────────────────────────────────────
  # `base_count` guaranteed tasks on `base`, everything above that floor on
  # `surge`. ECS expresses that as `base` on the guaranteed provider plus all of
  # the WEIGHT on the surge one — weight 0 on the base entry is what stops
  # additional tasks landing there. When base == surge there is a single
  # provider and ECS rejects a strategy naming the same provider twice, so the
  # two entries collapse into one carrying the whole weight.
  #
  # Derived once for every service this module creates, api included, so the
  # matrix's Spot policy cannot be honoured for the workers and quietly ignored
  # for the public API (which is what the removed use_fargate_spot flag did).
  capacity_providers_by_service = merge(
    { for service, cfg in var.runtime_services : service => cfg.capacity_provider },
    { backend = var.backend_capacity_provider },
  )

  capacity_strategies = {
    for service, provider in local.capacity_providers_by_service :
    service => provider.base == provider.surge ? [
      { capacity_provider = provider.base, base = provider.base_count, weight = 100 },
      ] : [
      { capacity_provider = provider.base, base = provider.base_count, weight = 0 },
      { capacity_provider = provider.surge, base = 0, weight = 100 },
    ]
  }
}

# Runtime service task definitions. They use the same immutable application
# image as the API but execute only their canonical role entrypoint — where
# "role" is the service KEY, which the runtime expands through
# roles.py::roles_in into the one role a dedicated task runs or the eight an
# execution group co-hosts. Sizing comes from the profile matrix in
# config/runtime_deployment.yaml.
resource "aws_ecs_task_definition" "runtime_service" {
  for_each                 = var.runtime_services
  family                   = "${var.project}-${var.environment}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name      = each.key
    image     = "${var.ecr_backend_url}@${var.backend_image_digest}"
    essential = true
    command   = ["python", "-m", "services.runtime.run_role", each.key]
    environment = concat(
      [
        { name = "APP_ENV", value = var.environment },
        { name = "AETHER_ENV", value = var.environment },
        { name = "AETHER_ROLE", value = each.key },
        { name = "CACHE_BACKEND", value = var.cache_backend },
        { name = "GRAPH_BACKEND", value = var.graph_backend },
        { name = "ANALYTICS_BACKEND", value = var.analytics_backend },
        { name = "ML_SERVING_INLINE", value = var.ml_serving_inline ? "true" : "false" },
      ],
      # Provider-credential envelope-encryption CMK (mirrors the API task).
      var.credential_kms_key_id != "" ? [
        { name = "CREDENTIAL_KMS_KEY_ID", value = var.credential_kms_key_id },
      ] : [],
      # Neptune endpoint only on the Neptune graph backend (mirrors the API task).
      var.graph_backend == "neptune" ? [
        { name = "NEPTUNE_ENDPOINT", value = var.neptune_endpoint },
      ] : [],
      # Same explicit broker selection as the API task: without it workers
      # default to kafka and never consume SQS.
      var.event_broker == "kafka" ? [
        { name = "EVENT_BROKER", value = "kafka" },
        { name = "KAFKA_BOOTSTRAP_SERVERS", value = var.kafka_bootstrap_servers },
        ] : concat(
        [
          { name = "EVENT_BROKER", value = "sns_sqs" },
          # Single-queue binding, still the whole story for a dedicated task
          # hosting one queue-bound role: each.key IS that role, so the lookup
          # finds its dedicated queue. For a consolidated service the key is an
          # execution group with no queue of its own, so this resolves to the
          # shared SNS-subscribed events queue — which is exactly the fallback
          # consumer_runner.resolve_queue_url applies to a hosted role that has
          # no dedicated queue of its own.
          { name = "SQS_QUEUE_URL", value = lookup(var.sqs_role_queue_urls, each.key, var.sqs_queue_url) },
          # Per-role bindings. One entry per role THIS service hosts that owns
          # a dedicated queue, so a consolidated task attaches one consumer per
          # role instead of eight roles sharing one URL. See the
          # runtime_service_role_queues local above for the full reasoning.
          { name = "SQS_ROLE_QUEUE_URLS", value = jsonencode(local.runtime_service_role_queues[each.key]) },
          # Dead-letter destinations, exactly mirroring the two lines above:
          # the single-URL fallback for a service key that owns a queue, and
          # the per-role object for every role this task hosts. The lookups use
          # the same key and the same fallback shape as the queue side, so a
          # role's DLQ is always the "-dlq" sibling of the queue it drains and
          # never the queue itself.
          { name = "SQS_DLQ_QUEUE_URL", value = lookup(var.sqs_role_dlq_queue_urls, each.key, var.sqs_dlq_url) },
          { name = "SQS_ROLE_DLQ_URLS", value = jsonencode(local.runtime_service_role_dlqs[each.key]) },
        ],
        var.sns_topic_arn != "" ? [
          { name = "SNS_TOPIC_ARN", value = var.sns_topic_arn },
        ] : [],
      ),
      # Cache backend selected explicitly by the profile (mirrors the API task).
      var.cache_backend == "redis" ? [
        { name = "REDIS_HOST", value = var.redis_host },
        { name = "REDIS_PORT", value = tostring(var.redis_port) },
        ] : [
        { name = "DYNAMODB_CACHE_TABLE", value = var.dynamodb_cache_table },
      ],
    )
    secrets = local.backend_secrets_block
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.runtime_service[each.key].name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = each.key
      }
    }
    readonlyRootFilesystem = false
    user                   = "1000:1000"
  }])
  tags = { Service = each.key }
}

resource "aws_ecs_service" "runtime_service" {
  for_each        = var.runtime_services
  name            = "${var.project}-${var.environment}-${each.key}"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.runtime_service[each.key].arn
  desired_count   = each.value.desired_count

  # base/surge from the matrix, not a fixed on-demand strategy: a dedicated
  # backlog-draining worker surges onto FARGATE_SPOT because an at-least-once
  # consumer with a DLQ tolerates a reclaim, while any service hosting
  # outbox-relay (including every consolidated lean-worker) stays on-demand at
  # every capacity. See the capacity_strategies local.
  dynamic "capacity_provider_strategy" {
    for_each = local.capacity_strategies[each.key]
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      base              = capacity_provider_strategy.value.base
      weight            = capacity_provider_strategy.value.weight
    }
  }

  network_configuration {
    subnets          = local.task_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = var.assign_public_ip
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  enable_execute_command = false
  tags                   = { Service = each.key }
}

# ----------------------------------------------------------------------------
# Runtime service state migrations
#
# schema v2 renamed the unit from "role" to "service"; these three resources
# were named after the old unit. A rename alone would read as "gone from
# configuration" and plan a destroy-and-create of every live worker service,
# so the address change is declared as state-only.
#
# This does NOT cover the lean/staging collapse. There, eight single-role
# services genuinely become one consolidated `lean-worker` service: seven of
# the eight keys disappear from `for_each` and a new key appears. That is a
# real destroy of seven services plus one create, it is the intended effect of
# consolidation, and papering over it with `moved` would silently rename a
# 512-CPU single-role task into a 2048-CPU eight-role one.
# ----------------------------------------------------------------------------

moved {
  from = aws_cloudwatch_log_group.runtime_role
  to   = aws_cloudwatch_log_group.runtime_service
}

moved {
  from = aws_ecs_task_definition.runtime_role
  to   = aws_ecs_task_definition.runtime_service
}

moved {
  from = aws_ecs_service.runtime_role
  to   = aws_ecs_service.runtime_service
}

# --------------------------------------------------------------------------
# Application Auto Scaling — runtime services
#
# The target exists for every runtime service, because min/max is how the
# matrix states a service's capacity envelope and how an asleep environment is
# pinned to 0..0. The POLICY only exists where there is a real backlog signal.
# --------------------------------------------------------------------------

resource "aws_appautoscaling_target" "runtime_service" {
  for_each           = var.runtime_services
  max_capacity       = each.value.autoscaling.max_capacity
  min_capacity       = each.value.autoscaling.min_capacity
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.runtime_service[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# Target tracking on SQS backlog PER TASK.
#
# Target tracking multiplies capacity by (metric / target), so the metric has
# to be a per-task quantity or the loop diverges — scaling on raw queue depth
# would keep scaling out while the depth stayed above the target no matter how
# many tasks were already draining it. There is no AWS predefined metric for
# this, so the policy is metric math: the summed visible backlog of the queues
# THIS service's roles own, divided by the service's running task count. A
# consolidated service therefore scales on the aggregate of the queues its one
# task drains, which is the load that task actually carries.
resource "aws_appautoscaling_policy" "runtime_service_queue_depth" {
  for_each           = local.runtime_service_scaling_queues
  name               = "${var.project}-${var.environment}-${each.key}-queue-depth-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.runtime_service[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.runtime_service[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.runtime_service[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = var.runtime_services[each.key].autoscaling.queue_depth_target

    # One declared cooldown, applied both ways. The matrix states a single
    # `cooldown_seconds` per service and splitting it into an invented
    # asymmetric pair here would be a capacity decision made in Terraform
    # rather than in the reviewed matrix.
    scale_in_cooldown  = var.runtime_services[each.key].autoscaling.cooldown_seconds
    scale_out_cooldown = var.runtime_services[each.key].autoscaling.cooldown_seconds

    customized_metric_specification {
      # One backlog series per role queue. The CloudWatch QueueName dimension is
      # taken from the queue URL the task is handed rather than reconstructed
      # from a naming convention, so the metric cannot drift from the queue the
      # consumer binds. Unknown-until-apply is fine here: unlike the root's
      # alarm dimensions, nothing in this resource gates a `count`.
      dynamic "metrics" {
        for_each = each.value
        content {
          id          = "q_${replace(metrics.key, "-", "_")}"
          label       = "${metrics.key} visible backlog"
          return_data = false
          metric_stat {
            stat = "Average"
            metric {
              namespace   = "AWS/SQS"
              metric_name = "ApproximateNumberOfMessagesVisible"
              dimensions {
                name  = "QueueName"
                value = basename(metrics.value)
              }
            }
          }
        }
      }

      # Running tasks, from Container Insights (enabled on the cluster above).
      metrics {
        id          = "tasks"
        label       = "running tasks"
        return_data = false
        metric_stat {
          stat = "Average"
          metric {
            namespace   = "ECS/ContainerInsights"
            metric_name = "RunningTaskCount"
            dimensions {
              name  = "ClusterName"
              value = aws_ecs_cluster.this.name
            }
            dimensions {
              name  = "ServiceName"
              value = aws_ecs_service.runtime_service[each.key].name
            }
          }
        }
      }

      # Backlog per task. Division by zero yields no datapoint rather than an
      # error, and no datapoint is the correct behaviour at zero tasks: the
      # only way to reach it is an asleep environment, whose max_capacity is
      # also 0, so there is nothing for a scaling decision to act on.
      metrics {
        id    = "backlog_per_task"
        label = "backlog per task"
        expression = format(
          "(%s) / tasks",
          join(" + ", [for role in keys(each.value) : "q_${replace(role, "-", "_")}"]),
        )
        return_data = true
      }
    }
  }
}

# --------------------------------------------------------------------------
# Task Definition — aether-ml-serving
# Only exists in profiles that run dedicated ML (enable_dedicated_ml).
# --------------------------------------------------------------------------

resource "aws_ecs_task_definition" "ml" {
  count                    = var.enable_dedicated_ml ? 1 : 0
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
          "awslogs-group"         = aws_cloudwatch_log_group.ml[0].name
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
  desired_count   = var.backend_desired_count

  # Capacity providers from the matrix, same derivation as the runtime services.
  # This replaces a use_fargate_spot flag the root passed as `true`, which put
  # the PUBLIC API on a 4:1 Spot:on-demand strategy — directly contrary to the
  # matrix, which pins api to FARGATE at every capacity precisely because a
  # two-minute Spot interruption on the request path is not worth the discount.
  dynamic "capacity_provider_strategy" {
    for_each = local.capacity_strategies["backend"]
    content {
      capacity_provider = capacity_provider_strategy.value.capacity_provider
      base              = capacity_provider_strategy.value.base
      weight            = capacity_provider_strategy.value.weight
    }
  }

  network_configuration {
    subnets          = local.task_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = var.assign_public_ip
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

  # task_definition is ignored because the deploy workflow registers the exact
  # revision to run; Terraform must not roll it back to whatever digest the
  # last plan happened to pin.
  #
  # desired_count is deliberately NOT ignored, and that is a correctness
  # requirement rather than a preference. It used to be, and the effect was
  # that `staging_state = "asleep"` never stopped the API at all:
  #
  #   * ignore_changes suppresses the attribute after CREATE, so the 0 this
  #     module computes for an asleep environment never reached an applied
  #     service — it only ever applied to a workspace being created for the
  #     first time, which is never the case when putting staging to sleep.
  #   * the autoscaling floor could not finish the job on its own. Dropping
  #     min_capacity to 0 stops Application Auto Scaling clamping the service
  #     back UP, but it cannot drive it DOWN to zero: both tracking policies
  #     below are target-tracking on a utilization metric, and target tracking
  #     computes ceil(running x metric / target), which from one running task
  #     at any non-zero CPU is 1, never 0.
  #   * the workers had no ignore_changes and did sleep, so an asleep staging
  #     environment quietly kept running exactly the always-on API task the
  #     "no always-on staging compute" guarantee says it does not.
  #
  # It is also what .github/workflows/staging-lifecycle.yml verifies: it reads
  # `desired_count` out of planned_values for every aws_ecs_service and
  # compares it against the matrix x the state multiplier. An ignored attribute
  # plans as its prior value, so that gate could never have passed on a real
  # sleep plan.
  #
  # The cost of managing desired_count is that an apply resets a scaled-out API
  # to the matrix baseline; the tracking policies below scale it back out
  # within a 60 s scale-out cooldown. That is the accepted trade, and it is the
  # same one aws_ecs_service.runtime_service has always made.
  lifecycle {
    ignore_changes = [task_definition]
  }

  tags = {
    Name    = "${var.project}-${var.environment}-backend-service"
    Service = "aether-backend"
  }
}

# --------------------------------------------------------------------------
# ECS Service — aether-ml-serving
# Only exists in profiles that run dedicated ML (enable_dedicated_ml); lean
# profiles serve ML predictions in-process inside aether-backend instead.
# --------------------------------------------------------------------------

resource "aws_ecs_service" "ml" {
  count           = var.enable_dedicated_ml ? 1 : 0
  name            = "${var.project}-${var.environment}-ml-serving"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.ml[0].arn
  desired_count   = var.ml_min_capacity

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    base              = 1
    weight            = 100
  }

  network_configuration {
    subnets          = local.task_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = var.assign_public_ip
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
# Absent unless the profile runs dedicated ML (enable_dedicated_ml).
# --------------------------------------------------------------------------

resource "aws_appautoscaling_target" "ml" {
  count              = var.enable_dedicated_ml ? 1 : 0
  max_capacity       = var.ml_max_capacity
  min_capacity       = var.ml_min_capacity
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.ml[0].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "ml_cpu" {
  count              = var.enable_dedicated_ml ? 1 : 0
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
