# Input variables for the platform. The pipeline passes PrefixCode and Region from bootstrap, the rest come from terraform.tfvars

variable "PrefixCode" {
  description = "Prefix for resource naming"
  type        = string
}

variable "Region" {
  description = "AWS region"
  type        = string
}

variable "AvailabilityZones" {
  description = "The two availability zones for the VPC subnets, in the deploy region"
  type        = list(string)

  validation {
    condition     = length(var.AvailabilityZones) == 2
    error_message = "Name exactly two availability zones."
  }
}
variable "BedrockModelSmart" {
  description = "Bedrock model ID for complex queries (System 2)"
  type        = string
}

variable "BedrockModelFast" {
  description = "Bedrock model ID for simple queries (System 1)"
  type        = string
}

variable "RedshiftWarmupEnabled" {
  description = "Enable EventBridge schedule to keep Redshift Serverless RPUs warm"
  type        = bool
}

variable "BedrockGuardrailEnabled" {
  description = "Enable Bedrock Guardrails on all agents (true = enforce, false = bypass)"
  type        = bool
  default     = true
}

