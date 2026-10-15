output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "IDs of public subnets (ALB tier)"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of private subnets (ECS task tier)"
  value       = aws_subnet.private[*].id
}

output "isolated_subnet_ids" {
  description = "IDs of isolated subnets (data store tier — no internet route)"
  value       = aws_subnet.isolated[*].id
}

# Subnet IDs grouped by network tier and keyed by "<tier>/<az>".
#
# The KEY is configuration-derived and therefore known at plan time; a subnet
# ID is not. That is the whole point of this shape: it lets a provider-mocked
# plan assert WHICH TIER a workload was placed in, which a list of
# unknown-until-apply IDs cannot express. modules/ecs consumes one entry of
# this map and republishes its keys, so task placement is pinned by a test
# rather than by a comment.
#
# Only the two tiers a workload may legitimately run in are offered. The
# isolated tier is deliberately absent: it is the data-store tier and has no
# route out at all.
output "workload_subnets_by_tier" {
  description = "Network tier -> {\"<tier>/<az>\" = subnet id}. Public carries the IGW default route; private carries the NAT default route only when nat_mode != \"none\"."
  value = {
    public = {
      for index, az in var.availability_zones :
      "public/${az}" => aws_subnet.public[index].id
    }
    private = {
      for index, az in var.availability_zones :
      "private/${az}" => aws_subnet.private[index].id
    }
  }
}

# True only when the private route tables actually carry a 0.0.0.0/0 route.
# With nat_mode = "none" the tables exist but have no default route, so a task
# ENI placed there has NO path to ECR, Secrets Manager or CloudWatch and
# assign_public_ip is inert (a public IP still routes through the subnet's
# route table). Configuration-derived, so a plan test can read it.
output "private_subnets_have_internet_route" {
  description = "Whether the private route tables carry a 0.0.0.0/0 route (false when nat_mode is \"none\")"
  value       = var.nat_mode != "none"
}

output "ecs_sg_ingress" {
  description = "The ingress rules configured on the ECS task security group, as declared data: port, admitted CIDRs, and whether the source is the ALB security group."
  value = [
    for rule in local.ecs_ingress_rules : {
      port        = rule.port
      cidr_blocks = rule.cidr_blocks
      from_alb    = rule.from_alb
    }
  ]
}

output "private_route_table_ids" {
  description = "IDs of private route tables (used by VPC endpoints)"
  value       = aws_route_table.private[*].id
}

output "isolated_route_table_id" {
  description = "ID of the isolated route table"
  value       = aws_route_table.isolated.id
}

output "vpc_cidr" {
  description = "VPC CIDR block"
  value       = aws_vpc.this.cidr_block
}

# NAT egress — all empty when nat_mode is "none"
output "nat_gateway_ids" {
  description = "IDs of the NAT Gateways (empty when nat_mode is \"none\")"
  value       = aws_nat_gateway.this[*].id
}

output "nat_eip_ids" {
  description = "IDs of the Elastic IPs attached to the NAT Gateways"
  value       = aws_eip.nat[*].id
}

output "nat_mode" {
  description = "NAT topology this VPC was built with (none, single, or ha)"
  value       = var.nat_mode
}

# Security group IDs
output "alb_sg_id" {
  description = "Security group ID for the Application Load Balancer"
  value       = aws_security_group.alb.id
}

output "ecs_sg_id" {
  description = "Security group ID for ECS tasks"
  value       = aws_security_group.ecs.id
}

output "rds_sg_id" {
  description = "Security group ID for RDS"
  value       = aws_security_group.rds.id
}

output "redis_sg_id" {
  description = "Security group ID for ElastiCache Redis (empty when not enabled)"
  value       = try(aws_security_group.redis[0].id, "")
}

output "neptune_sg_id" {
  description = "Security group ID for Neptune (empty when not enabled)"
  value       = try(aws_security_group.neptune[0].id, "")
}

output "msk_sg_id" {
  description = "Security group ID for MSK Kafka (empty when not enabled)"
  value       = try(aws_security_group.msk[0].id, "")
}
