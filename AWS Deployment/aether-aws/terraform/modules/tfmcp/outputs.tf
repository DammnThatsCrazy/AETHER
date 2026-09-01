output "mcp_endpoint_url" { count = var.enable_tfmcp ? 1 : 0; value = "https://${var.alb_dns_name}/mcp"; description = "Streamable HTTP MCP endpoint URL." }
output "mcp_auth_token_secret_arn" { count = var.enable_tfmcp ? 1 : 0; value = aws_secretsmanager_secret.tfmcp_auth[0].arn; description = "ARN of the Secrets Manager secret holding the MCP auth token." }
output "mcp_task_role_arn" { count = var.enable_tfmcp ? 1 : 0; value = aws_iam_role.tfmcp[0].arn; description = "ARN of the tfmcp task IAM role." }
output "tfmcp_service_name" { count = var.enable_tfmcp ? 1 : 0; value = aws_ecs_service.tfmcp[0].name; description = "ECS service name for the tfmcp service." }
output "tfmcp_task_definition_arn" { count = var.enable_tfmcp ? 1 : 0; value = aws_ecs_task_definition.tfmcp[0].arn; description = "ARN of the tfmcp task definition." }
