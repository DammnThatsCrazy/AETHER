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
  description = "Security group ID for ElastiCache Redis"
  value       = aws_security_group.redis.id
}

output "neptune_sg_id" {
  description = "Security group ID for Neptune"
  value       = aws_security_group.neptune.id
}

output "msk_sg_id" {
  description = "Security group ID for MSK Kafka"
  value       = aws_security_group.msk.id
}
