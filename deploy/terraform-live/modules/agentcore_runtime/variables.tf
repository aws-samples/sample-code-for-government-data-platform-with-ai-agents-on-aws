variable "prefix_code" {
  description = "Prefix for resource naming"
  type        = string
}

variable "region" {
  description = "Region the runtime and its OTLP endpoints live in"
  type        = string
}

variable "account_id" {
  description = "Account the runtime runs in, for the role trust and model ARNs"
  type        = string
}

variable "name" {
  description = "Runtime name without prefix (agent, walkthrough, geospatial); the runtime is <prefix>_<name>"
  type        = string
}

variable "description" {
  description = "Runtime description"
  type        = string
}

variable "ecr_repository_arn" {
  description = "ARN of the ECR repository the runtime pulls from"
  type        = string
}

variable "image_uri" {
  description = "Full container image URI including the tag"
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets the runtime's network interfaces are created in"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups on the runtime's network interfaces"
  type        = list(string)
}

variable "model_ids" {
  description = "Bedrock model or inference profile ids the runtime may invoke"
  type        = list(string)
}

variable "environment" {
  description = "Agent-specific environment variables, merged over the OTEL set"
  type        = map(string)
  default     = {}
}

variable "additional_iam_statements" {
  description = "Agent-specific IAM statements appended to the ECR, Bedrock and OTEL ones"
  type        = list(any)
  default     = []
}

variable "kms_key_arn" {
  description = "KMS key for the log groups and the SSM parameter"
  type        = string
}

variable "codeblock" {
  description = "Terraform file reference for tagging"
  type        = string
}
