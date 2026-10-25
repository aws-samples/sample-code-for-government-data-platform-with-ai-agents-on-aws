variable "prefix_code" {
  description = "Prefix for resource naming (1-10 lowercase chars)"
  type        = string
  default     = "govdata"

  validation {
    condition     = can(regex("^[a-z0-9]{1,10}$", var.prefix_code))
    error_message = "prefix_code must be 1-10 lowercase alphanumeric characters."
  }
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-2"
}

# Pipeline source

variable "codecommit_branch" {
  description = "CodeCommit branch the pipeline deploys from"
  type        = string
  default     = "main"
}

