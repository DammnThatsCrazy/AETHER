output "primary_endpoint" {
  description = "Redis primary endpoint (host:port)"
  value       = "${aws_elasticache_cluster.this.cache_nodes[0].address}:${aws_elasticache_cluster.this.port}"
}

output "cluster_id" {
  description = "ElastiCache cluster ID"
  value       = aws_elasticache_cluster.this.cluster_id
}

output "port" {
  description = "Redis port"
  value       = aws_elasticache_cluster.this.port
}

output "auth_token_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the Redis AUTH token"
  value       = aws_secretsmanager_secret.redis_auth.arn
}
