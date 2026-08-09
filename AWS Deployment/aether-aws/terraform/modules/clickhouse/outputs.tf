# ============================================================================
# AETHER — ClickHouse Analytics Module Outputs
# ============================================================================

output "hostname" {
  description = "Private DNS hostname of the ClickHouse appliance"
  value       = aws_instance.clickhouse.private_dns
}

output "private_ip" {
  description = "Private IP of the ClickHouse appliance"
  value       = aws_instance.clickhouse.private_ip
}

output "endpoint" {
  description = "Native-protocol endpoint the runtime should connect to (host only; port 9000)"
  value       = aws_instance.clickhouse.private_dns
}

output "http_endpoint" {
  description = "HTTP-interface endpoint (port 8123)"
  value       = aws_instance.clickhouse.private_dns
}

output "security_group_id" {
  description = "Security group id of the ClickHouse appliance"
  value       = aws_security_group.clickhouse.id
}

output "log_group_name" {
  description = "CloudWatch log group receiving ClickHouse broker/query logs"
  value       = aws_cloudwatch_log_group.clickhouse.name
}
