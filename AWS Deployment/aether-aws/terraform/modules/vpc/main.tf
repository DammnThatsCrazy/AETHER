# ============================================================================
# AETHER — VPC Module
#
# Creates a 3-tier network layout across 3 AZs:
#   Public   subnets — ALB, NAT Gateway egress IPs
#   Private  subnets — ECS Fargate tasks
#   Isolated subnets — RDS, Neptune, ElastiCache, MSK (no internet route)
#
# Security groups are defined here so dependent modules receive them as inputs
# and the VPC module is the single source of truth for network policy.
# ============================================================================

# --------------------------------------------------------------------------
# VPC
# --------------------------------------------------------------------------

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.project}-${var.environment}-vpc"
  }
}

# --------------------------------------------------------------------------
# Internet Gateway
# --------------------------------------------------------------------------

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.project}-${var.environment}-igw"
  }
}

# --------------------------------------------------------------------------
# Subnet calculation
# Divide the VPC CIDR into 9 /20 subnets (3 tiers x 3 AZs).
# --------------------------------------------------------------------------

locals {
  az_count = length(var.availability_zones)

  # /20 gives 4096 IPs each; newbits=4 carves /16 into /20 blocks
  public_subnets   = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, 4, i)]
  private_subnets  = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, 4, i + local.az_count)]
  isolated_subnets = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, 4, i + local.az_count * 2)]

  # NAT topology. "none" provisions no NAT Gateway at all, so zero-egress
  # profiles carry no fixed hourly NAT cost.
  nat_count = var.nat_mode == "ha" ? local.az_count : (var.nat_mode == "single" ? 1 : 0)

  # Distinct private routing domains: one per AZ only when each AZ has its own
  # NAT, otherwise a single shared table (which may carry no default route).
  private_route_table_count = var.nat_mode == "ha" ? local.az_count : 1
}

# --------------------------------------------------------------------------
# Public Subnets
# --------------------------------------------------------------------------

resource "aws_subnet" "public" {
  count = local.az_count

  vpc_id                  = aws_vpc.this.id
  cidr_block              = local.public_subnets[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project}-${var.environment}-public-${var.availability_zones[count.index]}"
    Tier = "public"
  }
}

# --------------------------------------------------------------------------
# Private Subnets (ECS tasks)
# --------------------------------------------------------------------------

resource "aws_subnet" "private" {
  count = local.az_count

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.private_subnets[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name = "${var.project}-${var.environment}-private-${var.availability_zones[count.index]}"
    Tier = "private"
  }
}

# --------------------------------------------------------------------------
# Isolated Subnets (data stores — no internet route)
# --------------------------------------------------------------------------

resource "aws_subnet" "isolated" {
  count = local.az_count

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.isolated_subnets[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name = "${var.project}-${var.environment}-isolated-${var.availability_zones[count.index]}"
    Tier = "isolated"
  }
}

# --------------------------------------------------------------------------
# Elastic IPs for NAT Gateways
# --------------------------------------------------------------------------

resource "aws_eip" "nat" {
  count  = local.nat_count
  domain = "vpc"

  tags = {
    Name = "${var.project}-${var.environment}-nat-eip-${count.index}"
  }

  depends_on = [aws_internet_gateway.this]
}

# --------------------------------------------------------------------------
# NAT Gateways
# HA mode:     one per AZ (placed in each public subnet).
# Single mode: one NAT in the first public subnet (lower cost).
# None mode:   no NAT Gateway; private subnets get no default route.
# --------------------------------------------------------------------------

resource "aws_nat_gateway" "this" {
  count = local.nat_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "${var.project}-${var.environment}-nat-${count.index}"
  }

  depends_on = [aws_internet_gateway.this]
}

# --------------------------------------------------------------------------
# Route Tables — Public
# --------------------------------------------------------------------------

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "${var.project}-${var.environment}-rt-public"
  }
}

resource "aws_route_table_association" "public" {
  count = local.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --------------------------------------------------------------------------
# Route Tables — Private (one per AZ when HA, else shared)
# The tables exist in every NAT mode; the default route is attached
# separately so a table can validly carry no egress path at all.
# --------------------------------------------------------------------------

resource "aws_route_table" "private" {
  count  = local.private_route_table_count
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.project}-${var.environment}-rt-private-${count.index}"
  }
}

