output "alb_dns_name" {
  description = "DNS name of the ALB"
  value       = aws_lb.this.dns_name
}

# Configuration-derived, so it is known at plan time — provider-mocked plan
# tests can assert the ALB exists without waiting for an apply.
output "alb_name" {
  description = "Name of the ALB"
  value       = aws_lb.this.name
}

output "backend_target_group_name" {
  description = "Name of the backend target group"
  value       = local.backend_target_group.name
}

output "backend_target_group_replacement_strategy" {
  description = "Replacement strategy selected by the deployment environment"
  value       = var.environment == "staging" ? "destroy-before-create" : "create-before-destroy"
}

output "alb_arn" {
  description = "ARN of the ALB"
  value       = aws_lb.this.arn
}

output "alb_arn_suffix" {
  description = "ARN suffix of the ALB (used for CloudWatch metrics)"
  value       = aws_lb.this.arn_suffix
}

output "https_listener_arn" {
  description = "ARN of the HTTPS listener"
  value       = aws_lb_listener.https.arn
}

output "backend_target_group_arn" {
  description = "ARN of the backend target group"
  value       = local.backend_target_group.arn
}

output "ml_target_group_arn" {
  description = "ARN of the ML serving target group (empty string when enable_dedicated_ml = false)"
  value       = try(aws_lb_target_group.ml[0].arn, "")
}

output "ml_target_group_arns" {
  description = "ML serving target group ARNs as a list; empty when enable_dedicated_ml = false"
  value       = aws_lb_target_group.ml[*].arn
}

output "backend_tg_arn_suffix" {
  description = "ARN suffix of the backend target group (CloudWatch metrics)"
  value       = local.backend_target_group.arn_suffix
}

output "ml_tg_arn_suffix" {
  description = "ARN suffix of the ML target group (empty string when enable_dedicated_ml = false)"
  value       = try(aws_lb_target_group.ml[0].arn_suffix, "")
}
