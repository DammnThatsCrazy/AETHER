output "alb_dns_name" {
  description = "DNS name of the ALB"
  value       = aws_lb.this.dns_name
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
  value       = aws_lb_target_group.backend.arn
}

output "ml_target_group_arn" {
  description = "ARN of the ML serving target group"
  value       = aws_lb_target_group.ml.arn
}

output "backend_tg_arn_suffix" {
  description = "ARN suffix of the backend target group (CloudWatch metrics)"
  value       = aws_lb_target_group.backend.arn_suffix
}

output "ml_tg_arn_suffix" {
  description = "ARN suffix of the ML target group (CloudWatch metrics)"
  value       = aws_lb_target_group.ml.arn_suffix
}
