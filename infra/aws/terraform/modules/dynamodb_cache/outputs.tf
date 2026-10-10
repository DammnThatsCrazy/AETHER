output "table_name" {
  description = "DynamoDB cache table name"
  value       = aws_dynamodb_table.cache.name
}

output "table_arn" {
  description = "DynamoDB cache table ARN"
  value       = aws_dynamodb_table.cache.arn
}
