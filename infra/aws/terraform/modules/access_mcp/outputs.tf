output "service_name" {
  description = "Customer Access Kit MCP ECS service name."
  value       = aws_ecs_service.this.name
}

output "service_arn" {
  description = "Customer Access Kit MCP ECS service ARN."
  value       = aws_ecs_service.this.id
}

output "task_role_arn" {
  description = "Dedicated task role ARN; the role has no attached permission policy."
  value       = aws_iam_role.task.arn
}

output "execution_role_arn" {
  description = "Dedicated execution role ARN for repository pull and CloudWatch log delivery."
  value       = aws_iam_role.execution.arn
}

output "desired_count" {
  description = "Fixed, operator-configured task count."
  value       = aws_ecs_service.this.desired_count
}

output "image" {
  description = "Digest-pinned container image configured on the MCP task."
  value       = "${var.ecr_repository_url}@${var.image_digest}"
}
