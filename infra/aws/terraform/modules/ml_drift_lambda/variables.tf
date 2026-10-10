variable "environment" {
  type        = string
  description = "Deployment environment (prod, staging, dev)"
}

variable "project" {
  type        = string
  description = "Project name"
}

variable "log_bucket" {
  type        = string
  description = "S3 bucket that contains prediction logs (predictions/<model>/dt=<date>/) and drift-reference/<model>/reference.json"
}

variable "model_names" {
  type        = list(string)
  description = "ML model names to check for drift. Empty list uses the Lambda's built-in MODELS_DEFAULT list."
  default     = []
}

variable "psi_threshold" {
  type        = number
  description = "PSI value above which a model is flagged as drifted in the Lambda result (informational; the CloudWatch alarm threshold is set independently in the monitoring module)"
  default     = 0.2
}

variable "schedule_expression" {
  type        = string
  description = "EventBridge schedule expression for nightly run"
  default     = "cron(0 2 * * ? *)"
}

variable "lambda_timeout" {
  type        = number
  description = "Lambda timeout in seconds"
  default     = 300
}

variable "lambda_memory" {
  type        = number
  description = "Lambda memory in MB"
  default     = 512
}
