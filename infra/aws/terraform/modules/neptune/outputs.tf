output "cluster_endpoint" {
  description = "Neptune cluster writer endpoint"
  value       = aws_neptune_cluster.this.endpoint
}

output "reader_endpoint" {
  description = "Neptune cluster reader endpoint"
  value       = aws_neptune_cluster.this.reader_endpoint
}

output "port" {
  description = "Neptune port (8182)"
  value       = aws_neptune_cluster.this.port
}

output "cluster_id" {
  description = "Neptune cluster identifier"
  value       = aws_neptune_cluster.this.id
}

output "cluster_arn" {
  description = "Neptune cluster ARN"
  value       = aws_neptune_cluster.this.arn
}
