output "bootstrap_brokers_tls" {
  description = "TLS bootstrap broker connection string"
  value       = aws_msk_cluster.this.bootstrap_brokers_tls
}

output "cluster_arn" {
  description = "MSK cluster ARN"
  value       = aws_msk_cluster.this.arn
}

output "zookeeper_connect_string" {
  description = "Zookeeper connection string"
  value       = aws_msk_cluster.this.zookeeper_connect_string
}
