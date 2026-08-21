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

output "task_role_name" {
  description = "Task IAM role NAME — aws_iam_role_policy.role takes the name, not the ARN"
  value       = aws_iam_role.task.name
}

output "backend_task_definition_arn" {
  description = "Latest ARN of the backend task definition"
  value       = aws_ecs_task_definition.backend.arn
}

output "runtime_role_service_names" {
  description = "AETHER_ROLE token -> ECS service name for every non-API runtime service (one key per service, so a consolidated profile has one entry hosting several roles)"
  value       = { for key, service in aws_ecs_service.runtime_service : key => service.name }
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
  description = "ECS service names for the non-API runtime services, in service-key order"
  value       = [for key, service in aws_ecs_service.runtime_service : service.name]
}

output "task_subnet_keys" {
  description = "The \"<tier>/<az>\" keys of the subnets every ECS task ENI in this module is placed in. Configuration-derived, so a provider-mocked plan can assert the network tier; the subnet IDs themselves are unknown until apply."
  value       = local.task_subnet_keys
}

output "backend_service_desired_count" {
  description = "Desired task count configured on the aether-backend service"
  value       = aws_ecs_service.backend.desired_count
}

# --------------------------------------------------------------------------
# Runtime topology surface
#
# Configuration-derived (never a computed attribute) so a provider-mocked plan
# can assert on the shape the matrix produced rather than on the locals that
# produced it.
# --------------------------------------------------------------------------

output "runtime_service_desired_counts" {
  description = "Service key -> planned desired task count. Every entry is 0 in an asleep environment."
  value       = { for key, service in aws_ecs_service.runtime_service : key => service.desired_count }
}

output "runtime_service_queue_roles" {
  description = "Service key -> the roles it hosts that own a dedicated SQS queue, i.e. the exact keys of that task's SQS_ROLE_QUEUE_URLS object"
  value       = { for key, queues in local.runtime_service_role_queues : key => sort(keys(queues)) }
}

output "runtime_service_dlq_roles" {
  description = "Service key -> the roles it hosts that own a dedicated dead-letter queue, i.e. the exact keys of that task's SQS_ROLE_DLQ_URLS object. Must match runtime_service_queue_roles: a role with a queue and no DLQ has nowhere to put a poison message."
  value       = { for key, dlqs in local.runtime_service_role_dlqs : key => sort(keys(dlqs)) }
}

output "runtime_service_capacity_providers" {
  description = "Service key -> the capacity providers its ECS strategy names, sorted"
  value = {
    for key, service in aws_ecs_service.runtime_service :
    key => sort([for strategy in service.capacity_provider_strategy : strategy.capacity_provider])
  }
}

output "backend_capacity_providers" {
  description = "Capacity providers named by the aether-backend service's strategy, sorted"
  value       = sort([for strategy in aws_ecs_service.backend.capacity_provider_strategy : strategy.capacity_provider])
}

output "backend_autoscaling_bounds" {
  description = "Autoscaling floor and ceiling applied to the aether-backend service; both 0 in an asleep environment"
  value = {
    min = aws_appautoscaling_target.backend.min_capacity
    max = aws_appautoscaling_target.backend.max_capacity
  }
}

output "runtime_service_log_groups" {
  description = "Service key -> CloudWatch log group name for that service's tasks. modules/monitoring turns the supervisor's per-role failure line into a metric filter and an alarm, because a consolidated task with one dead role stays at ECS steady state and is otherwise invisible."
  value       = { for key, group in aws_cloudwatch_log_group.runtime_service : key => group.name }
}
