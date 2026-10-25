variable "prefix_code" {
  description = "Prefix for resource naming"
  type        = string
}

variable "name" {
  description = "Lambda function name (without prefix)"
  type        = string
}

variable "source_dir" {
  description = "Path to Lambda source code directory"
  type        = string
}

variable "handler" {
  description = "Lambda handler (file.function)"
  type        = string
  default     = "handler.handler"
}

variable "runtime" {
  description = "Lambda runtime"
  type        = string
  default     = "python3.14"
}

variable "timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 60
}

variable "memory_size" {
  description = "Lambda memory in MB"
  type        = number
  default     = 256
}

variable "environment_variables" {
  description = "Environment variables for Lambda"
  type        = map(string)
  default     = {}
}

variable "additional_iam_statements" {
  description = "Additional IAM policy statements"
  type        = list(any)
  default     = []
}

variable "kms_key_arn" {
  description = "KMS key ARN for encrypting CloudWatch logs and Lambda env vars"
  type        = string
  default     = null
}

variable "codeblock" {
  description = "Terraform file reference for tagging"
  type        = string
}

variable "layers" {
  description = "Lambda layer ARNs for code shared between functions"
  type        = list(string)
  default     = []
}

variable "vpc_subnet_ids" {
  description = "Private subnets to attach the function to; empty keeps it outside the VPC"
  type        = list(string)
  default     = []
}

variable "vpc_security_group_ids" {
  description = "Security groups for the function's network interfaces when in the VPC"
  type        = list(string)
  default     = []
}
