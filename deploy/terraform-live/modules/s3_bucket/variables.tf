variable "name" {
  description = "Bucket name"
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key ARN for encryption"
  type        = string
}

variable "codeblock" {
  description = "Codeblock tag value"
  type        = string
}

variable "lifecycle_rules" {
  description = "Lifecycle rules for the bucket"
  type = list(object({
    id     = string
    prefix = optional(string)
    transitions = optional(list(object({
      days          = number
      storage_class = string
    })))
    expiration_days                    = optional(number)
    noncurrent_version_expiration_days = optional(number)
  }))
  default = []
}

variable "additional_bucket_policy_statements" {
  description = "Additional IAM policy statements to add to bucket policy"
  type        = list(any)
  default     = []
}