# Default route to NAT — one per NAT Gateway, so it disappears entirely when
# nat_mode is "none". In HA mode table N pairs with the NAT in the same AZ.
resource "aws_route" "private_nat" {
  count = local.nat_count

  route_table_id         = var.nat_mode == "ha" ? aws_route_table.private[count.index].id : aws_route_table.private[0].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[count.index].id
}

resource "aws_route_table_association" "private" {
  count = local.az_count

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = var.nat_mode == "ha" ? aws_route_table.private[count.index].id : aws_route_table.private[0].id
}

# --------------------------------------------------------------------------
# Route Tables — Isolated (no default route)
# --------------------------------------------------------------------------

resource "aws_route_table" "isolated" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${var.project}-${var.environment}-rt-isolated"
  }
}

resource "aws_route_table_association" "isolated" {
  count = local.az_count

  subnet_id      = aws_subnet.isolated[count.index].id
  route_table_id = aws_route_table.isolated.id
}

# --------------------------------------------------------------------------
# VPC Flow Logs
# --------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = "/aws/vpc/${var.project}-${var.environment}/flow-logs"
  retention_in_days = 30

  tags = {
    Name = "${var.project}-${var.environment}-vpc-flow-logs"
  }
}

resource "aws_iam_role" "flow_logs" {
  name = "${var.project}-${var.environment}-vpc-flow-logs-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${var.project}-${var.environment}-vpc-flow-logs-role"
  }
}

resource "aws_iam_role_policy" "flow_logs" {
  name = "${var.project}-${var.environment}-vpc-flow-logs-policy"
  role = aws_iam_role.flow_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_flow_log" "this" {
  iam_role_arn    = aws_iam_role.flow_logs.arn
  log_destination = aws_cloudwatch_log_group.flow_logs.arn
  traffic_type    = "ALL"
  vpc_id          = aws_vpc.this.id

  tags = {
    Name = "${var.project}-${var.environment}-vpc-flow-log"
  }
}

# --------------------------------------------------------------------------
# Security Groups
# --------------------------------------------------------------------------

# ALB Security Group — internet-facing, accepts 80 + 443
resource "aws_security_group" "alb" {
  name_prefix = "${var.project}-${var.environment}-alb-"
  description = "ALB: allow HTTP and HTTPS from the internet"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-alb-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ECS Security Group — accepts traffic from ALB only
resource "aws_security_group" "ecs" {
  name_prefix = "${var.project}-${var.environment}-ecs-"
  description = "ECS tasks: accept traffic from ALB"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Backend port from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description     = "ML serving port from ALB"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Allow all outbound (ECR pull, Secrets Manager, etc.)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-ecs-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# RDS Security Group — accepts Postgres from ECS only
resource "aws_security_group" "rds" {
  name_prefix = "${var.project}-${var.environment}-rds-"
  description = "RDS Postgres: accept connections from ECS"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Postgres from ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-rds-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Redis Security Group — only when the profile provisions ElastiCache
resource "aws_security_group" "redis" {
  count = var.enable_redis_sg ? 1 : 0

  name_prefix = "${var.project}-${var.environment}-redis-"
  description = "ElastiCache Redis: accept connections from ECS"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Redis from ECS tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-redis-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Neptune Security Group — only when the profile provisions Neptune
resource "aws_security_group" "neptune" {
  count = var.enable_neptune_sg ? 1 : 0

  name_prefix = "${var.project}-${var.environment}-neptune-"
  description = "Neptune graph DB: accept connections from ECS"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Neptune bolt from ECS tasks"
    from_port       = 8182
    to_port         = 8182
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-neptune-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# MSK Security Group — only when the profile provisions MSK
resource "aws_security_group" "msk" {
  count = var.enable_msk_sg ? 1 : 0

  name_prefix = "${var.project}-${var.environment}-msk-"
  description = "MSK Kafka: accept TLS connections from ECS"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Kafka TLS from ECS tasks"
    from_port       = 9094
    to_port         = 9094
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-${var.environment}-msk-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}
