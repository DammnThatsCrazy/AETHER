output "cluster_endpoint" {
  description = "Aurora writer endpoint (use for read-write connections)"
  value       = aws_rds_cluster.this.endpoint
}

output "reader_endpoint" {
  description = "Aurora reader endpoint (load-balanced across read replicas, if any)"
  value       = aws_rds_cluster.this.reader_endpoint
}

output "port" {
  description = "Aurora cluster port"
  value       = aws_rds_cluster.this.port
}

output "db_name" {
  description = "Name of the initial database"
  value       = aws_rds_cluster.this.database_name
}

output "cluster_identifier" {
  description = "Aurora cluster identifier (used by monitoring alarms)"
  value       = aws_rds_cluster.this.cluster_identifier
}

output "kms_key_arn" {
  description = "ARN of the KMS key used for Aurora encryption"
  value       = aws_kms_key.aurora.arn
}

output "db_password_secret_arn" {
  description = "ARN of the AWS-managed Secrets Manager secret containing DB credentials"
  value       = aws_rds_cluster.this.master_user_secret[0].secret_arn
}
