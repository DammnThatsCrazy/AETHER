output "cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.this.name
}

output "cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.this.arn
}

output "backend_service_name" {
  description = "ECS service name for aether-backend"
  value       = aws_ecs_service.backend.name
}

output "ml_service_name" {
  description = "ECS service name for aether-ml-serving"
  value       = aws_ecs_service.ml.name
}

output "execution_role_arn" {
  description = "Task execution IAM role ARN"
  value       = aws_iam_role.execution.arn
}

output "task_role_arn" {
  description = "Task IAM role ARN"
  value       = aws_iam_role.task.arn
}

output "backend_task_definition_arn" {
  description = "Latest ARN of the backend task definition"
  value       = aws_ecs_task_definition.backend.arn
}

output "runtime_role_service_names" {
  description = "ECS service name for every dedicated non-API runtime role"
  value       = { for role, service in aws_ecs_service.runtime_role : role => service.name }
}

output "ml_task_definition_arn" {
  description = "Latest ARN of the ml-serving task definition"
  value       = aws_ecs_task_definition.ml.arn
}
