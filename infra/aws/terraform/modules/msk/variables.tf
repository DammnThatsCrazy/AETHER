variable "environment" {
  type        = string
  description = "Deployment environment"
}

variable "project" {
  type        = string
  description = "Project name"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Isolated subnet IDs — one per broker AZ"
}

variable "msk_sg_id" {
  type        = string
  description = "Security group ID to attach to MSK brokers"
}

variable "broker_instance_type" {
  type        = string
  description = "MSK broker instance type"
  default     = "kafka.m5.large"
}

variable "kafka_version" {
  type        = string
  description = "Apache Kafka version"
  default     = "3.5.1"
}

variable "broker_count" {
  type        = number
  description = "Total number of broker nodes (multiple of AZ count)"
  default     = 3
}

variable "broker_volume_size" {
  type        = number
  description = "EBS volume size in GiB per broker"
  default     = 100
}
