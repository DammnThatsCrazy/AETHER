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
  description = "ECS service name for aether-ml-serving (empty string when enable_dedicated_ml = false)"
  value       = length(aws_ecs_service.ml) > 0 ? aws_ecs_service.ml[0].name : ""
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
  description = "Latest ARN of the ml-serving task definition (empty string when enable_dedicated_ml = false)"
  value       = length(aws_ecs_task_definition.ml) > 0 ? aws_ecs_task_definition.ml[0].arn : ""
}

# --------------------------------------------------------------------------
# Deployment profile surface
# Lists so callers can consume them unconditionally: every dedicated-ML output
# is an empty list in profiles that do not create the dedicated ML resources.
# --------------------------------------------------------------------------

output "dedicated_ml_service_arns" {
  description = "ARNs of the dedicated aether-ml-serving ECS service; empty when enable_dedicated_ml = false"
  value       = aws_ecs_service.ml[*].id
}

output "dedicated_ml_target_group_arns" {
  description = "ALB target group ARNs the dedicated ML service registers with; empty when enable_dedicated_ml = false"
  value       = var.enable_dedicated_ml && var.alb_ml_tg_arn != "" ? [var.alb_ml_tg_arn] : []
}

output "runtime_service_names" {
  description = "ECS service names for the dedicated non-API runtime roles, in role-name order"
  value       = [for role, service in aws_ecs_service.runtime_role : service.name]
}

output "backend_service_desired_count" {
  description = "Desired task count configured on the aether-backend service"
  value       = aws_ecs_service.backend.desired_count
}
