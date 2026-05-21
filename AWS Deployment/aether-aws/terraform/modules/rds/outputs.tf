output "endpoint" {
  description = "RDS instance endpoint address"
  value       = aws_db_instance.this.address
}

output "port" {
  description = "RDS instance port"
  value       = aws_db_instance.this.port
}

output "db_name" {
  description = "Name of the initial database"
  value       = aws_db_instance.this.db_name
}

output "db_instance_identifier" {
  description = "RDS instance identifier (used by monitoring alarms)"
  value       = aws_db_instance.this.identifier
}

output "kms_key_arn" {
  description = "ARN of the KMS key used for RDS encryption"
  value       = aws_kms_key.rds.arn
}

output "db_password_secret_arn" {
  description = "ARN of the AWS-managed Secrets Manager secret containing DB credentials"
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}
