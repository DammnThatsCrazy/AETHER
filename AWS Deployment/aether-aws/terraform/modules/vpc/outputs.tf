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
